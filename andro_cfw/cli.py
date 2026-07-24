from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import cloudflare_login
from .colors import log_info, log_working, log_success, log_error, log_warn, COLOR_GREEN, COLOR_RESET, COLOR_BOLD, COLOR_CYAN
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
            state = "exhausted (waiting for daily reset)" if w.exhausted_until > __import__("time").time() else "available"
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="andro-cfw", description="Run Telegram bots through your own Cloudflare Worker proxy.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Log into Cloudflare and deploy the proxy worker(s) for this project.")
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

    p_add = sub.add_parser("add-account", help="Add one more Cloudflare account/worker to an existing load-balanced session.")
    p_add.add_argument("--name", help="Base name for the new worker")
    p_add.add_argument("--path", help="Project directory (default: current directory)")
    p_add.set_defaults(func=cmd_add_account)

    p_status = sub.add_parser("status", help="Show info about the current project's worker(s).")
    p_status.add_argument("--path", help="Project directory (default: current directory)")
    p_status.set_defaults(func=cmd_status)

    p_remove = sub.add_parser("remove", help="Delete the deployed worker(s) and local session.")
    p_remove.add_argument("--path", help="Project directory (default: current directory)")
    p_remove.set_defaults(func=cmd_remove)

    p_path = sub.add_parser("setup-path", help="Safely add andro-cfw's executable folder to your User PATH.")
    p_path.set_defaults(func=cmd_setup_path)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
