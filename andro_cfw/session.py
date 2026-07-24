from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .errors import SessionNotFoundError

DEFAULT_SESSION_FILENAME = "cfw.session"
KEY_DIR = Path.home() / ".andro_cfw"
KEY_FILE = KEY_DIR / "key"


def _ensure_key() -> bytes:
    """
    Get (or create) the local Fernet key used to encrypt cfw.session.

    The key lives outside the project directory (in the user's home folder)
    so that committing cfw.session to a repo by mistake does NOT leak the
    worker URL / metadata. The key file is created with 0600 permissions.
    """
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        try:
            os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return key
    return KEY_FILE.read_bytes()


@dataclass
class CFWSession:
    """
    Represents a deployed Cloudflare Worker proxy session for a project.

    Attributes:
        worker_name: Name of the deployed Cloudflare Worker.
        worker_url: Public https://*.workers.dev URL of the worker.
        account_id: Cloudflare account id the worker was deployed under (optional).
        created_at: Unix timestamp of creation.
    """

    worker_name: str
    worker_url: str
    account_id: Optional[str] = None
    created_at: float = 0.0

    # ---------------------------------------------------------------- #
    # Persistence
    # ---------------------------------------------------------------- #

    def save(self, path: Optional[str] = None) -> Path:
        """Encrypt and write this session to cfw.session."""
        target = Path(path) if path else Path.cwd() / DEFAULT_SESSION_FILENAME
        key = _ensure_key()
        fernet = Fernet(key)
        payload = json.dumps(asdict(self)).encode("utf-8")
        token = fernet.encrypt(payload)
        target.write_bytes(token)
        try:
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return target

    @classmethod
    def load(cls, path: Optional[str] = None) -> "CFWSession":
        """
        Load and decrypt cfw.session from the given path (or the current
        working directory by default).
        """
        target = Path(path) if path else Path.cwd() / DEFAULT_SESSION_FILENAME
        if not target.exists():
            raise SessionNotFoundError(
                f"No '{target.name}' found at {target.parent}. "
                "Run `andro-cfw init` in your project directory first."
            )
        key = _ensure_key()
        fernet = Fernet(key)
        try:
            raw = fernet.decrypt(target.read_bytes())
        except InvalidToken as exc:
            raise SessionNotFoundError(
                "cfw.session could not be decrypted with the local key. "
                "This usually means it was created on a different machine/user. "
                "Re-run `andro-cfw init` to regenerate it."
            ) from exc
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)

    @classmethod
    def new(cls, worker_name: str, worker_url: str, account_id: Optional[str] = None) -> "CFWSession":
        return cls(
            worker_name=worker_name,
            worker_url=worker_url,
            account_id=account_id,
            created_at=time.time(),
        )

    # ---------------------------------------------------------------- #
    # Convenience accessors for popular Telegram libraries
    # ---------------------------------------------------------------- #

    def api_base_url(self) -> str:
        """Base URL of the deployed worker, no trailing slash."""
        return self.worker_url.rstrip("/")

    def telebot_api_url(self) -> str:
        """Drop-in replacement for ``telebot.apihelper.API_URL``."""
        return self.api_base_url() + "/bot{0}/{1}"

    def telebot_file_url(self) -> str:
        """Drop-in replacement for ``telebot.apihelper.FILE_URL``."""
        return self.api_base_url() + "/file/bot{0}/{1}"

    def ptb_base_url(self) -> str:
        """For python-telegram-bot's ApplicationBuilder().base_url(...)."""
        return self.api_base_url() + "/bot"

    def ptb_base_file_url(self) -> str:
        """For python-telegram-bot's ApplicationBuilder().base_file_url(...)."""
        return self.api_base_url() + "/file/bot"

    def aiogram_server_url(self):
        """
        Returns a dict of kwargs suitable for aiogram 3.x's
        ``TelegramAPIServer(base=..., file=...)``.
        """
        return {
            "base": self.api_base_url() + "/bot{token}/{method}",
            "file": self.api_base_url() + "/file/bot{token}/{path}",
        }
