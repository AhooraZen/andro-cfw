from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, asdict, field
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
class WorkerEntry:
    """
    One deployed Cloudflare Worker under one Cloudflare account.

    exhausted_until: unix timestamp until which this worker is assumed to
    have hit Cloudflare's daily free-tier request quota (100k req/day).
    0 means "not currently marked as exhausted". The load balancer sets
    this to the next UTC midnight the moment it detects a 429 / quota-limit
    response from this worker, and automatically considers the worker
    usable again once that timestamp has passed (i.e. after Cloudflare's
    daily reset) -- no manual action required.
    """

    worker_name: str
    worker_url: str
    account_label: Optional[str] = None
    account_id: Optional[str] = None
    exhausted_until: float = 0.0
    last_error: Optional[str] = None


@dataclass
class CFWSession:
    """
    Represents one or more deployed Cloudflare Worker proxy sessions for a
    project, with optional smart multi-account load balancing.

    Single-account projects (the default) behave exactly as before: the
    Telegram library talks directly to the one workers.dev URL.

    Multi-account projects (created with `andro-cfw init --accounts N`)
    hold N independent Cloudflare-account workers. In that case, the
    URLs returned by telebot_api_url()/ptb_base_url()/etc. point at a
    local load-balancing proxy (started automatically, in-process, the
    first time it's needed) which:
      - forwards every request to the currently "active" worker,
      - instantly detects a 429 / daily-quota-exceeded response,
      - switches to the next healthy worker/account with zero downtime,
      - automatically starts using an account again once its daily
        Cloudflare quota resets (00:00 UTC), cycling back to account #1
        first once it becomes available again.
    """

    workers: list = field(default_factory=list)  # list[WorkerEntry]
    active_index: int = 0
    created_at: float = 0.0

    # Backward-compatible single-worker fields. Kept so existing sessions
    # created with andro-cfw <0.2.0 keep loading correctly, and so simple
    # single-account code (`session.worker_name` / `session.worker_url`)
    # keeps working unchanged.
    worker_name: Optional[str] = None
    worker_url: Optional[str] = None
    account_id: Optional[str] = None

    _lb = None  # lazily-created LoadBalancer instance (not persisted)

    def __post_init__(self):
        # Normalize dicts (from JSON) into WorkerEntry objects.
        normalized = []
        for w in self.workers:
            if isinstance(w, WorkerEntry):
                normalized.append(w)
            elif isinstance(w, dict):
                normalized.append(WorkerEntry(**w))
        self.workers = normalized

        # Migrate an old-style single-worker session into the new
        # `workers` list so both code paths (old attrs + new list) agree.
        if not self.workers and self.worker_name and self.worker_url:
            self.workers = [
                WorkerEntry(
                    worker_name=self.worker_name,
                    worker_url=self.worker_url,
                    account_id=self.account_id,
                )
            ]

        if self.workers:
            active = self.workers[self.active_index % len(self.workers)]
            self.worker_name = active.worker_name
            self.worker_url = active.worker_url

    # ---------------------------------------------------------------- #
    # Persistence
    # ---------------------------------------------------------------- #

    def save(self, path: Optional[str] = None) -> Path:
        """Encrypt and write this session to cfw.session."""
        target = Path(path) if path else Path.cwd() / DEFAULT_SESSION_FILENAME
        key = _ensure_key()
        fernet = Fernet(key)
        data = {
            "workers": [asdict(w) for w in self.workers],
            "active_index": self.active_index,
            "created_at": self.created_at,
            "worker_name": self.worker_name,
            "worker_url": self.worker_url,
            "account_id": self.account_id,
        }
        payload = json.dumps(data).encode("utf-8")
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
        session = cls(**data)
        session._session_path = target
        return session

    @classmethod
    def new(cls, worker_name: str, worker_url: str, account_id: Optional[str] = None) -> "CFWSession":
        return cls(
            workers=[WorkerEntry(worker_name=worker_name, worker_url=worker_url, account_id=account_id)],
            active_index=0,
            created_at=time.time(),
        )

    @classmethod
    def new_multi(cls, entries: list) -> "CFWSession":
        """Create a session backed by several (worker_name, worker_url, account_label) tuples."""
        workers = [
            WorkerEntry(worker_name=n, worker_url=u, account_label=lbl)
            for (n, u, lbl) in entries
        ]
        return cls(workers=workers, active_index=0, created_at=time.time())

    # ---------------------------------------------------------------- #
    # Load-balancer plumbing (multi-account mode)
    # ---------------------------------------------------------------- #

    def _persist(self) -> None:
        """Re-save the session, used by the load balancer to persist
        exhausted_until timestamps / active_index switches across restarts."""
        path = getattr(self, "_session_path", None)
        try:
            self.save(str(path) if path else None)
        except Exception:
            pass

    def _get_load_balancer(self):
        if len(self.workers) <= 1:
            return None
        if self._lb is None:
            from .loadbalancer import LoadBalancer
            self._lb = LoadBalancer(self)
            self._lb.start()
        return self._lb

    # ---------------------------------------------------------------- #
    # Convenience accessors for popular Telegram libraries
    # ---------------------------------------------------------------- #

    def api_base_url(self) -> str:
        """
        Base URL to point Telegram libraries at, no trailing slash.

        - Single-account sessions: the workers.dev URL directly.
        - Multi-account sessions: the local smart load-balancer URL,
          started automatically in this process.
        """
        lb = self._get_load_balancer()
        if lb is not None:
            return lb.base_url()
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

    def check_health(self, timeout: int = 5) -> list[dict]:
        """
        Pings each deployed Cloudflare Worker in this session to measure ping latency,
        HTTP status, and check daily quota reset status.
        """
        import urllib.request
        import urllib.error

        results = []
        for i, w in enumerate(self.workers):
            start = time.time()
            url = w.worker_url.rstrip("/") + "/"
            status = 0
            latency = 0.0
            error = None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "andro-cfw-health-check"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    status = resp.status
                    latency = (time.time() - start) * 1000
            except urllib.error.HTTPError as http_err:
                status = http_err.code
                latency = (time.time() - start) * 1000
            except Exception as exc:
                error = str(exc)

            results.append({
                "index": i,
                "worker_name": w.worker_name,
                "worker_url": w.worker_url,
                "account_label": w.account_label,
                "status": status,
                "latency_ms": round(latency, 1),
                "is_exhausted": w.exhausted_until > time.time(),
                "exhausted_until": w.exhausted_until,
                "error": error,
            })
        return results
