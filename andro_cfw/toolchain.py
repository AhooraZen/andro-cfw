from __future__ import annotations

import shutil
import subprocess

from .errors import ToolchainMissingError


def _run_version(cmd: str) -> str | None:
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=15
        )
        return out.stdout.strip() or out.stderr.strip()
    except Exception:
        return None


def check_node_toolchain() -> None:
    """
    Raise ToolchainMissingError with clear instructions if Node.js/npm/npx
    (required to run Cloudflare's official `wrangler` CLI) are not installed.
    """
    node_version = _run_version("node")
    npx_version = _run_version("npx")

    if not node_version or not npx_version:
        raise ToolchainMissingError(
            "Node.js and npx are required (andro-cfw uses Cloudflare's official "
            "`wrangler` CLI under the hood to log in and deploy your worker).\n"
            "Install Node.js (which includes npm/npx) from https://nodejs.org "
            "and then run `andro-cfw init` again."
        )
