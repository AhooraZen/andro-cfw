from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .auth import cloudflare_login
from .colors import (
    COLOR_BOLD,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_RESET,
    COLOR_YELLOW,
    ColoredHelpFormatter,
    log_dim,
    log_error,
    log_info,
    log_notice,
    log_success,
    log_warn,
    log_working,
)
from .deploy import deploy_worker, put_worker_secret, teardown_worker
from .errors import AndroCFWError
from .platform_utils import add_to_user_path
from .session import DEFAULT_SESSION_FILENAME, CFWSession, require_http_url


def _session_path(args: argparse.Namespace) -> Path:
    return Path(args.path) / DEFAULT_SESSION_FILENAME if args.path else Path.cwd() / DEFAULT_SESSION_FILENAME


def cmd_init(args: argparse.Namespace) -> int:
    session_path = _session_path(args)

    if session_path.exists() and not args.force:
        log_warn(f"'{session_path}' already exists. Use --force to redeploy and overwrite it.")
        return 1

    num_accounts = max(1, args.accounts)

    try:
        if num_accounts == 1:
            cloudflare_login()
            worker_name, worker_url = deploy_worker(worker_name=args.name)
            session = CFWSession.new(worker_name=worker_name, worker_url=worker_url)
        else:
            log_info(
                f"Multi-account load-balanced mode: setting up {num_accounts} "
                "Cloudflare accounts. You'll be asked to log in once per account "
                "(each in its own isolated browser/OAuth session) -- log in with a "
                "DIFFERENT Cloudflare account each time.\n"
            )
            entries = []
            for i in range(1, num_accounts + 1):
                label = f"account-{i}"
                print(f"\n--- Account {i}/{num_accounts} ({label}) ---")
                cloudflare_login(account_label=label)
                name = f"{args.name}-{i}" if args.name else None
                worker_name, worker_url = deploy_worker(worker_name=name, account_label=label)
                entries.append((worker_name, worker_url, label))
            session = CFWSession.new_multi(entries)
    except AndroCFWError as exc:
        log_error(f"ERROR: {exc}")
        return 1

    saved_path = session.save(str(session_path))

    log_success("Success!")
    if len(session.workers) > 1:
        print(f"  Accounts    : {len(session.workers)} (load-balanced, auto failover on daily quota limit)")
        for w in session.workers:
            print(f"    - {w.account_label}: {w.worker_name} -> {w.worker_url}")
    else:
        print(f"  Worker name : {session.worker_name}")
        print(f"  Worker URL  : {session.worker_url}")
    print(f"  Session file: {saved_path}")
    print("\nUse it in your bot code (identical whether single- or multi-account):\n")
    print(f"  {COLOR_CYAN}from andro_cfw import CFWSession{COLOR_RESET}")
    print(f"  {COLOR_CYAN}session = CFWSession.load(){COLOR_RESET}")
    print(f"  {COLOR_CYAN}import telebot{COLOR_RESET}")
    print(f"  {COLOR_CYAN}telebot.apihelper.API_URL = session.telebot_api_url(){COLOR_RESET}")
    print(f"  {COLOR_CYAN}telebot.apihelper.FILE_URL = session.telebot_file_url(){COLOR_RESET}")
    print(f"  {COLOR_CYAN}bot = telebot.TeleBot('<YOUR_BOT_TOKEN>'){COLOR_RESET}")
    print(f"  {COLOR_CYAN}bot.infinity_polling(){COLOR_RESET}\n")
    return 0


def cmd_add_account(args: argparse.Namespace) -> int:
    session_path = _session_path(args)
    try:
        session = CFWSession.load(str(session_path))
    except AndroCFWError as exc:
        log_error(f"{exc}")
        return 1

    next_num = len(session.workers) + 1
    label = f"account-{next_num}"
    try:
        cloudflare_login(account_label=label)
        name = f"{args.name}-{next_num}" if args.name else None
        worker_name, worker_url = deploy_worker(worker_name=name, account_label=label)
    except AndroCFWError as exc:
        log_error(f"ERROR: {exc}")
        return 1

    from .session import WorkerEntry
    session.workers.append(WorkerEntry(worker_name=worker_name, worker_url=worker_url, account_label=label))
    session.save(str(session_path))

    log_success(f"Added '{label}' ({worker_name}) to the load-balanced pool.")
    log_info(f"Total accounts now: {len(session.workers)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        session = CFWSession.load(str(_session_path(args)) if args.path else None)
    except AndroCFWError as exc:
        log_error(f"{exc}")
        return 1

    print(f"Created at  : {session.created_at}")
    if len(session.workers) > 1:
        print(f"Mode        : multi-account load balancing ({len(session.workers)} accounts)")
        for i, w in enumerate(session.workers):
            marker = " <- active" if i == session.active_index else ""
            state = "exhausted (waiting for daily reset)" if w.exhausted_until > time.time() else "available"
            print(f"  [{i}] {w.account_label}: {w.worker_name} -> {w.worker_url} [{state}]{marker}")
    else:
        print(f"Worker name : {session.worker_name}")
        print(f"Worker URL  : {session.worker_url}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    try:
        session = CFWSession.load(str(_session_path(args)) if args.path else None)
    except AndroCFWError as exc:
        log_error(f"{exc}")
        return 1

    for w in session.workers:
        teardown_worker(w.worker_name, account_label=w.account_label)

    session_path = _session_path(args)
    if session_path.exists():
        session_path.unlink()

    log_success(f"{len(session.workers)} worker(s) deleted and local session removed.")
    return 0


def cmd_setup_path(args: argparse.Namespace) -> int:
    ok = add_to_user_path()
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    try:
        session = CFWSession.load(str(_session_path(args)) if args.path else None)
    except AndroCFWError as exc:
        log_error(f"{exc}")
        return 1

    log_working(f"Testing connectivity to {len(session.workers)} Cloudflare Worker(s)...")
    results = session.check_health(timeout=args.timeout)

    print()
    all_ok = True
    for r in results:
        label = r["account_label"] or r["worker_name"]
        if r["status"] == 200:
            status_str = f"{COLOR_GREEN}HTTP 200 OK{COLOR_RESET}"
            ping_str = f"{COLOR_CYAN}{r['latency_ms']} ms{COLOR_RESET}"
        elif r["status"] > 0:
            status_str = f"{COLOR_YELLOW}HTTP {r['status']}{COLOR_RESET}"
            ping_str = f"{r['latency_ms']} ms"
            all_ok = False
        else:
            status_str = f"{COLOR_BOLD}\033[1;31mFAILED ({r['error']}){COLOR_RESET}"
            ping_str = "-"
            all_ok = False

        state_str = f"{COLOR_YELLOW}[exhausted]{COLOR_RESET}" if r["is_exhausted"] else f"{COLOR_GREEN}[available]{COLOR_RESET}"
        print(f"  Worker [{r['index']}]: {label}")
        print(f"    URL     : {r['worker_url']}")
        print(f"    Status  : {status_str} ({ping_str})")
        print(f"    Quota   : {state_str}")
        print()

    if all_ok:
        log_success("All Cloudflare Worker proxies are healthy and responding!")
        return 0
    else:
        log_warn("One or more workers had connection or status issues.")
        return 1


# Only HTTP Bot API frameworks are listed. pyrogram / hydrogram / telethon
# speak MTProto straight to Telegram's datacenters, which a Cloudflare Worker
# HTTP proxy cannot route -- offering a snippet for them would hand the user
# code that silently does not go through the proxy.
FRAMEWORK_SNIPPETS = {
    "patch": """# The one-line option: import your framework first, then call patch().
import telebot                      # or: import aiogram / import telegram
from andro_cfw import patch

patch()                             # routes the imported framework through your worker

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Hello! This bot is running through andro-cfw.")

if __name__ == "__main__":
    bot.infinity_polling()
""",
    "telebot": """import telebot
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

# Configure telebot to route requests through andro-cfw proxy
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Hello! This bot is running through andro-cfw proxy! 🚀")

if __name__ == "__main__":
    print("Bot is starting via andro-cfw proxy...")
    bot.infinity_polling()
""",
    "ptb": """from telegram.ext import ApplicationBuilder, CommandHandler
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

app = (
    ApplicationBuilder()
    .token("YOUR_BOT_TOKEN")
    .base_url(session.ptb_base_url())
    .base_file_url(session.ptb_base_file_url())
    .build()
)

async def start(update, context):
    await update.message.reply_text("Hello! This bot is running through andro-cfw proxy! 🚀")

app.add_handler(CommandHandler("start", start))

if __name__ == "__main__":
    print("Bot is starting via andro-cfw proxy...")
    app.run_polling()
""",
    "aiogram": """import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

api_server = TelegramAPIServer(**session.aiogram_server_url())
bot = Bot(
    token="YOUR_BOT_TOKEN",
    session=AiohttpSession(api=api_server),
)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("Hello! This bot is running through andro-cfw proxy! 🚀")

async def main():
    print("Bot is starting via andro-cfw proxy...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
""",
}

MTPROTO_NOTE = (
    "pyrogram, hydrogram and telethon speak MTProto directly to Telegram's "
    "datacenters, not the HTTP Bot API. A Cloudflare Worker HTTP proxy cannot "
    "route them. Use their built-in SOCKS5/MTProto proxy settings instead."
)


def cmd_snippet(args: argparse.Namespace) -> int:
    fw = args.framework.lower()
    if fw in ("pyrogram", "hydrogram", "telethon"):
        log_error(f"andro-cfw cannot proxy '{fw}'.")
        log_dim(MTPROTO_NOTE)
        return 1
    if fw not in FRAMEWORK_SNIPPETS:
        log_error(f"Unknown framework '{fw}'. Choose from: {', '.join(FRAMEWORK_SNIPPETS.keys())}")
        return 1

    code = FRAMEWORK_SNIPPETS[fw]
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(code, encoding="utf-8")
        log_success(f"Generated {fw} starter bot snippet to '{out_path}'")
    else:
        print(f"\n--- Starter code for {COLOR_CYAN}{fw}{COLOR_RESET} ---")
        print(code)
    return 0


# A Bot API token is "<numeric bot id>:<35-char base64url secret>".
BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


def _read_bot_token(args: argparse.Namespace) -> str | None:
    """
    Resolve the bot token from --token, $TELEGRAM_BOT_TOKEN, or an interactive
    prompt. The prompt uses getpass so the token is not echoed to the terminal
    or captured in a screen recording / shoulder-surfed.
    """
    token = getattr(args, "token", None) or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        try:
            token = getpass.getpass(
                f"{COLOR_BOLD}{COLOR_CYAN}[andro-cfw]{COLOR_RESET} "
                "Telegram Bot Token from @BotFather (input hidden): "
            )
        except (KeyboardInterrupt, EOFError):
            return None
    return (token or "").strip()


def cmd_deploy_serverless(args: argparse.Namespace) -> int:
    session_path = _session_path(args)

    try:
        session = CFWSession.load(str(session_path) if args.path else None)
    except AndroCFWError:
        log_warn("No active session found. Running `andro-cfw init` first...")
        init_args = argparse.Namespace(name=getattr(args, "name", None), path=args.path, force=False, accounts=1)
        if cmd_init(init_args) != 0:
            return 1
        session = CFWSession.load(str(session_path) if args.path else None)

    token = _read_bot_token(args)
    if token is None:
        log_warn("\nOperation cancelled.")
        return 130
    if not BOT_TOKEN_RE.match(token):
        log_error(
            "That does not look like a Telegram bot token. Expected the form "
            "123456789:AA... as issued by @BotFather."
        )
        return 1

    worker = session.workers[0] if session.workers else None
    if worker is None:
        log_error("This session has no deployed worker. Run `andro-cfw init` first.")
        return 1
    worker_url = worker.worker_url.rstrip("/")
    webhook_url = f"{worker_url}/webhook"

    # Telegram echoes this secret in the X-Telegram-Bot-Api-Secret-Token header
    # of every update, and the worker rejects updates without it. That is what
    # stops anyone who learns the worker URL from injecting fake updates.
    webhook_secret = secrets.token_urlsafe(32)

    log_working("Storing bot credentials as encrypted Cloudflare Worker secrets...")
    try:
        put_worker_secret(worker.worker_name, "BOT_TOKEN", token, worker.account_label)
        put_worker_secret(worker.worker_name, "WEBHOOK_SECRET", webhook_secret, worker.account_label)
        forward_url = getattr(args, "forward_url", None)
        if forward_url:
            put_worker_secret(worker.worker_name, "FORWARD_WEBHOOK_URL", forward_url, worker.account_label)
    except AndroCFWError as exc:
        log_error(f"{exc}")
        return 1

    log_working("Registering the webhook with Telegram through your worker...")
    ok, description = _register_webhook(worker_url, token, webhook_url, webhook_secret)

    print(f"\n  {COLOR_BOLD}Worker URL{COLOR_RESET}    : {COLOR_CYAN}{worker_url}{COLOR_RESET}")
    print(f"  {COLOR_BOLD}Webhook URL{COLOR_RESET}   : {COLOR_CYAN}{webhook_url}{COLOR_RESET}")
    if forward_url:
        print(f"  {COLOR_BOLD}Forwarding to{COLOR_RESET} : {COLOR_CYAN}{forward_url}{COLOR_RESET}")

    if ok:
        print(f"  {COLOR_BOLD}Webhook Status{COLOR_RESET}: {COLOR_GREEN}Registered with Telegram{COLOR_RESET}\n")
        log_success("Serverless Cloudflare bot deployment complete.")
        if not forward_url:
            log_notice(
                "No --forward-url was given, so the worker will accept and "
                "acknowledge updates without routing them anywhere yet."
            )
        return 0

    print(f"  {COLOR_BOLD}Webhook Status{COLOR_RESET}: {COLOR_RED}Not registered{COLOR_RESET}\n")
    log_error(f"Telegram rejected the webhook registration: {description}")
    log_dim("The worker itself is deployed and its secrets are stored; only the")
    log_dim("setWebhook call failed. Re-run this command to retry.")
    return 1


def _register_webhook(worker_url: str, token: str, webhook_url: str, secret: str) -> tuple[bool, str]:
    """
    Call setWebhook via the deployed worker and report Telegram's own verdict.

    Returns (ok, description). An HTTP 200 is not success on its own: the Bot
    API answers `{"ok": false, "description": ...}` with status 200 for many
    rejections, so the JSON body is what decides.
    """
    payload = json.dumps({
        "url": webhook_url,
        "secret_token": secret,
        "drop_pending_updates": True,
    }).encode("utf-8")

    request = urllib.request.Request(  # noqa: S310 - scheme pinned by require_http_url
        require_http_url(f"{worker_url}/bot{token}/setWebhook"),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "andro-cfw"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 - scheme pinned above
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return False, f"HTTP {exc.code} from the worker"
    except Exception as exc:
        return False, str(exc)

    if isinstance(body, dict) and body.get("ok") is True:
        return True, str(body.get("description", "ok"))
    description = body.get("description", "unknown error") if isinstance(body, dict) else "malformed response"
    return False, str(description)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="andro-cfw",
        description=f"{COLOR_BOLD}{COLOR_CYAN}andro-cfw{COLOR_RESET} - Run Telegram bots through your own Cloudflare Worker proxy.",
        formatter_class=ColoredHelpFormatter,
    )
    from . import __version__
    parser.add_argument("--version", action="version", version=f"andro-cfw {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Log into Cloudflare and deploy the proxy worker(s) for this project.", formatter_class=ColoredHelpFormatter)
    p_init.add_argument("--name", help="Custom worker name (default: random andro-cfw-xxxxxxxx)")
    p_init.add_argument("--path", help="Project directory (default: current directory)")
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing cfw.session")
    p_init.add_argument(
        "--accounts", type=int, default=1,
        help="Number of Cloudflare accounts to set up for smart load balancing "
             "(each account gives you its own 100k req/day free quota; andro-cfw "
             "auto-switches between them and resets daily). Default: 1.",
    )
    p_init.set_defaults(func=cmd_init)

    p_serverless = sub.add_parser("deploy-serverless", aliases=["serverless", "deploy-webhook"], help="Deploy a 100% serverless 24/7 Telegram bot to Cloudflare Edge.", formatter_class=ColoredHelpFormatter)
    p_serverless.add_argument(
        "--token",
        help="Telegram bot token from @BotFather. Prefer $TELEGRAM_BOT_TOKEN or the "
             "hidden prompt: an argv token is visible to every process on the machine.",
    )
    p_serverless.add_argument(
        "--forward-url",
        help="Your backend URL. Updates received by the worker are POSTed here verbatim.",
    )
    p_serverless.add_argument("--path", help="Project directory (default: current directory)")
    p_serverless.set_defaults(func=cmd_deploy_serverless)

    p_add = sub.add_parser("add-account", help="Add one more Cloudflare account/worker to an existing load-balanced session.", formatter_class=ColoredHelpFormatter)
    p_add.add_argument("--name", help="Base name for the new worker")
    p_add.add_argument("--path", help="Project directory (default: current directory)")
    p_add.set_defaults(func=cmd_add_account)

    p_status = sub.add_parser("status", help="Show info about the current project's worker(s).", formatter_class=ColoredHelpFormatter)
    p_status.add_argument("--path", help="Project directory (default: current directory)")
    p_status.set_defaults(func=cmd_status)

    p_check = sub.add_parser("check", help="Test live network connectivity and ping response times of deployed worker(s).", formatter_class=ColoredHelpFormatter)
    p_check.add_argument("--path", help="Project directory (default: current directory)")
    p_check.add_argument("--timeout", type=int, default=5, help="HTTP connection timeout in seconds (default: 5)")
    p_check.set_defaults(func=cmd_check)

    p_snippet = sub.add_parser("snippet", help="Generate ready-to-run Python code for telebot, ptb, or aiogram.", formatter_class=ColoredHelpFormatter)
    # No `choices=`: cmd_snippet explains *why* pyrogram/hydrogram are refused,
    # which argparse's "invalid choice" error cannot.
    p_snippet.add_argument(
        "--framework", "-f", default="telebot", metavar="{" + ",".join(sorted(FRAMEWORK_SNIPPETS)) + "}",
        help="Framework name (default: telebot)",
    )
    p_snippet.add_argument("--out", "-o", help="Optional output file path to write code to (e.g. bot.py)")
    p_snippet.set_defaults(func=cmd_snippet)

    p_remove = sub.add_parser("remove", help="Delete the deployed worker(s) and local session.", formatter_class=ColoredHelpFormatter)
    p_remove.add_argument("--path", help="Project directory (default: current directory)")
    p_remove.set_defaults(func=cmd_remove)

    p_path = sub.add_parser("setup-path", help="Safely add andro-cfw's executable folder to your User PATH.", formatter_class=ColoredHelpFormatter)
    p_path.set_defaults(func=cmd_setup_path)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log_warn("\nOperation cancelled by user.")
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log_warn("\nOperation cancelled by user.")
        sys.exit(130)
