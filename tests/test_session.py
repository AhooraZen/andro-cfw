import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet

from andro_cfw.session import (
    _ensure_key,
    WorkerEntry,
    CFWSession,
    KEY_FILE,
    DEFAULT_SESSION_FILENAME,
)
from andro_cfw.errors import SessionNotFoundError


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
