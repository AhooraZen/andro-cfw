"""
Usage accounting for the shared proxy daemon.

The load balancer used to be purely reactive: it only learned an account was
out of quota when Cloudflare answered 429, so every switch cost one failed
request. And because each bot process ran its own balancer, three bots meant
three independent copies of that discovery, none of them aware of the others'
consumption.

Since the daemon proxies every request itself, it can simply count them. This
module is that counter, plus enough history to draw the dashboard.

One caveat worth stating plainly: webhook traffic goes from Telegram straight
to the Worker and never passes through here, so these counts cover polling and
outbound API calls only. For a webhook-driven bot they will read low.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .session import KEY_DIR

DEFAULT_DB_PATH = KEY_DIR / "usage.db"

# Cloudflare Workers free plan: 100,000 requests per UTC day.
FREE_PLAN_DAILY_REQUESTS = 100_000

# Switch away from a worker once it has consumed this fraction of the daily
# allowance, so the bot never experiences the 429 that used to trigger failover.
DEFAULT_QUOTA_HEADROOM = 0.95

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    worker_name TEXT NOT NULL,
    utc_day     TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (worker_name, utc_day)
);

CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_name TEXT NOT NULL,
    at          REAL NOT NULL,
    latency_ms  REAL,
    status      INTEGER,
    ok          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS samples_at ON samples (at);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    worker_name TEXT,
    kind        TEXT NOT NULL,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events (at);
"""


def utc_day(at: Optional[float] = None) -> str:
    """The UTC date key Cloudflare's daily quota resets on."""
    moment = datetime.fromtimestamp(at if at is not None else time.time(), tz=timezone.utc)
    return moment.strftime("%Y-%m-%d")


class UsageStore:
    """
    SQLite-backed counters and history.

    A single connection guarded by a lock: the daemon is threaded, and SQLite
    connections are not safe to share across threads without one. WAL mode lets
    the dashboard read while requests are still being recorded.
    """

    def __init__(self, path: Optional[Path] = None, retention_days: int = 7):
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.retention_days = retention_days
        self._lock = threading.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- #
    # Recording
    # ---------------------------------------------------------------- #

    def record_request(
        self,
        worker_name: str,
        *,
        latency_ms: Optional[float] = None,
        status: Optional[int] = None,
        ok: bool = True,
        at: Optional[float] = None,
    ) -> None:
        """Count one proxied request and keep a latency sample for the graph."""
        moment = at if at is not None else time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO requests (worker_name, utc_day, count) VALUES (?, ?, 1) "
                "ON CONFLICT (worker_name, utc_day) DO UPDATE SET count = count + 1",
                (worker_name, utc_day(moment)),
            )
            self._conn.execute(
                "INSERT INTO samples (worker_name, at, latency_ms, status, ok) VALUES (?, ?, ?, ?, ?)",
                (worker_name, moment, latency_ms, status, 1 if ok else 0),
            )
            self._conn.commit()

    def record_event(self, kind: str, worker_name: Optional[str] = None,
                     detail: Optional[str] = None, at: Optional[float] = None) -> None:
        """Log a notable moment: a failover, a quota trip, a retry exhaustion."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (at, worker_name, kind, detail) VALUES (?, ?, ?, ?)",
                (at if at is not None else time.time(), worker_name, kind, detail),
            )
            self._conn.commit()

    # ---------------------------------------------------------------- #
    # Reading
    # ---------------------------------------------------------------- #

    def requests_today(self, worker_name: str, at: Optional[float] = None) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM requests WHERE worker_name = ? AND utc_day = ?",
                (worker_name, utc_day(at)),
            ).fetchone()
        return int(row["count"]) if row else 0

    def usage_summary(self, at: Optional[float] = None) -> dict:
        """Today's request count for every worker seen so far."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT worker_name, count FROM requests WHERE utc_day = ?",
                (utc_day(at),),
            ).fetchall()
        return {row["worker_name"]: int(row["count"]) for row in rows}

    def recent_latency(self, worker_name: str, window: int = 20) -> Optional[float]:
        """
        Median latency of the last `window` successful requests.

        The median rather than the mean: one 30-second timeout should not
        disqualify an otherwise healthy account from being chosen.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT latency_ms FROM samples "
                "WHERE worker_name = ? AND ok = 1 AND latency_ms IS NOT NULL "
                "ORDER BY at DESC LIMIT ?",
                (worker_name, window),
            ).fetchall()

        values = sorted(row["latency_ms"] for row in rows)
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2

    def latency_series(self, since: float, buckets: int = 60) -> dict:
        """
        Bucketed mean latency per worker, for the dashboard chart.

        The mean, unlike recent_latency's median, because a chart should show a
        spike rather than smooth it away -- routing decisions want the robust
        statistic, a human reading a graph wants the outlier to be visible.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT worker_name, at, latency_ms FROM samples "
                "WHERE at >= ? AND latency_ms IS NOT NULL AND ok = 1 ORDER BY at",
                (since,),
            ).fetchall()

        if not rows:
            return {}

        now = time.time()
        span = max(now - since, 1.0)
        width = span / buckets
        grouped: dict = {}
        for row in rows:
            index = min(int((row["at"] - since) / width), buckets - 1)
            grouped.setdefault(row["worker_name"], {}).setdefault(index, []).append(row["latency_ms"])

        series = {}
        for worker, points in grouped.items():
            series[worker] = [
                {"bucket": index, "latency_ms": round(sum(vals) / len(vals), 1)}
                for index, vals in sorted(points.items())
            ]
        return series

    def recent_events(self, limit: int = 50) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT at, worker_name, kind, detail FROM events ORDER BY at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- #
    # Housekeeping
    # ---------------------------------------------------------------- #

    def prune(self, at: Optional[float] = None) -> None:
        """
        Drop history past the retention window.

        Without this the samples table grows by one row per proxied request
        forever -- a long-polling bot writes roughly one per second.
        """
        cutoff = (at if at is not None else time.time()) - self.retention_days * 86400
        day_cutoff = utc_day(cutoff)
        with self._lock:
            self._conn.execute("DELETE FROM samples WHERE at < ?", (cutoff,))
            self._conn.execute("DELETE FROM events WHERE at < ?", (cutoff,))
            self._conn.execute("DELETE FROM requests WHERE utc_day < ?", (day_cutoff,))
            self._conn.commit()
