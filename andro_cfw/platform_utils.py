"""
Platform helpers.

This module used to detect the OS, pick a package manager, and install Node.js
so that `wrangler` could run -- around 250 lines, including a `curl | sudo bash`
path. andro-cfw now talks to the Cloudflare REST API directly, so none of that
is needed and only the PATH helper remains.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional

from .colors import log_dim, log_error, log_info, log_success


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
        win_scripts = exec_bin / "Scripts"

        if (exec_bin / "andro-cfw").exists() or (exec_bin / "andro-cfw.exe").exists():
            target_dir = exec_bin
        elif (win_scripts / "andro-cfw.exe").exists():
            target_dir = win_scripts
        elif (user_bin / "andro-cfw").exists() or (user_bin / "andro-cfw.exe").exists():
            target_dir = user_bin
        elif sys_family == "windows":
            target_dir = win_scripts if win_scripts.exists() else exec_bin
        else:
            target_dir = user_bin

    if sys_family == "windows":
        return _add_to_windows_user_path(target_dir)
    return _add_to_posix_user_path(target_dir)


def _add_to_windows_user_path(target_dir: Path) -> bool:
    # Ensure a command wrapper exists in target_dir so andro-cfw runs from anywhere
    cmd_bin = target_dir / "andro-cfw.cmd"
    if not cmd_bin.exists() and not (target_dir / "andro-cfw.exe").exists():
        try:
            cmd_content = f'@echo off\r\n"{sys.executable}" -m andro_cfw.cli %*\r\n'
            cmd_bin.write_text(cmd_content, encoding="utf-8")
            log_success(f"Created CLI wrapper at '{cmd_bin}'.")
        except Exception:  # noqa: S110 - wrapper is a convenience; PATH edit still proceeds
            pass

    target_str = str(target_dir.resolve())
    try:
        # Imported dynamically: these modules exist only on Windows, so a
        # static import fails type checking on every other platform.
        import importlib
        from typing import Any

        ctypes: Any = importlib.import_module("ctypes")
        winreg: Any = importlib.import_module("winreg")

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
    # Ensure a command wrapper exists in target_dir so andro-cfw runs from anywhere
    target_dir.mkdir(parents=True, exist_ok=True)
    wrapper_bin = target_dir / "andro-cfw"
    is_pipx = "pipx" in str(sys.executable)
    if not wrapper_bin.exists() and not wrapper_bin.is_symlink() and not is_pipx:
        try:
            wrapper_content = f'#!/bin/sh\nexec "{sys.executable}" -m andro_cfw.cli "$@"\n'
            wrapper_bin.write_text(wrapper_content, encoding="utf-8")
            os.chmod(wrapper_bin, 0o755)  # noqa: S103 - a launcher on PATH must be executable
            log_success(f"Created CLI wrapper at '{wrapper_bin}'.")
        except Exception:  # noqa: S110 - wrapper is a convenience; PATH edit still proceeds
            pass

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
        log_error(f"Could not write to {rc_name}: {exc}")
        return False
