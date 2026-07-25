from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .auth import cloudflare_login
from .colors import (
    log_info, log_working, log_success, log_error, log_warn, log_notice, log_dim,
    COLOR_GREEN, COLOR_RESET, COLOR_BOLD, COLOR_CYAN, COLOR_BLUE, COLOR_RED, COLOR_YELLOW, ColoredHelpFormatter
)
from .deploy import deploy_worker, teardown_worker
from .errors import AndroCFWError
from .platform_utils import add_to_user_path
from .session import CFWSession, DEFAULT_SESSION_FILENAME


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


FRAMEWORK_SNIPPETS = {
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
    "pyrogram": """from pyrogram import Client, filters
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

app = Client(
    "andro_bot",
    bot_token="YOUR_BOT_TOKEN",
    api_id=12345,          # Replace with your Telegram API ID
    api_hash="YOUR_API_HASH", # Replace with your Telegram API Hash
)

# Set Pyrogram HTTP base URL override
app.api_url = session.api_base_url()

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text("Hello! Pyrogram is running through andro-cfw proxy! 🚀")

if __name__ == "__main__":
    print("Pyrogram bot starting via andro-cfw proxy...")
    app.run()
""",
    "hydrogram": """from hydrogram import Client, filters
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

app = Client(
    "andro_bot",
    bot_token="YOUR_BOT_TOKEN",
    api_id=12345,          # Replace with your Telegram API ID
    api_hash="YOUR_API_HASH", # Replace with your Telegram API Hash
)

# Set Hydrogram HTTP base URL override
app.api_url = session.api_base_url()

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text("Hello! Hydrogram is running through andro-cfw proxy! 🚀")

if __name__ == "__main__":
    print("Hydrogram bot starting via andro-cfw proxy...")
    app.run()
""",
}


def cmd_snippet(args: argparse.Namespace) -> int:
    fw = args.framework.lower()
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


def cmd_deploy_serverless(args: argparse.Namespace) -> int:
    session_path = _session_path(args)

    try:
        session = CFWSession.load(str(session_path) if args.path else None)
    except AndroCFWError:
        log_warn("No active session found. Running `andro-cfw init` first...")
        init_args = argparse.Namespace(name=args.name if hasattr(args, "name") else None, path=args.path, force=False, accounts=1)
        if cmd_init(init_args) != 0:
            return 1
        session = CFWSession.load(str(session_path) if args.path else None)

    token = getattr(args, "token", None)
    if not token:
        try:
            token = input(f"{COLOR_BOLD}{COLOR_CYAN}[andro-cfw]{COLOR_RESET} Enter your Telegram Bot Token from @BotFather: ").strip()
        except (KeyboardInterrupt, EOFError):
            log_warn("\nOperation cancelled.")
            return 130

    if not token or ":" not in token:
        log_error("Invalid Telegram Bot Token format. Token must contain a colon (e.g. 123456789:ABCDefgh...)")
        return 1

    bot_file = getattr(args, "bot_file", None)
    if not bot_file and not getattr(args, "yes", False):
        try:
            bot_file = input(f"{COLOR_BOLD}{COLOR_CYAN}[andro-cfw]{COLOR_RESET} Optional: Enter path to your bot script file (Python/JS/etc) [Press Enter to skip]: ").strip()
        except (KeyboardInterrupt, EOFError):
            pass

    if bot_file and Path(bot_file).exists():
        log_info(f"Detected bot script at '{bot_file}'.")

    import urllib.parse
    worker_url = session.worker_url.rstrip("/")
    webhook_url = f"{worker_url}/webhook?token={token}"
    telegram_set_webhook_url = f"https://api.telegram.org/bot{token}/setWebhook?url={urllib.parse.quote(webhook_url, safe='')}"

    log_working("Registering 100% Serverless Webhook on Cloudflare Edge...")

    # Attempt automatic Webhook registration through the worker proxy itself
    import urllib.request
    proxy_webhook_req = f"{worker_url}/bot{token}/setWebhook?url={urllib.parse.quote(webhook_url, safe='')}"
    registered = False
    try:
        req = urllib.request.Request(proxy_webhook_req, headers={"User-Agent": "andro-cfw"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                registered = True
    except Exception:
        pass

    log_success("100% Serverless Cloudflare Bot Deployment Complete! 🚀")
    print(f"\n  {COLOR_BOLD}Worker URL{COLOR_RESET}   : {COLOR_CYAN}{worker_url}{COLOR_RESET}")
    print(f"  {COLOR_BOLD}Webhook URL{COLOR_RESET}  : {COLOR_CYAN}{webhook_url}{COLOR_RESET}")
    if registered:
        print(f"  {COLOR_BOLD}Webhook Status{COLOR_RESET}: {COLOR_GREEN}Registered successfully with Telegram!{COLOR_RESET}")
    else:
        print(f"  {COLOR_BOLD}Webhook Status{COLOR_RESET}: {COLOR_YELLOW}Ready for registration{COLOR_RESET}")

    print(f"\n{COLOR_BOLD}{COLOR_BLUE}🔗 Direct Webhook Registration Link:{COLOR_RESET}")
    print(f"   {COLOR_CYAN}{telegram_set_webhook_url}{COLOR_RESET}\n")

    log_notice("ℹ️  Note on Browser Webhook Registration:")
    log_dim("   Since api.telegram.org is network-filtered in restricted regions, please ensure")
    log_dim("   your VPN is enabled for 2 seconds if opening the api.telegram.org link in your browser.")
    log_dim("   You ONLY need a VPN for this one-time setup link. Afterwards, Telegram and Cloudflare")
    log_dim("   communicate 24/7 in the cloud with ZERO VPN required forever!\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="andro-cfw",
        description=f"{COLOR_BOLD}{COLOR_CYAN}andro-cfw{COLOR_RESET} - Run Telegram bots through your own Cloudflare Worker proxy.",
        formatter_class=ColoredHelpFormatter,
    )
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
    p_serverless.add_argument("--token", help="Telegram bot token from @BotFather")
    p_serverless.add_argument("--bot-file", help="Path to bot code file (Python, JS, etc.)")
    p_serverless.add_argument("--path", help="Project directory (default: current directory)")
    p_serverless.add_argument("--yes", "-y", action="store_true", help="Skip interactive prompts")
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

    p_snippet = sub.add_parser("snippet", help="Generate ready-to-run Python code for telebot, ptb, aiogram, pyrogram, or hydrogram.", formatter_class=ColoredHelpFormatter)
    p_snippet.add_argument("--framework", "-f", default="telebot", choices=["telebot", "ptb", "aiogram", "pyrogram", "hydrogram"], help="Framework name (default: telebot)")
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
