from __future__ import annotations

import argparse
import os
import sys

_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

if _USE_COLOR:
    PREFIX = "\033[1;36m[andro-cfw]\033[0m"
    COLOR_BLUE = "\033[1;34m"
    COLOR_RED = "\033[1;31m"
    COLOR_YELLOW = "\033[1;33m"
    COLOR_GREEN = "\033[1;32m"
    COLOR_CYAN = "\033[1;36m"
    COLOR_MAGENTA = "\033[1;35m"
    COLOR_DIM = "\033[2m"
    COLOR_BOLD = "\033[1m"
    COLOR_RESET = "\033[0m"
else:
    PREFIX = "[andro-cfw]"
    COLOR_BLUE = ""
    COLOR_RED = ""
    COLOR_YELLOW = ""
    COLOR_GREEN = ""
    COLOR_CYAN = ""
    COLOR_MAGENTA = ""
    COLOR_DIM = ""
    COLOR_BOLD = ""
    COLOR_RESET = ""


class ColoredHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom argparse help formatter that adds ANSI colors to CLI --help output."""

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return f"{COLOR_CYAN}{action.dest}{COLOR_RESET}"
        return f"{COLOR_BLUE}{', '.join(action.option_strings)}{COLOR_RESET}"

    def format_help(self) -> str:
        help_text = super().format_help()
        if not _USE_COLOR:
            return help_text

        lines = []
        for line in help_text.splitlines():
            if line.startswith("usage:"):
                line = line.replace("usage:", f"{COLOR_BOLD}{COLOR_BLUE}Usage:{COLOR_RESET}")
            elif line.endswith(":") and not line.startswith(" "):
                line = f"{COLOR_BOLD}{COLOR_YELLOW}{line}{COLOR_RESET}"
            lines.append(line)
        return "\n".join(lines) + "\n"


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


def log_notice(msg: str) -> None:
    """Print a notice message in bold blue."""
    print(f"{PREFIX} {COLOR_BLUE}{msg}{COLOR_RESET}")


def log_dim(msg: str) -> None:
    """Print a dimmed message."""
    print(f"{PREFIX} {COLOR_DIM}{msg}{COLOR_RESET}")
