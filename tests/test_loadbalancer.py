import http.client
import socket
import time
import urllib.error
from unittest.mock import MagicMock, patch

from andro_cfw.loadbalancer import (
    MAX_REQUEST_BODY_BYTES,
    LoadBalancer,
    _looks_like_quota_error,
    _next_utc_midnight,
)
from andro_cfw.session import CFWSession, WorkerEntry


def test_next_utc_midnight():
    ts = _next_utc_midnight()
    assert ts > time.time()


def test_looks_like_quota_error():
    assert _looks_like_quota_error(429, "") is True
    assert _looks_like_quota_error(500, "") is False
    assert _looks_like_quota_error(200, "Error 1015: Rate limited") is True
    assert _looks_like_quota_error(200, "You have exceeded your request limit") is True
    assert _looks_like_quota_error(200, "Normal response") is False


def test_loadbalancer_worker_selection():
    workers = [
        WorkerEntry("w1", "https://w1.workers.dev", "acc1", exhausted_until=time.time() + 3600),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2", exhausted_until=0.0),
        WorkerEntry("w3", "https://w3.workers.dev", "acc3", exhausted_until=time.time() + 7200),
    ]
    session = CFWSession(workers=workers)
    lb = LoadBalancer(session)
    assert lb._pick_active_worker() == 1

    workers[1].exhausted_until = time.time() + 5000
    assert lb._pick_active_worker() == 0


def test_loadbalancer_mark_exhausted(tmp_path):
    workers = [
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ]
    session = CFWSession(workers=workers)
    session._session_path = tmp_path / "cfw.session"
    lb = LoadBalancer(session)

    with patch.object(session, "_persist") as mock_persist:
        lb._mark_exhausted(0, "HTTP 429")
        assert workers[0].exhausted_until > time.time()
        assert workers[0].last_error == "HTTP 429"
        assert session.active_index == 1
        mock_persist.assert_called_once()


def test_loadbalancer_lifecycle():
    workers = [WorkerEntry("w1", "https://w1.workers.dev", "acc1")]
    session = CFWSession(workers=workers)
    lb = LoadBalancer(session)

    url = lb.base_url()
    assert url.startswith("http://127.0.0.1:")
    assert lb.port is not None
    lb.start()  # re-entrant start call
    lb.stop()
    assert lb._server is None


def test_loadbalancer_forward_success():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.getheaders.return_value = [("Content-Type", "application/json")]
    mock_resp.read.return_value = b'{"ok": true}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, headers, body = LoadBalancer._forward("https://w1.workers.dev/bot123/getMe", "GET", {}, None)
        assert status == 200
        assert headers["Content-Type"] == "application/json"
        assert body == b'{"ok": true}'


def test_loadbalancer_forward_httperror():
    mock_err = urllib.error.HTTPError(
        "https://w1.workers.dev", 429, "Too Many Requests", {}, MagicMock(read=lambda: b"rate limit exceeded")
    )
    with patch("urllib.request.urlopen", side_effect=mock_err):
        status, _headers, body = LoadBalancer._forward("https://w1.workers.dev/bot123/getMe", "GET", {}, None)
        assert status == 429
        assert body == b"rate limit exceeded"


def test_send_response():
    mock_handler = MagicMock()
    LoadBalancer._send_response(mock_handler, 200, {"Header": "Value"}, b"OK")
    mock_handler.send_response.assert_called_with(200)
    mock_handler.send_header.assert_any_call("Header", "Value")
    mock_handler.send_header.assert_any_call("Content-Length", "2")
    mock_handler.end_headers.assert_called_once()
    mock_handler.wfile.write.assert_called_with(b"OK")

    # Test BrokenPipeError handling
    mock_handler.wfile.write.side_effect = BrokenPipeError()
    LoadBalancer._send_response(mock_handler, 200, {}, b"OK")


def test_proxy_request_success():
    workers = [WorkerEntry("w1", "https://w1.workers.dev", "acc1")]
    session = CFWSession(workers=workers)
    lb = LoadBalancer(session)

    handler = MagicMock()
    handler.headers = {"Content-Length": "5"}
    handler.rfile.read.return_value = b"hello"
    handler.path = "/bot123/getMe"
    handler.command = "POST"

    with patch.object(lb, "_forward", return_value=(200, {"Content-Type": "text/plain"}, b"response")):
        lb._proxy_request(handler)
        handler.send_response.assert_called_with(200)


def test_proxy_request_connection_error_failover(tmp_path):
    workers = [
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ]
    session = CFWSession(workers=workers)
    session._session_path = tmp_path / "cfw.session"
    lb = LoadBalancer(session)

    handler = MagicMock()
    handler.headers = {}
    handler.path = "/bot123/getMe"
    handler.command = "GET"

    with patch.object(lb, "_forward", side_effect=[TimeoutError("timeout"), (200, {}, b"ok")]):
        lb._proxy_request(handler)
        assert workers[0].exhausted_until > time.time()
        handler.send_response.assert_called_with(200)


def test_proxy_request_quota_failover_and_all_exhausted(tmp_path):
    workers = [
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ]
    session = CFWSession(workers=workers)
    session._session_path = tmp_path / "cfw.session"
    lb = LoadBalancer(session)

    handler = MagicMock()
    handler.headers = {}
    handler.path = "/bot123/getMe"
    handler.command = "GET"

    # Both fail with 429
    with patch.object(lb, "_forward", return_value=(429, {}, b"rate limit")):
        lb._proxy_request(handler)
        assert workers[0].exhausted_until > time.time()
        assert workers[1].exhausted_until > time.time()
        handler.send_response.assert_called_with(429)


def test_proxy_request_invalid_content_length():
    workers = [WorkerEntry("w1", "https://w1.workers.dev", "acc1")]
    session = CFWSession(workers=workers)
    lb = LoadBalancer(session)

    handler = MagicMock()
    handler.headers = {"Content-Length": "invalid_string_header"}
    handler.path = "/bot123/getMe"
    handler.command = "GET"

    with patch.object(lb, "_forward", return_value=(200, {}, b"ok")):
        lb._proxy_request(handler)
        handler.send_response.assert_called_with(200)



def _mock_handler(**overrides):
    handler = MagicMock()
    handler.headers = overrides.pop("headers", {})
    handler.path = overrides.pop("path", "/bot123/getMe")
    handler.command = overrides.pop("command", "GET")
    for key, value in overrides.items():
        setattr(handler, key, value)
    return handler


def test_all_workers_down_sends_a_framed_503(tmp_path):
    """
    Under HTTP/1.1 a response with no Content-Length leaves the client waiting
    for a body that never arrives, so the bot hangs instead of seeing an error.
    """
    session = CFWSession(workers=[
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ])
    session._session_path = tmp_path / "cfw.session"
    lb = LoadBalancer(session)
    handler = _mock_handler()

    with patch.object(lb, "_forward", side_effect=TimeoutError("timeout")), \
         patch.object(session, "_persist"):
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(503)
    sent = dict(call.args for call in handler.send_header.call_args_list)
    assert "Content-Length" in sent
    assert int(sent["Content-Length"]) > 0


def test_oversized_content_length_is_refused_without_reading_the_body():
    session = CFWSession(workers=[WorkerEntry("w1", "https://w1.workers.dev", "acc1")])
    lb = LoadBalancer(session)
    handler = _mock_handler(headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)})

    with patch.object(lb, "_forward") as mock_forward:
        lb._proxy_request(handler)

    handler.send_response.assert_called_with(413)
    handler.rfile.read.assert_not_called()
    mock_forward.assert_not_called()


def test_forward_strips_hop_by_hop_and_accept_encoding():
    """
    Relaying hop-by-hop headers corrupts framing, and a gzipped upstream body
    would make the quota-marker sniffing read binary noise.
    """
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured.update(req.headers)
        resp = MagicMock()
        resp.status = 200
        resp.getheaders.return_value = []
        resp.read.return_value = b"ok"
        resp.__enter__.return_value = resp
        return resp

    headers = {
        "Host": "127.0.0.1",
        "Content-Length": "2",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Transfer-Encoding": "chunked",
        "X-Custom": "keep-me",
    }
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        LoadBalancer._forward("https://w1.workers.dev/bot1/getMe", "POST", headers, b"hi")

    lowered = {k.lower() for k in captured}
    assert "x-custom" in lowered
    for dropped in ("host", "content-length", "accept-encoding", "connection", "transfer-encoding"):
        assert dropped not in lowered


def test_send_response_drops_hop_by_hop_headers():
    handler = MagicMock()
    LoadBalancer._send_response(
        handler, 200,
        {"Content-Type": "application/json", "Transfer-Encoding": "chunked", "Connection": "close"},
        b"{}",
    )
    sent = {call.args[0].lower() for call in handler.send_header.call_args_list}
    assert "content-type" in sent
    assert "transfer-encoding" not in sent
    assert "connection" not in sent


def test_stop_closes_the_listening_socket():
    """shutdown() alone leaves the socket bound for the life of the process."""
    session = CFWSession(workers=[WorkerEntry("w1", "https://w1.workers.dev", "acc1")])
    lb = LoadBalancer(session)
    lb.start()
    port = lb.port
    server = lb._server
    lb.stop()

    assert lb._server is None
    assert server.socket.fileno() == -1

    # The port is free again, so a second balancer can bind it.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_mark_exhausted_does_not_hold_the_lock_while_persisting():
    """
    Persisting encrypts and fsyncs the session file. Doing that under the lock
    serialises every in-flight proxied request behind a disk write.
    """
    session = CFWSession(workers=[
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ])
    lb = LoadBalancer(session)
    observed = {}

    def check_lock():
        observed["locked_during_persist"] = lb._lock.locked()

    with patch.object(session, "_persist", side_effect=check_lock):
        lb._mark_exhausted(0, "HTTP 429")

    assert observed["locked_during_persist"] is False


def test_end_to_end_failover_over_a_real_socket(tmp_path):
    """
    Drive the balancer through an actual HTTP request: the first worker 429s,
    and the client must transparently receive the second worker's response.
    """
    session = CFWSession(workers=[
        WorkerEntry("w1", "https://w1.workers.dev", "acc1"),
        WorkerEntry("w2", "https://w2.workers.dev", "acc2"),
    ])
    session._session_path = tmp_path / "cfw.session"
    lb = LoadBalancer(session)

    responses = {
        "https://w1.workers.dev/bot123/getMe": (429, {"Content-Type": "text/plain"}, b"rate limit"),
        "https://w2.workers.dev/bot123/getMe": (200, {"Content-Type": "application/json"}, b'{"ok":true}'),
    }

    with patch.object(LoadBalancer, "_forward", staticmethod(lambda url, *a, **k: responses[url])), \
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
    assert body == b'{"ok":true}'
    assert session.workers[0].exhausted_until > time.time()
    assert session.workers[1].exhausted_until == 0.0
