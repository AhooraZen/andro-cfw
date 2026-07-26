from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .session import require_http_url

# Cloudflare Workers Free plan: 100,000 requests/day, resetting at UTC
# midnight. We treat a 429 response (or a Cloudflare rate-limit page) from
# a worker as "this account's daily quota is exhausted" and mark it
# unusable until the next UTC midnight, at which point it automatically
# becomes eligible again -- no manual reset needed.
QUOTA_STATUS_CODES = {429}

# Telegram caps uploads at 50 MB. Anything larger is not a legitimate Bot API
# call, and Content-Length is attacker-controlled, so refuse rather than
# allocate a buffer of whatever size the header claims.
MAX_REQUEST_BODY_BYTES = 64 * 1024 * 1024

# Hop-by-hop headers are connection-scoped and must not be relayed.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
CLOUDFLARE_LIMIT_MARKERS = (
    "you have exceeded",
    "rate limit",
    "1015",  # Cloudflare's own "rate limited" error code
    "resource_limited",
)


def _next_utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.timestamp()


def _looks_like_quota_error(status: int, body_snippet: str) -> bool:
    if status in QUOTA_STATUS_CODES:
        return True
    if status >= 500:
        return False
    lowered = body_snippet.lower()
    return any(marker in lowered for marker in CLOUDFLARE_LIMIT_MARKERS)


class LoadBalancer:
    """
    A tiny local HTTP proxy (127.0.0.1) that sits between the Telegram
    library running in this process and the pool of deployed Cloudflare
    Worker proxies (one per Cloudflare account).

    Smart switching logic:
      1. Every request goes to the currently active worker.
      2. If that worker replies with a quota-exceeded signal (HTTP 429 or
         a Cloudflare rate-limit page), the worker is immediately marked
         "exhausted until next UTC midnight" and the balancer instantly
         retries the SAME request against the next healthy worker in the
         rotation, so the bot never sees the failure.
      3. Once a worker's exhausted_until timestamp is in the past again
         (i.e. Cloudflare's daily reset has happened), it automatically
         becomes eligible again -- the balancer always prefers the lowest
         account index that is currently usable, so it "returns to
         account #1" first once it resets, exactly as requested.
      4. All of this happens in-memory + is persisted back into the
         encrypted cfw.session file, so exhausted/reset state survives
         bot restarts too.
    """

    def __init__(self, session, host: str = "127.0.0.1"):
        self.session = session
        self.host = host
        self.port: Optional[int] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------ #

    def start(self) -> None:
        if self._server is not None:
            return
        balancer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # silence default noisy logging
                pass

            def _handle(self):
                balancer._proxy_request(self)

            do_GET = _handle
            do_POST = _handle
            do_PUT = _handle
            do_DELETE = _handle
            do_HEAD = _handle
            do_PATCH = _handle

        # Bind to an OS-assigned free port on localhost only.
        self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(
            f"[andro-cfw] Smart load balancer active on http://{self.host}:{self.port} "
            f"across {len(self.session.workers)} Cloudflare account(s)."
        )

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            # shutdown() only stops serve_forever; without server_close() the
            # listening socket stays open for the life of the process.
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.port = None

    def base_url(self) -> str:
        self.start()
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------ #
    # Worker selection
    # ------------------------------------------------------------ #

    def _pick_active_worker(self):
        """
        Return the index of the best worker to use right now: the
        lowest-indexed one that is not currently marked exhausted. If all
        are exhausted, fall back to the one whose quota resets soonest
        (best effort -- Cloudflare will simply keep 429-ing until then).
        """
        now = time.time()
        workers = self.session.workers
        for i, w in enumerate(workers):
            if w.exhausted_until <= now:
                return i
        # All exhausted: pick the soonest to reset.
        return min(range(len(workers)), key=lambda i: workers[i].exhausted_until)

    def _mark_exhausted(self, index: int, reason: str) -> None:
        with self._lock:
            w = self.session.workers[index]
            w.exhausted_until = _next_utc_midnight()
            w.last_error = reason
            self.session.active_index = self._pick_active_worker()

        # Persist outside the lock: encrypting and fsync-ing the session file
        # takes milliseconds, and every in-flight proxied request needs this
        # same lock to pick a worker. The write itself is atomic (see
        # CFWSession.save), so concurrent persists cannot corrupt the file.
        self.session._persist()

        reset_at = datetime.fromtimestamp(w.exhausted_until, tz=timezone.utc).strftime("%H:%M UTC")
        print(
            f"[andro-cfw] Account '{w.account_label or w.worker_name}' hit its daily "
            f"Cloudflare quota ({reason}). Switching to the next account. "
            f"This account will automatically be usable again after {reset_at}."
        )

    # ------------------------------------------------------------ #
    # Request proxying
    # ------------------------------------------------------------ #

    def _proxy_request(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            content_length = int(handler.headers.get("Content-Length", 0) or 0)
        except (ValueError, TypeError):
            content_length = 0

        if content_length < 0 or content_length > MAX_REQUEST_BODY_BYTES:
            # Never allocate a buffer sized by an unvalidated header.
            self._send_response(
                handler, 413, {"Content-Type": "application/json"},
                b'{"ok":false,"error_code":413,"description":"Request body too large for andro-cfw proxy"}',
            )
            return

        body = handler.rfile.read(content_length) if content_length else None

        tried_indices = set()
        attempts = 0
        max_attempts = max(1, len(self.session.workers))

        while attempts < max_attempts:
            attempts += 1
            with self._lock:
                index = self._pick_active_worker()
                self.session.active_index = index
                worker = self.session.workers[index]
            tried_indices.add(index)

            target_url = worker.worker_url.rstrip("/") + handler.path

            try:
                status, resp_headers, resp_body = self._forward(
                    target_url, handler.command, dict(handler.headers), body
                )
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                # Network-level failure talking to this worker/account --
                # treat it the same as an exhaustion signal so we fail over
                # instead of surfacing an error to the bot.
                self._mark_exhausted(index, f"connection error: {exc}")
                if len(tried_indices) >= max_attempts:
                    break
                continue

            snippet = resp_body[:500].decode("utf-8", "ignore") if resp_body else ""
            if _looks_like_quota_error(status, snippet):
                self._mark_exhausted(index, f"HTTP {status}")
                if len(tried_indices) >= max_attempts:
                    # Every account is currently exhausted -- return the
                    # last (quota-limited) response as-is, best effort.
                    self._send_response(handler, status, resp_headers, resp_body)
                    return
                continue

            self._send_response(handler, status, resp_headers, resp_body)
            return

        # Every account failed, or the pool is empty. Send a framed response:
        # under HTTP/1.1 a reply with no Content-Length leaves the client
        # waiting for a body that never arrives.
        self._send_response(
            handler, 503, {"Content-Type": "application/json"},
            b'{"ok":false,"error_code":503,"description":"No healthy Cloudflare Worker available via andro-cfw"}',
        )

    @staticmethod
    def _forward(url: str, method: str, headers: dict, body: Optional[bytes]):
        # `accept-encoding` is dropped so the upstream replies uncompressed:
        # urllib does not decode gzip, and a compressed body would make the
        # quota-marker sniffing in _proxy_request read binary noise.
        skip = HOP_BY_HOP_HEADERS | {"host", "content-length", "accept-encoding"}
        filtered_headers = {k: v for k, v in headers.items() if k.lower() not in skip}
        req = urllib.request.Request(  # noqa: S310 - scheme pinned by require_http_url
            require_http_url(url), data=body, method=method, headers=filtered_headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - scheme pinned above
                return resp.status, dict(resp.getheaders()), resp.read()
        except urllib.error.HTTPError as http_err:
            return http_err.code, dict(http_err.headers or {}), http_err.read()

    @staticmethod
    def _send_response(handler: BaseHTTPRequestHandler, status: int, headers: dict, body: Optional[bytes]) -> None:
        handler.send_response(status)
        for k, v in headers.items():
            if k.lower() in HOP_BY_HOP_HEADERS or k.lower() == "content-length":
                continue
            handler.send_header(k, v)
        body = body or b""
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
