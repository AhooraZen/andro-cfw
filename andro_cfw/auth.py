from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Optional

from .colors import log_dim, log_step, log_working
from .errors import DeploymentError
from .toolchain import check_node_toolchain

ACCOUNTS_DIR = Path.home() / ".andro_cfw" / "accounts"

# Account labels become directory names under the user's home directory, so
# they must not be able to escape it (e.g. "../../.ssh").
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_account_label(account_label: str) -> str:
    if not _SAFE_LABEL_RE.match(account_label) or account_label in (".", ".."):
        raise DeploymentError(
            f"Invalid account label '{account_label}'. "
            "Use only letters, digits, dots, dashes and underscores."
        )
    return account_label


def _account_env(account_label: Optional[str]) -> dict:
    """
    Build an environment dict that isolates wrangler's OAuth token storage
    per account label, so andro-cfw can hold multiple logged-in Cloudflare
    accounts at once (needed for the multi-account load-balancing feature).

    The per-account directory holds live Cloudflare OAuth tokens, so it is
    created 0700 rather than inheriting the default umask.
    """
    env = os.environ.copy()
    if account_label:
        account_home = ACCOUNTS_DIR / _validate_account_label(account_label)
        account_home.mkdir(parents=True, exist_ok=True)
        for directory in (ACCOUNTS_DIR, account_home):
            try:
                os.chmod(directory, stat.S_IRWXU)
            except OSError:
                pass
        env["WRANGLER_HOME"] = str(account_home)
        env["XDG_CONFIG_HOME"] = str(account_home)
    return env


def cloudflare_login(account_label: Optional[str] = None) -> None:
    """
    Launch Cloudflare's official OAuth login flow via `wrangler login`.
    """
    log_working("Checking and verifying Node.js & Wrangler toolchain...")
    check_node_toolchain()

    label_note = f" (account: {account_label})" if account_label else ""
    log_working(f"Downloading & preparing Cloudflare Wrangler CLI{label_note}...")
    log_step(f"Opening your browser for Cloudflare login{label_note}...")
    log_dim("Please log in (or sign up) and click 'Allow' to authorize Wrangler.")
    log_dim("(If your browser does not open automatically, copy the link printed below by Wrangler into your browser)\n")

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
