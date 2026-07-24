from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
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


def add_to_user_path(target_dir: Optional[Path] = None) -> bool:
    """
    Safely append target_dir (or directory containing andro-cfw executable) to the user's PATH.

    IMPORTANT SAFETY GUARANTEE:
    - On Windows: Uses Python's native `winreg` module to read HKCU\\Environment\\PATH,
      appends target_dir using ';' separator if missing, and NEVER overwrites existing PATH entries.
    - On Linux/macOS: Appends `export PATH="<target_dir>:$PATH"` to shell rc file (~/.bashrc or ~/.zshrc).
    """
    sys_family = platform.system().lower()

    if target_dir is None:
        user_bin = Path.home() / ".local" / "bin"
        exec_bin = Path(sys.executable).parent
        if (exec_bin / "andro-cfw").exists() or (exec_bin / "andro-cfw.exe").exists():
            target_dir = exec_bin
        elif (user_bin / "andro-cfw").exists() or (user_bin / "andro-cfw.exe").exists():
            target_dir = user_bin
        elif sys_family == "windows":
            target_dir = exec_bin
        else:
            target_dir = user_bin

    if sys_family == "windows":
        return _add_to_windows_user_path(target_dir)
    return _add_to_posix_user_path(target_dir)


def _add_to_windows_user_path(target_dir: Path) -> bool:
    target_str = str(target_dir.resolve())
    try:
        import winreg
        import ctypes

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
        try:
            existing_path, reg_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            existing_path, reg_type = "", winreg.REG_EXPAND_SZ

        existing_parts = [p.strip().lower() for p in existing_path.split(";") if p.strip()]
        if target_str.lower() in existing_parts:
            log_info(f"'{target_str}' is already in Windows User PATH.")
            winreg.CloseKey(key)
            return True

        # SAFELY APPEND -- NEVER OVERWRITE EXISTING PATH
        new_path = f"{existing_path.rstrip(';')};{target_str}" if existing_path else target_str
        winreg.SetValueEx(key, "Path", 0, reg_type, new_path)
        winreg.CloseKey(key)

        # Notify running Windows processes of environment change
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(result)
        )
        log_success(f"Safely appended '{target_str}' to Windows User PATH (HKCU\\Environment\\PATH).")
        log_dim("Please restart open terminal windows for the updated PATH to take effect.")
        return True
    except Exception as exc:
        log_error(f"Could not update Windows User PATH: {exc}")
        return False


def _add_to_posix_user_path(target_dir: Path) -> bool:
    target_str = str(target_dir.resolve())
    current_paths = os.environ.get("PATH", "").split(":")
    if target_str in current_paths or str(target_dir.expanduser()) in current_paths:
        log_info(f"'{target_str}' is already in PATH.")
        return True

    shell = os.environ.get("SHELL", "")
    rc_name = ".zshrc" if "zsh" in shell else ".bashrc"
    rc_file = Path.home() / rc_name
    export_line = f'\nexport PATH="{target_str}:$PATH"\n'

    try:
        content = rc_file.read_text(encoding="utf-8") if rc_file.exists() else ""
        if target_str not in content:
            with open(rc_file, "a", encoding="utf-8") as fh:
                fh.write(export_line)
            log_success(f"Appended '{target_str}' to {rc_file.name}.")
            log_dim(f"Run `source ~/{rc_name}` or restart your terminal.")
        return True
    except Exception as exc:
        log_error(f"Could not update {rc_file}: {exc}")
        return False
