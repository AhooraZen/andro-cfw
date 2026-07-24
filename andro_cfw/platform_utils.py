from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from .colors import log_info, log_working, log_success, log_error, log_dim


@dataclass
class SystemInfo:
    """
    Describes the host system so andro-cfw can pick the right way to
    check for / install Node.js.

    os_family: "windows", "macos" or "linux"
    distro:    Linux distro id (from /etc/os-release), e.g. "ubuntu",
               "debian", "fedora", "arch", "alpine", "opensuse" ... or
               None on non-Linux systems.
    package_manager: best package manager found for this system
               ("winget", "choco", "brew", "apt", "dnf", "yum", "pacman",
               "zypper", "apk", or None if nothing usable was found).
    is_root:   True if the current process can install system packages
               without needing `sudo` (root on Linux/macOS, or elevated
               on Windows is not required for winget/choco per-user installs).
    """

    os_family: str
    distro: Optional[str]
    distro_like: Optional[str]
    package_manager: Optional[str]
    is_root: bool
    arch: str

    def pretty(self) -> str:
        if self.os_family == "linux":
            return f"Linux ({self.distro or 'unknown distro'}, package manager: {self.package_manager or 'none found'})"
        if self.os_family == "macos":
            return f"macOS (package manager: {self.package_manager or 'none found'})"
        if self.os_family == "windows":
            return f"Windows (package manager: {self.package_manager or 'none found'})"
        return f"{self.os_family} (unrecognized)"


def _read_os_release() -> dict:
    data = {}
    path = "/etc/os-release"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    data[key] = value.strip().strip('"')
        except OSError:
            pass
    return data


def _first_available(*candidates: str) -> Optional[str]:
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return None


def detect_system() -> SystemInfo:
    """Detect OS, Linux distro (if any) and the best available package manager."""
    system = platform.system().lower()
    arch = platform.machine()

    if system == "windows":
        pm = _first_available("winget", "choco", "scoop")
        return SystemInfo(
            os_family="windows",
            distro=None,
            distro_like=None,
            package_manager=pm,
            is_root=True,
            arch=arch,
        )

    if system == "darwin":
        pm = _first_available("brew", "port")
        return SystemInfo(
            os_family="macos",
            distro=None,
            distro_like=None,
            package_manager=pm,
            is_root=(os.geteuid() == 0) if hasattr(os, "geteuid") else False,
            arch=arch,
        )

    if system == "linux":
        release = _read_os_release()
        distro_id = release.get("ID", "").lower() or None
        distro_like = release.get("ID_LIKE", "").lower() or None

        pm = None
        if distro_id in ("ubuntu", "debian", "linuxmint", "pop", "raspbian") or (
            distro_like and ("debian" in distro_like or "ubuntu" in distro_like)
        ):
            pm = _first_available("apt-get", "apt")
        elif distro_id in ("fedora", "rhel", "centos", "rocky", "almalinux") or (
            distro_like and ("fedora" in distro_like or "rhel" in distro_like)
        ):
            pm = _first_available("dnf", "yum")
        elif distro_id in ("arch", "manjaro", "endeavouros", "parch") or (
            distro_like and "arch" in distro_like
        ):
            pm = _first_available("pacman")
        elif distro_id in ("opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles") or (
            distro_like and "suse" in distro_like
        ):
            pm = _first_available("zypper")
        elif distro_id == "alpine":
            pm = _first_available("apk")
        else:
            pm = _first_available("apt-get", "dnf", "yum", "pacman", "zypper", "apk")

        return SystemInfo(
            os_family="linux",
            distro=distro_id,
            distro_like=distro_like,
            package_manager=pm,
            is_root=(os.geteuid() == 0) if hasattr(os, "geteuid") else False,
            arch=arch,
        )

    return SystemInfo(
        os_family=system or "unknown",
        distro=None,
        distro_like=None,
        package_manager=None,
        is_root=False,
        arch=arch,
    )


def _run(cmd: list[str], *, use_sudo: bool = False, timeout: int = 600) -> subprocess.CompletedProcess:
    if use_sudo and shutil.which("sudo") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd] if _sudo_noninteractive_ok() else ["sudo", *cmd]
    log_dim(f"Executing: {' '.join(cmd)}")
    return subprocess.run(cmd, timeout=timeout)


def _sudo_noninteractive_ok() -> bool:
    """Check whether `sudo` can run without prompting for a password."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def install_nodejs(info: SystemInfo) -> bool:
    """
    Attempt to automatically install Node.js (which brings npm/npx along)
    using the best package manager detected for this system.
    """
    log_info(f"Detected system: {info.pretty()}")
    log_working("Node.js/npx not found — attempting automatic installation using system package manager...")

    try:
        if info.os_family == "windows":
            return _install_windows(info)
        if info.os_family == "macos":
            return _install_macos(info)
        if info.os_family == "linux":
            return _install_linux(info)
    except subprocess.TimeoutExpired:
        log_error("Installation timed out.")
        return False
    except Exception as exc:  # noqa: BLE001
        log_error(f"Automatic installation failed: {exc}")
        return False

    return False


def _install_windows(info: SystemInfo) -> bool:
    if info.package_manager == "winget":
        result = _run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                        "--accept-source-agreements", "--accept-package-agreements"])
        return result.returncode == 0
    if info.package_manager == "choco":
        result = _run(["choco", "install", "nodejs-lts", "-y"])
        return result.returncode == 0
    if info.package_manager == "scoop":
        result = _run(["scoop", "install", "nodejs-lts"])
        return result.returncode == 0
    log_error(
        "No supported Windows package manager found (winget/choco/scoop).\n"
        "Install winget or download Node.js manually from https://nodejs.org"
    )
    return False


def _install_macos(info: SystemInfo) -> bool:
    if info.package_manager == "brew":
        result = _run(["brew", "install", "node"])
        return result.returncode == 0
    if info.package_manager == "port":
        result = _run(["port", "install", "nodejs20"], use_sudo=True)
        return result.returncode == 0
    log_error(
        "Homebrew not found. Install it from https://brew.sh or download Node.js manually from https://nodejs.org"
    )
    return False


def _install_linux(info: SystemInfo) -> bool:
    pm = info.package_manager
    if pm in ("apt-get", "apt"):
        if shutil.which("curl") or shutil.which("wget"):
            fetcher = ["curl", "-fsSL"] if shutil.which("curl") else ["wget", "-qO-"]
            setup = subprocess.run(
                [*fetcher, "https://deb.nodesource.com/setup_lts.x"],
                capture_output=True, timeout=60,
            )
            if setup.returncode == 0 and setup.stdout:
                bash_cmd = ["bash", "-c", setup.stdout.decode("utf-8", "ignore")]
                _run(bash_cmd, use_sudo=True)
                result = _run(["apt-get", "install", "-y", "nodejs"], use_sudo=True)
                if result.returncode == 0:
                    return True
        _run(["apt-get", "update"], use_sudo=True)
        result = _run(["apt-get", "install", "-y", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    if pm == "dnf":
        result = _run(["dnf", "install", "-y", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    if pm == "yum":
        result = _run(["yum", "install", "-y", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    if pm == "pacman":
        log_info("Installing nodejs and npm via pacman package manager...")
        result = _run(["pacman", "-Sy", "--noconfirm", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    if pm == "zypper":
        result = _run(["zypper", "--non-interactive", "install", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    if pm == "apk":
        result = _run(["apk", "add", "--no-cache", "nodejs", "npm"], use_sudo=True)
        return result.returncode == 0

    log_error(
        "No supported Linux package manager found (apt/dnf/yum/pacman/zypper/apk).\n"
        "Install Node.js manually from https://nodejs.org or via nvm."
    )
    return False
