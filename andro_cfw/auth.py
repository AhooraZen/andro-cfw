from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from .errors import DeploymentError
from .toolchain import check_node_toolchain

ACCOUNTS_DIR = Path.home() / ".andro_cfw" / "accounts"


def _account_env(account_label: Optional[str]) -> dict:
    """
    Build an environment dict that isolates wrangler's OAuth token storage
    per account label, so andro-cfw can hold multiple logged-in Cloudflare
    accounts at once (needed for the multi-account load-balancing feature).

    wrangler stores its OAuth config under `$WRANGLER_HOME` (if set) or
    otherwise under the user's home/config directory. We point a fake
    per-account "home" at an isolated folder so each account's login is
    completely independent from the others.
    """
    env = os.environ.copy()
    if account_label:
        account_home = ACCOUNTS_DIR / account_label
        account_home.mkdir(parents=True, exist_ok=True)
        env["WRANGLER_HOME"] = str(account_home)
        # Fallback for older wrangler versions that only respect $HOME /
        # $XDG_CONFIG_HOME for locating their config directory.
        env["XDG_CONFIG_HOME"] = str(account_home)
    return env


def cloudflare_login(account_label: Optional[str] = None) -> None:
    """
    Launch Cloudflare's official OAuth login flow via `wrangler login`.

    This opens the user's default browser, where they log into (or sign up
    for) Cloudflare and authorize the Wrangler CLI. andro-cfw never sees
    the user's Cloudflare password; authentication is handled entirely by
    Cloudflare + wrangler's own OAuth implementation.

    If `account_label` is given, the login is stored in an isolated config
    directory (see `_account_env`) so it doesn't overwrite a previous
    account's login -- this is how andro-cfw supports logging into several
    Cloudflare accounts for load-balanced deployments.
    """
    check_node_toolchain()
    label_note = f" (account: {account_label})" if account_label else ""
    print(f"\n[andro-cfw] Opening your browser for Cloudflare login{label_note}...")
    print("[andro-cfw] Please log in (or sign up) and click 'Allow' to authorize Wrangler.\n")

    result = subprocess.run(
        ["npx", "--yes", "wrangler", "login"],
        env=_account_env(account_label),
    )
    if result.returncode != 0:
        raise DeploymentError(
            "Cloudflare login failed or was cancelled. Run `andro-cfw init` again to retry."
        )


def whoami(account_label: Optional[str] = None) -> str:
    """Return the raw output of `wrangler whoami` (useful for diagnostics)."""
    check_node_toolchain()
    result = subprocess.run(
        ["npx", "--yes", "wrangler", "whoami"],
        capture_output=True, text=True,
        env=_account_env(account_label),
    )
    return result.stdout or result.stderr
