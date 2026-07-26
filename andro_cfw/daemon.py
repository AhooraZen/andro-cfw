"""
The shared proxy daemon.

Before this existed, every bot process started its own in-process load
balancer. Three bots on one machine meant three balancers that each discovered
a 429 independently, all wrote to the same session file, and none of which knew
what the others had already spent. Failover was also purely reactive: an
account was only known to be out of quota once Cloudflare refused a request, so
every switch cost the bot one failure.

One daemon shared by every bot fixes both. Because it proxies each request
itself it can simply count them, which turns quota handling from "react to a
429" into "move before we get one".

Honest caveat: webhook updates travel from Telegram straight to the Worker and
never pass through here, so these counts cover long polling and outbound API
calls only. For a webhook-driven bot they read low.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from importlib import resources
from pathlib import Path
from typing import Optional

from .colors import log_dim, log_info, log_success
from .loadbalancer import LoadBalancer
from .session import _OWNER_ONLY_FILE, KEY_DIR, _restrict
from .store import DEFAULT_QUOTA_HEADROOM, FREE_PLAN_DAILY_REQUESTS, UsageStore

# Where a running daemon advertises itself so bots and the CLI can find it.
DAEMON_FILE = KEY_DIR / "daemon.json"

DEFAULT_DAEMON_PORT = 8787

# Reserved path prefix for the dashboard and its API. Bot API traffic always
# begins with /bot or /file/bot, so this cannot collide with a proxied call.
CONTROL_PREFIX = "/__andro"

# Window the dashboard's latency chart covers.
SERIES_WINDOW_SECONDS = 3600
SERIES_BUCKETS = 60


def _dashboard_html() -> str:
    return resources.files("andro_cfw.templates").joinpath("dashboard.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

def read_daemon_file() -> Optional[dict]:
    if not DAEMON_FILE.exists():
        return None
    try:
        data = json.loads(DAEMON_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_running_daemon(timeout: float = 1.0) -> Optional[str]:
    """
    Return the base URL of a live daemon, or None.

    The advertised file is not trusted on its own: a daemon killed with SIGKILL
    leaves it behind, and the port may since have been taken by something else.
    A successful ping on the control endpoint is what makes it live.
    """
    data = read_daemon_file()
    if not data:
        return None

    host = data.get("host", "127.0.0.1")
    port = data.get("port")
    if not port:
        return None

    base_url = f"http://{host}:{port}"
    try:
        request = urllib.request.Request(  # noqa: S310 - localhost http URL built above
            f"{base_url}{CONTROL_PREFIX}/api/ping", headers={"User-Agent": "andro-cfw"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - localhost URL built above
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None

    return base_url if payload.get("service") == "andro-cfw" else None


def clear_daemon_file() -> None:
    try:
        DAEMON_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# The daemon
# --------------------------------------------------------------------------- #

class Daemon(LoadBalancer):
    """
    A long-lived local proxy that every bot on the machine shares.

    Extends LoadBalancer with quota accounting, latency-aware worker choice,
    and the control endpoints that back the dashboard.
    """

    def __init__(
        self,
        session,
        store: Optional[UsageStore] = None,
        host: str = "127.0.0.1",
        port: int = DEFAULT_DAEMON_PORT,
        headroom: float = DEFAULT_QUOTA_HEADROOM,
        daily_limit: int = FREE_PLAN_DAILY_REQUESTS,
    ):
        super().__init__(session, host=host)
        self.store = store if store is not None else UsageStore()
        self.requested_port = port
        self.headroom = headroom
        self.daily_limit = daily_limit
        self.started_at = time.time()

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    def start(self, preferred_port: Optional[int] = None) -> None:
        if self._server is not None:
            return
        super().start(preferred_port=self.requested_port if preferred_port is None else preferred_port)
        self.started_at = time.time()
        self._write_daemon_file()
        self.store.record_event("daemon_start", detail=f"port {self.port}")
        self.store.prune()

    def _announce(self) -> None:
        """Silent: serve_forever prints a fuller banner, and an in-process
        daemon started for a single bot should not chatter on import."""

    def stop(self) -> None:
        super().stop()
        clear_daemon_file()

    def _write_daemon_file(self) -> None:
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        DAEMON_FILE.write_text(
            json.dumps({
                "host": self.host,
                "port": self.port,
                "pid": os.getpid(),
                "started_at": self.started_at,
            }),
            encoding="utf-8",
        )
        _restrict(DAEMON_FILE, _OWNER_ONLY_FILE)

    # ---------------------------------------------------------------- #
    # Quota-aware, latency-aware worker choice
    # ---------------------------------------------------------------- #

    def quota_ceiling(self) -> int:
        """Requests per worker per day before we move on, leaving headroom."""
        return int(self.daily_limit * self.headroom)

    def _pick_active_worker(self) -> int:
        """
        Prefer the fastest worker that is neither exhausted nor near its quota.

        Choosing by measured latency rather than by list order means the bot
        gets the best account available, and the quota check means it leaves
        that account *before* Cloudflare starts refusing requests.
        """
        now = time.time()
        ceiling = self.quota_ceiling()
        candidates = []

        for index, worker in enumerate(self.session.workers):
            if worker.exhausted_until > now:
                continue
            if self.store.requests_today(worker.worker_name) >= ceiling:
                continue
            latency = self.store.recent_latency(worker.worker_name)
            # An unmeasured worker sorts first so it earns a sample and can
            # compete honestly on the next request.
            candidates.append((latency if latency is not None else -1.0, index))

        if candidates:
            candidates.sort()
            return candidates[0][1]

        # Everything is exhausted or over its ceiling. Fall back to the base
        # policy, which picks whichever resets soonest.
        return super()._pick_active_worker()

    # ---------------------------------------------------------------- #
    # Accounting hooks
    # ---------------------------------------------------------------- #

    def _record_result(self, worker, latency_ms, status, ok: bool) -> None:
        self.store.record_request(
            worker.worker_name, latency_ms=latency_ms, status=status, ok=ok
        )

    def _note_retry(self, worker, status: int, retry: int) -> None:
        self.store.record_event(
            "retry", worker.worker_name, f"HTTP {status}, attempt {retry + 1}"
        )

    def _mark_exhausted(self, index: int, reason: str) -> None:
        worker = self.session.workers[index]
        self.store.record_event("failover", worker.worker_name, reason)
        super()._mark_exhausted(index, reason)

    # ---------------------------------------------------------------- #
    # Control endpoints
    # ---------------------------------------------------------------- #

    def _proxy_request(self, handler) -> None:
        if handler.path == CONTROL_PREFIX or handler.path.startswith(CONTROL_PREFIX + "/"):
            self._handle_control(handler)
            return
        super()._proxy_request(handler)

    def _handle_control(self, handler) -> None:
        route = handler.path[len(CONTROL_PREFIX):].split("?")[0].rstrip("/") or "/"

        if route in ("/", ""):
            body = _dashboard_html().encode("utf-8")
            self._send_response(handler, 200, {"Content-Type": "text/html; charset=utf-8"}, body)
            return

        if route == "/api/ping":
            self._send_json(handler, 200, {"service": "andro-cfw", "port": self.port})
            return

        if route == "/api/state":
            self._send_json(handler, 200, self.api_state())
            return

        self._send_json(handler, 404, {"error": "unknown control endpoint"})

    def _send_json(self, handler, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_response(
            handler, status,
            {"Content-Type": "application/json", "Cache-Control": "no-store"},
            body,
        )

    def api_state(self) -> dict:
        """The snapshot the dashboard renders."""
        now = time.time()
        ceiling = self.quota_ceiling()
        usage = self.store.usage_summary()

        workers = []
        available = 0
        for index, worker in enumerate(self.session.workers):
            used = usage.get(worker.worker_name, 0)
            if worker.exhausted_until > now:
                state = "quota" if used >= ceiling else "cooldown"
            elif used >= ceiling:
                state = "quota"
            else:
                state = "available"
                available += 1

            workers.append({
                "index": index,
                "worker_name": worker.worker_name,
                "worker_url": worker.worker_url,
                "account_label": worker.account_label,
                "active": index == self.session.active_index,
                "state": state,
                "requests_today": used,
                "quota_fraction": round(used / self.daily_limit, 6) if self.daily_limit else 0.0,
                "latency_ms": self.store.recent_latency(worker.worker_name),
                "exhausted_until": worker.exhausted_until,
                "last_error": worker.last_error,
            })

        from . import __version__

        return {
            "daemon": {
                "port": self.port,
                "uptime_seconds": round(now - self.started_at, 1),
                "version": __version__,
                "started_at": self.started_at,
            },
            "quota": {
                "daily_limit": self.daily_limit,
                "headroom": self.headroom,
                "utc_day": time.strftime("%Y-%m-%d", time.gmtime(now)),
            },
            "workers": workers,
            "latency_series": self.store.latency_series(
                now - SERIES_WINDOW_SECONDS, buckets=SERIES_BUCKETS
            ),
            "series_meta": {"buckets": SERIES_BUCKETS, "window_seconds": SERIES_WINDOW_SECONDS},
            "events": self.store.recent_events(limit=50),
            "totals": {
                "requests_today": sum(usage.values()),
                "workers": len(self.session.workers),
                "available": available,
            },
        }

    # ---------------------------------------------------------------- #
    # Foreground run
    # ---------------------------------------------------------------- #

    def serve_forever(self) -> None:
        """Block until interrupted. Used by `andro-cfw daemon`."""
        self.start()
        log_success(f"Daemon listening on http://{self.host}:{self.port}")
        log_info(f"Dashboard: http://{self.host}:{self.port}{CONTROL_PREFIX}/")
        log_dim("Point your bots at this address, or just call andro_cfw.patch().")
        log_dim("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
                self.store.prune()
        except KeyboardInterrupt:
            log_info("Shutting down.")
        finally:
            self.stop()
            self.store.close()


def daemon_base_url(session, autostart: bool = True) -> Optional[str]:
    """
    Find a running daemon, or start an in-process one.

    Called from CFWSession.api_base_url(). A daemon started here lives inside
    the bot's own process -- it still counts quota and load balances, it just
    is not shared with other processes the way `andro-cfw daemon` is.
    """
    running = find_running_daemon()
    if running:
        return running
    if not autostart:
        return None

    daemon = Daemon(session, port=0)
    daemon.start()
    return daemon.base_url()


def daemon_status(path: Optional[Path] = None) -> dict:
    """Describe the running daemon for `andro-cfw status`."""
    base_url = find_running_daemon()
    data = read_daemon_file() or {}
    return {
        "running": base_url is not None,
        "base_url": base_url,
        "pid": data.get("pid"),
        "port": data.get("port"),
        "started_at": data.get("started_at"),
    }
