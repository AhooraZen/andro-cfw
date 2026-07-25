import time
import io
import urllib.error
from unittest.mock import patch, MagicMock
from http.server import BaseHTTPRequestHandler

import pytest

from andro_cfw.session import CFWSession, WorkerEntry
from andro_cfw.loadbalancer import (
    _next_utc_midnight,
    _looks_like_quota_error,
    LoadBalancer,
)


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
        status, headers, body = LoadBalancer._forward("https://w1.workers.dev/bot123/getMe", "GET", {}, None)
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

