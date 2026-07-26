from __future__ import annotations

import os
import shutil
import subprocess

from .errors import ToolchainMissingError
from .platform_utils import SystemInfo, detect_system, install_nodejs


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


def _node_present() -> bool:
    return bool(_run_version("node") and _run_version("npx"))


def check_node_toolchain(auto_install: bool = True) -> SystemInfo:
    """
    Ensure Node.js/npm/npx (required to run Cloudflare's official `wrangler`
    CLI) are available on this machine.

    Behavior:
      1. Detect the host OS (Windows / macOS / Linux) and, on Linux, the
         distro + best package manager (apt/dnf/yum/pacman/zypper/apk).
      2. If node/npx are already installed, return immediately.
      3. Otherwise, if auto_install is True, attempt an unattended install
         using the platform's native package manager.
      4. Re-check afterwards; if still missing, raise ToolchainMissingError
         with manual instructions tailored to the detected system.

    Returns the detected SystemInfo (useful for logging/diagnostics).
    """
    info = detect_system()

    if _node_present():
        return info

    # Installing system packages is a privileged, machine-wide side effect.
    # ANDRO_CFW_NO_AUTO_INSTALL lets CI and locked-down machines refuse it.
    if os.environ.get("ANDRO_CFW_NO_AUTO_INSTALL", "").strip().lower() in ("1", "true", "yes"):
        auto_install = False

    if not auto_install:
        raise ToolchainMissingError(_manual_instructions(info))

    installed = install_nodejs(info)

    if installed and _node_present():
        print("[andro-cfw] Node.js installed successfully.")
        return info

    raise ToolchainMissingError(_manual_instructions(info))


def _manual_instructions(info: SystemInfo) -> str:
    base = (
        "Node.js and npx are required (andro-cfw uses Cloudflare's official "
        "`wrangler` CLI under the hood to log in and deploy your worker).\n"
        f"Detected system: {info.pretty()}\n"
        "Automatic installation did not succeed. Please install Node.js manually:\n"
    )
    if info.os_family == "windows":
        base += (
            "  - winget install -e --id OpenJS.NodeJS.LTS\n"
            "  - or download the installer from https://nodejs.org\n"
        )
    elif info.os_family == "macos":
        base += (
            "  - brew install node   (install Homebrew from https://brew.sh first)\n"
            "  - or download the installer from https://nodejs.org\n"
        )
    elif info.os_family == "linux":
        base += (
            "  - Debian/Ubuntu : sudo apt-get update && sudo apt-get install -y nodejs npm\n"
            "  - Fedora/RHEL   : sudo dnf install -y nodejs npm\n"
            "  - Arch/Manjaro  : sudo pacman -Sy nodejs npm\n"
            "  - openSUSE      : sudo zypper install nodejs npm\n"
            "  - Alpine        : sudo apk add nodejs npm\n"
            "  - or use nvm: https://github.com/nvm-sh/nvm\n"
        )
    else:
        base += "  - Download and install from https://nodejs.org\n"

    base += "\nThen run `andro-cfw init` again."
    return base
