import http.client
import io
import socket
import time
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from andro_cfw.loadbalancer import (
    MAX_REQUEST_BODY_BYTES,
    QUOTA_SNIFF_BYTES,
    SPOOL_THRESHOLD_BYTES,
    LoadBalancer,
    _looks_like_quota_error,
    _next_utc_midnight,
)
from andro_cfw.session import CFWSession, WorkerEntry


class FakeUpstream(io.BytesIO):
    """
    Stands in for the object urlopen returns: readable in chunks, closeable.

    Real responses are streamed, so tests must never assume the balancer reads
    the whole body in one call.
    """

    def __init__(self, body: bytes = b""):
        super().__init__(body)
        self.was_closed = False

    def close(self):
        self.was_closed = True
        super().close()


def upstream_result(status=200, headers=None, body=b""):
    """Build the (status, headers, response) triple _open_upstream returns."""
    resolved = dict(headers or {})
    if "Content-Length" not in resolved:
        resolved["Content-Length"] = str(len(body))
    return status, resolved, FakeUpstream(body)


def make_handler(**overrides):
    handler = MagicMock()
    handler.headers = overrides.pop("headers", {})
    handler.path = overrides.pop("path", "/bot123/getMe")
    handler.command = overrides.pop("command", "GET")
    for key, value in overrides.items():
        setattr(handler, key, value)
    return handler


def sent_headers(handler):
    return {call.args[0].lower(): call.args[1] for call in handler.send_header.call_args_list}


def written_body(handler):
    return b"".join(call.args[0] for call in handler.wfile.write.call_args_list)


def make_balancer(*labels, tmp_path=None):
    workers = [WorkerEntry(f"w{i}", f"https://w{i}.workers.dev", label)
               for i, label in enumerate(labels, start=1)]
    session = CFWSession(workers=workers)
    if tmp_path is not None:
        session._session_path = tmp_path / "cfw.session"
    return LoadBalancer(session), session


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_next_utc_midnight():
    assert _next_utc_midnight() > time.time()


def test_looks_like_quota_error():
    assert _looks_like_quota_error(429, "") is True
    assert _looks_like_quota_error(500, "") is False
    assert _looks_like_quota_error(200, "Error 1015: Rate limited") is True
    assert _looks_like_quota_error(200, "You have exceeded your request limit") is True
    assert _looks_like_quota_error(200, "Normal response") is False


# --------------------------------------------------------------------------- #
# Worker selection & lifecycle
# --------------------------------------------------------------------------- #

def test_loadbalancer_worker_selection():
    workers = [
        WorkerEntry("w1", "https://w1.workers.dev", "acc1", exhausted_until=time.time() + 3600),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2", exhausted_until=0.0),
        WorkerEntry("w3", "https://w3.workers.dev", "acc3", exhausted_until=time.time() + 7200),
    ]
    lb = LoadBalancer(CFWSession(workers=workers))
    assert lb._pick_active_worker() == 1

    workers[1].exhausted_until = time.time() + 5000
    assert lb._pick_active_worker() == 0


def test_loadbalancer_mark_exhausted(tmp_path):
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)

    with patch.object(session, "_persist") as mock_persist:
        lb._mark_exhausted(0, "HTTP 429")
        assert session.workers[0].exhausted_until > time.time()
        assert session.workers[0].last_error == "HTTP 429"
        assert session.active_index == 1
        mock_persist.assert_called_once()


def test_mark_exhausted_does_not_hold_the_lock_while_persisting():
    """
    Persisting encrypts and fsyncs the session file. Doing that under the lock
    serialises every in-flight proxied request behind a disk write.
    """
    lb, session = make_balancer("acc1", "acc2")
    observed = {}

    with patch.object(session, "_persist", side_effect=lambda: observed.update(locked=lb._lock.locked())):
        lb._mark_exhausted(0, "HTTP 429")

    assert observed["locked"] is False


def test_loadbalancer_lifecycle():
    lb, _ = make_balancer("acc1")

    url = lb.base_url()
    assert url.startswith("http://127.0.0.1:")
    assert lb.port is not None
    lb.start()  # re-entrant start call
    lb.stop()
    assert lb._server is None


def test_stop_closes_the_listening_socket():
    """shutdown() alone leaves the socket bound for the life of the process."""
    lb, _ = make_balancer("acc1")
    lb.start()
    port, server = lb.port, lb._server
    lb.stop()

    assert lb._server is None
    assert server.socket.fileno() == -1

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


# --------------------------------------------------------------------------- #
# Upstream request construction
# --------------------------------------------------------------------------- #

def test_open_upstream_success():
    resp = MagicMock(status=200)
    resp.getheaders.return_value = [("Content-Type", "application/json")]

    with patch("urllib.request.urlopen", return_value=resp):
        status, headers, returned = LoadBalancer._open_upstream(
            "https://w1.workers.dev/bot123/getMe", "GET", {}, None, 0
        )

    assert status == 200
    assert headers["Content-Type"] == "application/json"
    # Returned unread so the caller can stream it.
    assert returned is resp
    resp.read.assert_not_called()


def test_open_upstream_returns_httperror_as_a_response():
    err = urllib.error.HTTPError(
        "https://w1.workers.dev", 429, "Too Many Requests", {}, io.BytesIO(b"rate limit exceeded")
    )
    with patch("urllib.request.urlopen", side_effect=err):
        status, _headers, resp = LoadBalancer._open_upstream(
            "https://w1.workers.dev/bot123/getMe", "GET", {}, None, 0
        )

    assert status == 429
    assert resp.read() == b"rate limit exceeded"


def test_open_upstream_strips_hop_by_hop_and_accept_encoding():
    """
    Relaying hop-by-hop headers corrupts framing, and a gzipped upstream body
    would make the quota-marker sniffing read binary noise.
    """
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured.update(req.headers)
        return MagicMock(status=200, getheaders=lambda: [])

    headers = {
        "Host": "127.0.0.1",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Transfer-Encoding": "chunked",
        "X-Custom": "keep-me",
    }
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        LoadBalancer._open_upstream("https://w1.workers.dev/bot1/getMe", "POST", headers, None, 0)

    lowered = {k.lower() for k in captured}
    assert "x-custom" in lowered
    for dropped in ("host", "accept-encoding", "connection", "transfer-encoding"):
        assert dropped not in lowered


def test_open_upstream_sets_content_length_for_a_streamed_body():
    """
    http.client only streams a file object when it knows the length; without an
    explicit Content-Length it would silently switch to chunked encoding.
    """
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured.update(req.headers)
        return MagicMock(status=200, getheaders=lambda: [])

    body = io.BytesIO(b"x" * 4096)
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        LoadBalancer._open_upstream("https://w1.workers.dev/bot1/sendDocument", "POST", {}, body, 4096)

    assert {k.lower(): v for k, v in captured.items()}["content-length"] == "4096"


# --------------------------------------------------------------------------- #
# Proxying & failover
# --------------------------------------------------------------------------- #

def test_proxy_request_success():
    lb, _ = make_balancer("acc1")
    handler = make_handler(headers={"Content-Length": "5"}, command="POST")
    handler.rfile.read.side_effect = [b"hello"]

    with patch.object(lb, "_open_upstream", return_value=upstream_result(body=b"response")):
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(200)
    assert written_body(handler) == b"response"


def test_proxy_request_connection_error_failover(tmp_path):
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)
    handler = make_handler()

    with patch.object(lb, "_open_upstream", side_effect=[TimeoutError("timeout"), upstream_result(body=b"ok")]), \
         patch.object(session, "_persist"):
        lb._proxy_request(handler)

    assert session.workers[0].exhausted_until > time.time()
    handler.send_response.assert_called_with(200)


def test_proxy_request_quota_failover_and_all_exhausted(tmp_path):
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)
    handler = make_handler()

    with patch.object(lb, "_open_upstream", side_effect=lambda *a, **k: upstream_result(429, body=b"rate limit")), \
         patch.object(session, "_persist"):
        lb._proxy_request(handler)

    assert session.workers[0].exhausted_until > time.time()
    assert session.workers[1].exhausted_until > time.time()
    handler.send_response.assert_called_with(429)


def test_proxy_request_invalid_content_length():
    lb, _ = make_balancer("acc1")
    handler = make_handler(headers={"Content-Length": "invalid_string_header"})

    with patch.object(lb, "_open_upstream", return_value=upstream_result(body=b"ok")):
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(200)


def test_all_workers_down_sends_a_framed_503(tmp_path):
    """
    Under HTTP/1.1 a response with no Content-Length leaves the client waiting
    for a body that never arrives, so the bot hangs instead of seeing an error.
    """
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)
    handler = make_handler()

    with patch.object(lb, "_open_upstream", side_effect=TimeoutError("timeout")), \
         patch.object(session, "_persist"):
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(503)
    assert int(sent_headers(handler)["content-length"]) > 0


def test_oversized_content_length_is_refused_without_reading_the_body():
    lb, _ = make_balancer("acc1")
    handler = make_handler(headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)})

    with patch.object(lb, "_open_upstream") as mock_open:
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(413)
    handler.rfile.read.assert_not_called()
    mock_open.assert_not_called()


def test_request_body_is_replayed_on_failover(tmp_path):
    """
    Failover retries the same request against the next worker, so the body has
    to survive the first attempt -- it cannot be streamed straight off the
    client socket and consumed.
    """
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)
    handler = make_handler(headers={"Content-Length": "11"}, command="POST")
    handler.rfile.read.side_effect = [b"hello world"]

    seen = []

    def record(url, method, headers, body, content_length):
        seen.append(body.read())
        if len(seen) == 1:
            raise TimeoutError("first worker down")
        return upstream_result(body=b"ok")

    with patch.object(lb, "_open_upstream", side_effect=record), \
         patch.object(session, "_persist"):
        lb._proxy_request(handler)

    assert seen == [b"hello world", b"hello world"]
    handler.send_response.assert_called_with(200)


def test_large_request_body_spills_to_disk_instead_of_ram():
    lb, _ = make_balancer("acc1")
    size = SPOOL_THRESHOLD_BYTES * 2
    handler = make_handler(headers={"Content-Length": str(size)}, command="POST")
    handler.rfile.read.side_effect = lambda n: b"x" * n

    observed = {}

    def inspect(url, method, headers, body, content_length):
        # SpooledTemporaryFile exposes _rolled once it has spilled to disk.
        observed["rolled"] = body._rolled
        observed["length"] = content_length
        return upstream_result(body=b"ok")

    with patch.object(lb, "_open_upstream", side_effect=inspect):
        lb._proxy_request(handler)

    assert observed["rolled"] is True
    assert observed["length"] == size


def test_short_request_body_stays_in_memory():
    lb, _ = make_balancer("acc1")
    handler = make_handler(headers={"Content-Length": "5"}, command="POST")
    handler.rfile.read.side_effect = [b"hello"]

    observed = {}

    def inspect(url, method, headers, body, content_length):
        observed["rolled"] = body._rolled
        return upstream_result(body=b"ok")

    with patch.object(lb, "_open_upstream", side_effect=inspect):
        lb._proxy_request(handler)

    assert observed["rolled"] is False


# --------------------------------------------------------------------------- #
# Response streaming
# --------------------------------------------------------------------------- #

def test_response_larger_than_the_sniff_window_is_relayed_intact():
    """A file download must not be truncated to the quota-sniffing prefix."""
    lb, _ = make_balancer("acc1")
    handler = make_handler()
    payload = bytes(range(256)) * 4096   # 1 MiB, well past QUOTA_SNIFF_BYTES

    with patch.object(lb, "_open_upstream", return_value=upstream_result(body=payload)):
        lb._proxy_request(handler)

    assert written_body(handler) == payload
    assert sent_headers(handler)["content-length"] == str(len(payload))


def test_response_body_is_not_buffered_whole():
    """
    The balancer must hand the client chunks as they arrive rather than reading
    the entire response first -- that is the point of streaming.
    """
    lb, _ = make_balancer("acc1")
    handler = make_handler()
    payload = b"z" * (QUOTA_SNIFF_BYTES * 20)

    with patch.object(lb, "_open_upstream", return_value=upstream_result(body=payload)):
        lb._proxy_request(handler)

    # Prefix + at least one streamed chunk, never a single whole-body write.
    assert handler.wfile.write.call_count > 1
    assert max(len(call.args[0]) for call in handler.wfile.write.call_args_list) < len(payload)


def test_unknown_length_response_closes_the_connection():
    """
    urllib decodes chunked upstream responses, leaving no Content-Length. The
    only other legal HTTP/1.1 body delimiter is closing the connection.
    """
    lb, _ = make_balancer("acc1")
    handler = make_handler()
    status, headers, resp = upstream_result(body=b"streamed")
    headers.pop("Content-Length")

    with patch.object(lb, "_open_upstream", return_value=(status, headers, resp)):
        lb._proxy_request(handler)

    assert sent_headers(handler)["connection"] == "close"
    assert "content-length" not in sent_headers(handler)
    assert handler.close_connection is True
    assert written_body(handler) == b"streamed"


def test_head_request_sends_headers_without_a_body():
    lb, _ = make_balancer("acc1")
    handler = make_handler(command="HEAD")

    with patch.object(lb, "_open_upstream", return_value=upstream_result(body=b"ignored")):
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(200)
    handler.wfile.write.assert_not_called()


def test_upstream_is_closed_even_when_the_client_disconnects():
    lb, _ = make_balancer("acc1")
    handler = make_handler()
    handler.wfile.write.side_effect = BrokenPipeError()
    result = upstream_result(body=b"payload")

    with patch.object(lb, "_open_upstream", return_value=result):
        lb._proxy_request(handler)   # must not raise

    assert result[2].was_closed is True


def test_send_response_drops_hop_by_hop_headers():
    handler = MagicMock()
    LoadBalancer._send_response(
        handler, 200,
        {"Content-Type": "application/json", "Transfer-Encoding": "chunked", "Connection": "close"},
        b"{}",
    )
    sent = sent_headers(handler)
    assert "content-type" in sent
    assert "transfer-encoding" not in sent
    assert "connection" not in sent


def test_send_response_survives_a_broken_pipe():
    handler = MagicMock()
    handler.wfile.write.side_effect = BrokenPipeError()
    LoadBalancer._send_response(handler, 200, {}, b"OK")   # must not raise


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("payload_size", [16, 1024 * 512])
def test_end_to_end_failover_over_a_real_socket(tmp_path, payload_size):
    """
    Drive the balancer through an actual HTTP request: the first worker 429s,
    and the client must transparently receive the second worker's response --
    for both a tiny JSON reply and a payload larger than the sniff window.
    """
    lb, session = make_balancer("acc1", "acc2", tmp_path=tmp_path)
    payload = b"a" * payload_size

    def fake_open(url, method, headers, body, content_length):
        if url.startswith("https://w1."):
            return upstream_result(429, body=b"rate limit")
        return upstream_result(200, {"Content-Type": "application/json"}, payload)

    with patch.object(lb, "_open_upstream", side_effect=fake_open), \
         patch.object(session, "_persist"):
        lb.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", lb.port, timeout=10)
            conn.request("GET", "/bot123/getMe")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
        finally:
            lb.stop()

    assert resp.status == 200
    assert body == payload
    assert session.workers[0].exhausted_until > time.time()
    assert session.workers[1].exhausted_until == 0.0
