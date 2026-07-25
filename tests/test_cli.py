import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from andro_cfw.cli import (
    _session_path,
    cmd_init,
    cmd_add_account,
    cmd_status,
    cmd_check,
    cmd_snippet,
    cmd_remove,
    main,
)
from andro_cfw.errors import DeploymentError, SessionNotFoundError
from andro_cfw.session import CFWSession, WorkerEntry, DEFAULT_SESSION_FILENAME


def test_session_path():
    args_none = argparse.Namespace(path=None)
    assert _session_path(args_none) == Path.cwd() / DEFAULT_SESSION_FILENAME

    args_custom = argparse.Namespace(path="/tmp/myproj")
    assert _session_path(args_custom) == Path("/tmp/myproj") / DEFAULT_SESSION_FILENAME


def test_cmd_init_single(tmp_path):
    args = argparse.Namespace(
        path=str(tmp_path), force=False, accounts=1, name="test-bot"
    )

    with patch("andro_cfw.cli.cloudflare_login") as mock_login, \
         patch("andro_cfw.cli.deploy_worker", return_value=("test-bot", "https://test.workers.dev")), \
         patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):

        ret = cmd_init(args)
        assert ret == 0
        mock_login.assert_called_once()
        assert (tmp_path / DEFAULT_SESSION_FILENAME).exists()


def test_cmd_init_already_exists(tmp_path):
    (tmp_path / DEFAULT_SESSION_FILENAME).write_bytes(b"existing")
    args = argparse.Namespace(path=str(tmp_path), force=False, accounts=1, name="test-bot")
    ret = cmd_init(args)
    assert ret == 1


def test_cmd_init_multi(tmp_path):
    args = argparse.Namespace(
        path=str(tmp_path), force=True, accounts=2, name="multi-bot"
    )

    with patch("andro_cfw.cli.cloudflare_login") as mock_login, \
         patch("andro_cfw.cli.deploy_worker", side_effect=[
             ("multi-bot-1", "https://w1.workers.dev"),
             ("multi-bot-2", "https://w2.workers.dev"),
         ]), \
         patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):

        ret = cmd_init(args)
        assert ret == 0
        assert mock_login.call_count == 2
        assert (tmp_path / DEFAULT_SESSION_FILENAME).exists()


def test_cmd_init_error_handling(tmp_path):
    args = argparse.Namespace(path=str(tmp_path), force=True, accounts=1, name="err-bot")
    with patch("andro_cfw.cli.cloudflare_login", side_effect=DeploymentError("Login error")):
        ret = cmd_init(args)
        assert ret == 1


def test_cmd_add_account(tmp_path):
    args = argparse.Namespace(path=str(tmp_path), name="added-bot")

    mock_session = CFWSession(workers=[WorkerEntry("w1", "https://w1.workers.dev")])

    with patch("andro_cfw.session.CFWSession.load", return_value=mock_session), \
         patch("andro_cfw.cli.cloudflare_login") as mock_login, \
         patch("andro_cfw.cli.deploy_worker", return_value=("added-bot-2", "https://w2.workers.dev")), \
         patch.object(mock_session, "save") as mock_save:

        ret = cmd_add_account(args)
        assert ret == 0
        assert len(mock_session.workers) == 2
        mock_save.assert_called_once()


def test_cmd_add_account_error(tmp_path):
    args = argparse.Namespace(path=str(tmp_path), name="added-bot")
    with patch("andro_cfw.session.CFWSession.load", side_effect=SessionNotFoundError("No session")):
        ret = cmd_add_account(args)
        assert ret == 1


def test_cmd_status_single(tmp_path):
    args = argparse.Namespace(path=str(tmp_path))
    session = CFWSession(worker_name="w1", worker_url="https://w1.workers.dev", created_at=123.0)

    with patch("andro_cfw.cli.CFWSession.load", return_value=session):
        ret = cmd_status(args)
        assert ret == 0


def test_cmd_status_multi(tmp_path):
    args = argparse.Namespace(path=str(tmp_path))
    session = CFWSession.new_multi([
        ("w1", "https://w1.workers.dev", "acc1"),
        ("w2", "https://w2.workers.dev", "acc2"),
    ])

    with patch("andro_cfw.cli.CFWSession.load", return_value=session):
        ret = cmd_status(args)
        assert ret == 0


def test_cmd_status_error(tmp_path):
    args = argparse.Namespace(path=str(tmp_path))
    with patch("andro_cfw.cli.CFWSession.load", side_effect=SessionNotFoundError("No session")):
        ret = cmd_status(args)
        assert ret == 1


def test_cmd_remove(tmp_path):
    session_file = tmp_path / DEFAULT_SESSION_FILENAME
    session_file.write_bytes(b"data")

    args = argparse.Namespace(path=str(tmp_path))
    session = CFWSession.new_multi([
        ("w1", "https://w1.workers.dev", "acc1"),
    ])

    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.teardown_worker") as mock_teardown:
        ret = cmd_remove(args)
        assert ret == 0
        mock_teardown.assert_called_once_with("w1", account_label="acc1")
        assert not session_file.exists()


def test_cmd_remove_error(tmp_path):
    args = argparse.Namespace(path=str(tmp_path))
    with patch("andro_cfw.cli.CFWSession.load", side_effect=SessionNotFoundError("No session")):
        ret = cmd_remove(args)
        assert ret == 1


def test_cmd_check(tmp_path):
    args = argparse.Namespace(path=str(tmp_path), timeout=5)
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    health_mock = [
        {
            "index": 0,
            "worker_name": "w1",
            "worker_url": "https://w1.workers.dev",
            "account_label": None,
            "status": 200,
            "latency_ms": 45.2,
            "is_exhausted": False,
            "exhausted_until": 0,
            "error": None,
        }
    ]

    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch.object(session, "check_health", return_value=health_mock):
        ret = cmd_check(args)
        assert ret == 0


def test_cmd_snippet(tmp_path):
    out_file = tmp_path / "bot.py"
    args = argparse.Namespace(framework="telebot", out=str(out_file))
    ret = cmd_snippet(args)
    assert ret == 0
    assert out_file.exists()
    assert "telebot" in out_file.read_text()


def test_main_cli():
    with patch("andro_cfw.cli.cmd_status", return_value=0) as mock_cmd:
        ret = main(["status"])
        assert ret == 0
        mock_cmd.assert_called_once()


def test_main_cli_keyboard_interrupt():
    with patch("andro_cfw.cli.cmd_status", side_effect=KeyboardInterrupt()):
        ret = main(["status"])
        assert ret == 130

