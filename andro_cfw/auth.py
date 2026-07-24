from __future__ import annotations

import subprocess

from .errors import DeploymentError
from .toolchain import check_node_toolchain


def cloudflare_login() -> None:
    """
    Launch Cloudflare's official OAuth login flow via `wrangler login`.

    This opens the user's default browser, where they log into (or sign up
    for) Cloudflare and authorize the Wrangler CLI. andro-cfw never sees
    the user's Cloudflare password; authentication is handled entirely by
    Cloudflare + wrangler's own OAuth implementation.
    """
    check_node_toolchain()
    print("\n[andro-cfw] Opening your browser for Cloudflare login...")
    print("[andro-cfw] Please log in (or sign up) and click 'Allow' to authorize Wrangler.\n")

    result = subprocess.run(["npx", "--yes", "wrangler", "login"])
    if result.returncode != 0:
        raise DeploymentError(
            "Cloudflare login failed or was cancelled. Run `andro-cfw init` again to retry."
        )


def whoami() -> str:
    """Return the raw output of `wrangler whoami` (useful for diagnostics)."""
    check_node_toolchain()
    result = subprocess.run(
        ["npx", "--yes", "wrangler", "whoami"], capture_output=True, text=True
    )
    return result.stdout or result.stderr
