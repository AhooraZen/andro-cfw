import json
import os
import stat
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from andro_cfw.errors import SessionNotFoundError
from andro_cfw.session import (
    DEFAULT_SESSION_FILENAME,
    CFWSession,
    WorkerEntry,
    _ensure_key,
)


def test_ensure_key(tmp_path):
    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        key1 = _ensure_key()
        assert len(key1) > 0
        key2 = _ensure_key()
        assert key1 == key2


def test_worker_entry():
    entry = WorkerEntry(worker_name="w1", worker_url="https://w1.workers.dev")
    assert entry.worker_name == "w1"
    assert entry.exhausted_until == 0.0
    assert entry.account_label is None


def test_cfw_session_single_and_save_load(tmp_path):
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    session_key = tmp_path / "key"

    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", session_key):

        session = CFWSession.new(worker_name="my-bot", worker_url="https://my-bot.workers.dev")
        saved_path = session.save(str(session_file))
        assert saved_path.exists()

        loaded = CFWSession.load(str(session_file))
        assert loaded.worker_name == "my-bot"
        assert loaded.worker_url == "https://my-bot.workers.dev"
        assert len(loaded.workers) == 1
        assert loaded.workers[0].worker_name == "my-bot"

        # Check API URLs
        assert loaded.api_base_url() == "https://my-bot.workers.dev"
        assert loaded.telebot_api_url() == "https://my-bot.workers.dev/bot{0}/{1}"
        assert loaded.telebot_file_url() == "https://my-bot.workers.dev/file/bot{0}/{1}"
        assert loaded.ptb_base_url() == "https://my-bot.workers.dev/bot"
        assert loaded.ptb_base_file_url() == "https://my-bot.workers.dev/file/bot"
        aiogram_kwargs = loaded.aiogram_server_url()
        assert aiogram_kwargs["base"] == "https://my-bot.workers.dev/bot{token}/{method}"
        assert aiogram_kwargs["file"] == "https://my-bot.workers.dev/file/bot{token}/{path}"


def test_cfw_session_multi(tmp_path):
    entries = [
        ("w1", "https://w1.workers.dev", "acc1"),
        ("w2", "https://w2.workers.dev", "acc2"),
    ]
    session = CFWSession.new_multi(entries)
    assert len(session.workers) == 2
    assert session.workers[0].account_label == "acc1"
    assert session.workers[1].account_label == "acc2"


def test_cfw_session_migration():
    # Legacy session dictionary without `workers` list
    legacy_data = {
        "worker_name": "old-worker",
        "worker_url": "https://old.workers.dev",
        "account_id": "12345",
        "created_at": 1000.0,
    }
    session = CFWSession(**legacy_data)
    assert len(session.workers) == 1
    assert session.workers[0].worker_name == "old-worker"
    assert session.worker_url == "https://old.workers.dev"


def test_cfw_session_load_missing(tmp_path):
    with pytest.raises(SessionNotFoundError) as exc_info:
        CFWSession.load(str(tmp_path / "nonexistent.session"))
    assert "No 'nonexistent.session' found" in str(exc_info.value)


def test_cfw_session_load_invalid_key(tmp_path):
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    session_key = tmp_path / "key"
    session_file.write_bytes(b"invalid corrupt data")

    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", session_key):
        with pytest.raises(SessionNotFoundError) as exc_info:
            CFWSession.load(str(session_file))
        assert "could not be decrypted" in str(exc_info.value)


def test_cfw_session_load_balancer_routing(tmp_path):
    entries = [
        ("w1", "https://w1.workers.dev", "acc1"),
        ("w2", "https://w2.workers.dev", "acc2"),
    ]
    session = CFWSession.new_multi(entries)

    mock_lb = MagicMock()
    mock_lb.base_url.return_value = "http://127.0.0.1:54321"

    with patch.object(session, "_get_load_balancer", return_value=mock_lb):
        assert session.api_base_url() == "http://127.0.0.1:54321"
        assert session.telebot_api_url() == "http://127.0.0.1:54321/bot{0}/{1}"


def test_cfw_session_persist(tmp_path):
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    session_key = tmp_path / "key"

    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", session_key):
        session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
        session._session_path = session_file
        session._persist()
        assert session_file.exists()


def test_check_health():
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_conn.getresponse.return_value = mock_resp

    with patch("http.client.HTTPSConnection", return_value=mock_conn):
        res = session.check_health()
        assert len(res) == 1
        assert res[0]["status"] == 200
        assert res[0]["latency_ms"] >= 0


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    """
    The load balancer persists quota state from request threads. A partial
    write would leave an undecryptable session and force a full re-init.
    """
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
        session.save(str(session_file))
        original = session_file.read_bytes()

        # A failure mid-write must leave the previous file untouched.
        with patch("andro_cfw.session.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                session.save(str(session_file))

        assert session_file.read_bytes() == original
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


def test_concurrent_persists_never_corrupt_the_session(tmp_path):
    """Many threads persisting at once must always leave a loadable file."""
    import threading

    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        session = CFWSession.new_multi([
            ("w1", "https://w1.workers.dev", "acc1"),
            ("w2", "https://w2.workers.dev", "acc2"),
        ])
        session._session_path = session_file
        session.save(str(session_file))

        threads = [threading.Thread(target=session._persist) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        reloaded = CFWSession.load(str(session_file))
        assert len(reloaded.workers) == 2


def test_load_ignores_fields_written_by_a_newer_version(tmp_path):
    """An older install must still read a session a newer one wrote."""
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        key = _ensure_key()
        payload = {
            "workers": [{
                "worker_name": "w1",
                "worker_url": "https://w1.workers.dev",
                "region_hint": "eu-west",     # field from a hypothetical future release
            }],
            "active_index": 0,
            "created_at": 1.0,
            "telemetry_opt_in": True,         # ditto
        }
        session_file.write_bytes(Fernet(key).encrypt(json.dumps(payload).encode()))

        loaded = CFWSession.load(str(session_file))
        assert loaded.workers[0].worker_name == "w1"


def test_load_rejects_non_session_payload(tmp_path):
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    with patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        key = _ensure_key()
        session_file.write_bytes(Fernet(key).encrypt(b'["not", "a", "session"]'))
        with pytest.raises(SessionNotFoundError):
            CFWSession.load(str(session_file))


def test_api_base_url_without_a_worker_raises_actionable_error():
    """Previously an AttributeError on None, which told the user nothing."""
    with pytest.raises(SessionNotFoundError, match="andro-cfw init"):
        CFWSession().api_base_url()


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has no POSIX modes; os.chmod only toggles the read-only bit. "
           "Access is governed by the ACL that %USERPROFILE% already carries.",
)
def test_key_file_and_dir_are_owner_only(tmp_path):
    key_dir = tmp_path / "keys"
    with patch("andro_cfw.session.KEY_DIR", key_dir), \
         patch("andro_cfw.session.KEY_FILE", key_dir / "key"):
        _ensure_key()
        assert stat.S_IMODE((key_dir / "key").stat().st_mode) == 0o600
        assert stat.S_IMODE(key_dir.stat().st_mode) == 0o700


def test_check_health_uses_plain_http_for_http_urls():
    session = CFWSession.new(worker_name="w1", worker_url="http://localhost:8787")
    mock_conn = MagicMock()
    mock_conn.getresponse.return_value = MagicMock(status=200)

    with patch("http.client.HTTPConnection", return_value=mock_conn) as http_conn, \
         patch("http.client.HTTPSConnection") as https_conn:
        results = session.check_health()

    http_conn.assert_called_once()
    https_conn.assert_not_called()
    assert results[0]["status"] == 200
    mock_conn.close.assert_called_once()


def test_check_health_closes_the_connection_on_failure():
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    mock_conn = MagicMock()
    mock_conn.request.side_effect = OSError("network unreachable")

    with patch("http.client.HTTPSConnection", return_value=mock_conn):
        results = session.check_health()

    assert results[0]["status"] == 0
    assert "network unreachable" in results[0]["error"]
    mock_conn.close.assert_called_once()
