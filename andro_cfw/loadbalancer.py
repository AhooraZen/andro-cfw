from __future__ import annotations

import tempfile
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

# Request bodies stay in memory up to this size and spill to a temp file above
# it, so a few concurrent file uploads cannot pin tens of megabytes of RAM.
SPOOL_THRESHOLD_BYTES = 1024 * 1024

# Copy size for relaying bodies in both directions.
STREAM_CHUNK_BYTES = 64 * 1024

# How much of a response body is buffered to recognise a Cloudflare quota page.
# Everything past this is streamed straight through to the client.
QUOTA_SNIFF_BYTES = 512

# Gateway errors are usually a blip at the edge rather than a real Bot API
# answer, so they are retried against the same worker before failing over.
# A plain 500 is left alone: that is Telegram's own error and the bot should
# see it.
RETRYABLE_STATUS = {502, 503, 504}
MAX_RETRIES_PER_WORKER = 2
RETRY_BACKOFF_SECONDS = 0.25

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

    def start(self, preferred_port: int = 0) -> None:
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

        # Localhost only. A preferred port is a request, not a requirement:
        # if it is taken, fall back to an OS-assigned one rather than refusing
        # to start and leaving the bot with no proxy at all.
        try:
            self._server = ThreadingHTTPServer((self.host, preferred_port), Handler)
        except OSError:
            if not preferred_port:
                raise
            self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._announce()

    def _announce(self) -> None:
        """Say where we are listening. The daemon prints its own banner instead."""
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

        # Spool the request body instead of holding it in memory. Failover has
        # to replay the same body against the next worker, so it cannot simply
        # stream off the socket -- but it can live on disk once it is large.
        body = None
        if content_length:
            body = tempfile.SpooledTemporaryFile(max_size=SPOOL_THRESHOLD_BYTES)
            remaining = content_length
            while remaining > 0:
                chunk = handler.rfile.read(min(STREAM_CHUNK_BYTES, remaining))
                if not chunk:
                    break
                body.write(chunk)
                remaining -= len(chunk)

        try:
            self._proxy_with_failover(handler, body, content_length)
        finally:
            if body is not None:
                body.close()

    def _proxy_with_failover(self, handler, body, content_length: int) -> None:
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

            outcome = self._attempt_worker(handler, worker, index, target_url, body, content_length)
            if outcome == "sent":
                return
            if outcome == "failed_over" and len(tried_indices) >= max_attempts:
                break

        # Every account failed, or the pool is empty. Send a framed response:
        # under HTTP/1.1 a reply with no Content-Length leaves the client
        # waiting for a body that never arrives.
        self._send_response(
            handler, 503, {"Content-Type": "application/json"},
            b'{"ok":false,"error_code":503,"description":"No healthy Cloudflare Worker available via andro-cfw"}',
        )

    def _attempt_worker(self, handler, worker, index: int, target_url: str,
                        body, content_length: int) -> str:
        """
        Try one worker, retrying transient gateway errors against it.

        Returns "sent" if the client got a response, or "failed_over" if the
        worker was marked unusable and the caller should try the next one.
        """
        for retry in range(MAX_RETRIES_PER_WORKER + 1):
            if body is not None:
                body.seek(0)

            started = time.monotonic()
            try:
                status, resp_headers, upstream = self._open_upstream(
                    target_url, handler.command, dict(handler.headers), body, content_length
                )
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                # Network-level failure talking to this worker/account --
                # treat it the same as an exhaustion signal so we fail over
                # instead of surfacing an error to the bot.
                self._record_result(worker, None, None, ok=False)
                self._mark_exhausted(index, f"connection error: {exc}")
                return "failed_over"

            latency_ms = (time.monotonic() - started) * 1000
            try:
                # Only the head of the body is buffered: enough to recognise a
                # Cloudflare quota page, never the whole payload.
                head = upstream.read(QUOTA_SNIFF_BYTES)

                if _looks_like_quota_error(status, head.decode("utf-8", "ignore")):
                    self._record_result(worker, latency_ms, status, ok=False)
                    self._mark_exhausted(index, f"HTTP {status}")
                    if self._all_workers_tried():
                        # Every account is exhausted -- relay the last
                        # quota-limited response as-is, best effort.
                        self._stream_response(handler, status, resp_headers, head, upstream)
                        return "sent"
                    return "failed_over"

                if status in RETRYABLE_STATUS and retry < MAX_RETRIES_PER_WORKER:
                    # A gateway blip at the edge, not an answer from Telegram.
                    self._record_result(worker, latency_ms, status, ok=False)
                    self._note_retry(worker, status, retry)
                    time.sleep(RETRY_BACKOFF_SECONDS * (2 ** retry))
                    continue

                self._record_result(worker, latency_ms, status, ok=status < 500)
                self._stream_response(handler, status, resp_headers, head, upstream)
                return "sent"
            finally:
                upstream.close()

        return "failed_over"

    def _all_workers_tried(self) -> bool:
        """Whether every worker in the pool is currently marked exhausted."""
        now = time.time()
        return all(w.exhausted_until > now for w in self.session.workers)

    # ------------------------------------------------------------ #
    # Hooks -- no-ops here, implemented by the daemon
    # ------------------------------------------------------------ #

    def _record_result(self, worker, latency_ms, status, ok: bool) -> None:
        """Called once per upstream attempt. The daemon uses this to count quota."""

    def _note_retry(self, worker, status: int, retry: int) -> None:
        """Called before backing off on a retryable gateway error."""

    @staticmethod
    def _open_upstream(url: str, method: str, headers: dict, body, content_length: int):
        """
        Start the upstream request and return (status, headers, response).

        The response is returned unread so the caller can stream it. The caller
        owns it and must close it.
        """
        # `accept-encoding` is dropped so the upstream replies uncompressed:
        # urllib does not decode gzip, and a compressed body would make the
        # quota-marker sniffing in _proxy_with_failover read binary noise.
        skip = HOP_BY_HOP_HEADERS | {"host", "content-length", "accept-encoding"}
        filtered_headers = {k: v for k, v in headers.items() if k.lower() not in skip}
        if body is not None:
            # http.client streams a file object only when it knows the length;
            # without this it would fall back to chunked encoding.
            filtered_headers["Content-Length"] = str(content_length)

        req = urllib.request.Request(  # noqa: S310 - scheme pinned by require_http_url
            require_http_url(url), data=body, method=method, headers=filtered_headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)  # noqa: S310 - scheme pinned above
            return resp.status, dict(resp.getheaders()), resp
        except urllib.error.HTTPError as http_err:
            # HTTPError is itself a readable response object.
            return http_err.code, dict(http_err.headers or {}), http_err

    @staticmethod
    def _stream_response(handler, status: int, headers: dict, head: bytes, upstream) -> None:
        """
        Relay an upstream response to the client without buffering it whole.

        `head` is the already-consumed prefix used for quota sniffing; it is
        written first, then the remainder is copied in chunks.
        """
        upstream_length = None
        for key, value in headers.items():
            if key.lower() == "content-length":
                try:
                    upstream_length = int(value)
                except (TypeError, ValueError):
                    upstream_length = None
                break

        handler.send_response(status)
        for key, value in headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-length":
                continue
            handler.send_header(key, value)

        if upstream_length is not None:
            handler.send_header("Content-Length", str(upstream_length))
        else:
            # Length unknown (upstream was chunked, which urllib already
            # decoded). Under HTTP/1.1 the only other way to delimit the body
            # is to close the connection when it ends.
            handler.send_header("Connection", "close")
            handler.close_connection = True
        handler.end_headers()

        if handler.command == "HEAD":
            return

        try:
            if head:
                handler.wfile.write(head)
            while True:
                chunk = upstream.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # The bot hung up mid-download; nothing left to do.
            pass

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
