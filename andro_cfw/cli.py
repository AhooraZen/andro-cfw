from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import cloudflare_login
from .deploy import deploy_worker, teardown_worker
from .errors import AndroCFWError
from .session import CFWSession, DEFAULT_SESSION_FILENAME


def cmd_init(args: argparse.Namespace) -> int:
    session_path = Path(args.path) / DEFAULT_SESSION_FILENAME if args.path else Path.cwd() / DEFAULT_SESSION_FILENAME

    if session_path.exists() and not args.force:
        print(f"[andro-cfw] '{session_path}' already exists. Use --force to redeploy and overwrite it.")
        return 1

    try:
        cloudflare_login()
        worker_name, worker_url = deploy_worker(worker_name=args.name)
    except AndroCFWError as exc:
        print(f"[andro-cfw] ERROR: {exc}")
        return 1

    session = CFWSession.new(worker_name=worker_name, worker_url=worker_url)
    saved_path = session.save(str(session_path))

    print("\n[andro-cfw] Success!")
    print(f"  Worker name : {worker_name}")
    print(f"  Worker URL  : {worker_url}")
    print(f"  Session file: {saved_path}")
    print("\nUse it in your bot code:\n")
    print("  from andro_cfw import CFWSession")
    print("  session = CFWSession.load()")
    print("  import telebot")
    print("  telebot.apihelper.API_URL = session.telebot_api_url()")
    print("  telebot.apihelper.FILE_URL = session.telebot_file_url()")
    print("  bot = telebot.TeleBot('<YOUR_BOT_TOKEN>')")
    print("  bot.infinity_polling()\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        session = CFWSession.load(args.path)
    except AndroCFWError as exc:
        print(f"[andro-cfw] {exc}")
        return 1

    print(f"Worker name : {session.worker_name}")
    print(f"Worker URL  : {session.worker_url}")
    print(f"Created at  : {session.created_at}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    try:
        session = CFWSession.load(args.path)
    except AndroCFWError as exc:
        print(f"[andro-cfw] {exc}")
        return 1

    teardown_worker(session.worker_name)

    session_path = Path(args.path) / DEFAULT_SESSION_FILENAME if args.path else Path.cwd() / DEFAULT_SESSION_FILENAME
    if session_path.exists():
        session_path.unlink()

    print(f"[andro-cfw] Worker '{session.worker_name}' deleted and local session removed.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="andro-cfw", description="Run Telegram bots through your own Cloudflare Worker proxy.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Log into Cloudflare and deploy the proxy worker for this project.")
    p_init.add_argument("--name", help="Custom worker name (default: random andro-cfw-xxxxxxxx)")
    p_init.add_argument("--path", help="Project directory (default: current directory)")
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing cfw.session")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Show info about the current project's worker.")
    p_status.add_argument("--path", help="Project directory (default: current directory)")
    p_status.set_defaults(func=cmd_status)

    p_remove = sub.add_parser("remove", help="Delete the deployed worker and local session.")
    p_remove.add_argument("--path", help="Project directory (default: current directory)")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
