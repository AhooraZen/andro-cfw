from __future__ import annotations

import os
import sys

_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

if _USE_COLOR:
    PREFIX = "\033[1;36m[andro-cfw]\033[0m"
    COLOR_YELLOW = "\033[1;33m"
    COLOR_GREEN = "\033[1;32m"
    COLOR_CYAN = "\033[1;36m"
    COLOR_RED = "\033[1;31m"
    COLOR_DIM = "\033[2m"
    COLOR_BOLD = "\033[1m"
    COLOR_RESET = "\033[0m"
else:
    PREFIX = "[andro-cfw]"
    COLOR_YELLOW = ""
    COLOR_GREEN = ""
    COLOR_CYAN = ""
    COLOR_RED = ""
    COLOR_DIM = ""
    COLOR_BOLD = ""
    COLOR_RESET = ""


def log_info(msg: str) -> None:
    """Print an informational status message with cyan prefix."""
    print(f"{PREFIX} {msg}")


def log_step(msg: str) -> None:
    """Print a step message in bold cyan."""
    print(f"{PREFIX} {COLOR_CYAN}{msg}{COLOR_RESET}")


def log_working(msg: str) -> None:
    """Print a pending/working message in bold yellow."""
    print(f"{PREFIX} {COLOR_YELLOW}{msg}{COLOR_RESET}")


def log_success(msg: str) -> None:
    """Print a success message in bold green."""
    print(f"{PREFIX} {COLOR_GREEN}{msg}{COLOR_RESET}")


def log_warn(msg: str) -> None:
    """Print a warning message in bold yellow."""
    print(f"{PREFIX} {COLOR_YELLOW}{msg}{COLOR_RESET}")


def log_error(msg: str) -> None:
    """Print an error message in bold red."""
    print(f"{PREFIX} {COLOR_RED}{msg}{COLOR_RESET}")


def log_dim(msg: str) -> None:
    """Print a dimmed message."""
    print(f"{PREFIX} {COLOR_DIM}{msg}{COLOR_RESET}")
