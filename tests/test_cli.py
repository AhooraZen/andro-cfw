import argparse
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from andro_cfw.cli import (
    _session_path,
    cmd_add_account,
    cmd_check,
    cmd_deploy_serverless,
    cmd_init,
    cmd_remove,
    cmd_snippet,
    cmd_status,
    main,
)
from andro_cfw.errors import DeploymentError, SessionNotFoundError
from andro_cfw.session import DEFAULT_SESSION_FILENAME, CFWSession, WorkerEntry


def test_session_path():
    args_none = argparse.Namespace(path=None)
    assert _session_path(args_none) == Path.cwd() / DEFAULT_SESSION_FILENAME

    args_custom = argparse.Namespace(path=str(Path("myproj").resolve()))
    assert _session_path(args_custom) == Path("myproj").resolve() / DEFAULT_SESSION_FILENAME


def test_cmd_init_single(tmp_path):
    args = argparse.Namespace(
        path=str(tmp_path), force=False, accounts=1, name="test-bot"
    )

    with patch("andro_cfw.cli._ensure_logged_in", return_value=True) as mock_login, \
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

    with patch("andro_cfw.cli._ensure_logged_in", return_value=True) as mock_login, \
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
    with patch("andro_cfw.cli._ensure_logged_in", return_value=True), \
         patch("andro_cfw.cli.deploy_worker", side_effect=DeploymentError("deploy failed")):
        ret = cmd_init(args)
        assert ret == 1


def test_cmd_add_account(tmp_path):
    args = argparse.Namespace(path=str(tmp_path), name="added-bot")

    mock_session = CFWSession(workers=[WorkerEntry("w1", "https://w1.workers.dev")])

    with patch("andro_cfw.session.CFWSession.load", return_value=mock_session), \
         patch("andro_cfw.cli._ensure_logged_in", return_value=True), \
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


VALID_TOKEN = "123456789:AAEhBOweik6ad9r_QXbSJLmRbCkuKBDlvBQ"


def _serverless_args(tmp_path, **overrides):
    defaults = dict(token=VALID_TOKEN, forward_url=None, path=str(tmp_path))
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _telegram_response(payload: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def test_cmd_deploy_serverless_success(tmp_path):
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")

    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret") as mock_secret, \
         patch("urllib.request.urlopen", return_value=_telegram_response({"ok": True, "result": True})):
        assert cmd_deploy_serverless(_serverless_args(tmp_path)) == 0

    stored = {call.args[1]: call.args[2] for call in mock_secret.call_args_list}
    assert stored["BOT_TOKEN"] == VALID_TOKEN
    # A fresh high-entropy secret must be generated, not derived from the token.
    assert len(stored["WEBHOOK_SECRET"]) >= 32
    assert VALID_TOKEN not in stored["WEBHOOK_SECRET"]


def test_cmd_deploy_serverless_sends_secret_token_and_no_token_in_webhook_url(tmp_path):
    """
    Regression guard: the webhook URL handed to Telegram must not embed the bot
    token. Telegram stores that URL and replays it on every single update.
    """
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return _telegram_response({"ok": True})

    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert cmd_deploy_serverless(_serverless_args(tmp_path)) == 0

    assert captured["body"]["url"] == "https://w1.workers.dev/webhook"
    assert VALID_TOKEN not in captured["body"]["url"]
    assert captured["body"]["secret_token"]
    assert captured["url"].endswith("/setWebhook")


def test_cmd_deploy_serverless_reports_telegram_rejection(tmp_path):
    """HTTP 200 with {"ok": false} is a failure, not a success."""
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    rejection = {"ok": False, "error_code": 401, "description": "Unauthorized"}

    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret"), \
         patch("urllib.request.urlopen", return_value=_telegram_response(rejection)):
        assert cmd_deploy_serverless(_serverless_args(tmp_path)) == 1


@pytest.mark.parametrize("bad", ["no-colon", "abc:def", "123:short", ":onlycolon"])
def test_cmd_deploy_serverless_rejects_malformed_token(tmp_path, bad):
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret") as mock_secret, \
         patch.dict(os.environ, {}, clear=True):
        assert cmd_deploy_serverless(_serverless_args(tmp_path, token=bad)) == 1
    mock_secret.assert_not_called()


def test_cmd_deploy_serverless_cancelled_at_prompt(tmp_path):
    """Ctrl-D at the hidden token prompt exits 130, it does not deploy."""
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret") as mock_secret, \
         patch("andro_cfw.cli.getpass.getpass", side_effect=EOFError), \
         patch.dict(os.environ, {}, clear=True):
        assert cmd_deploy_serverless(_serverless_args(tmp_path, token=None)) == 130
    mock_secret.assert_not_called()


def test_cmd_deploy_serverless_reads_token_from_environment(tmp_path):
    session = CFWSession.new(worker_name="w1", worker_url="https://w1.workers.dev")
    with patch("andro_cfw.cli.CFWSession.load", return_value=session), \
         patch("andro_cfw.cli.put_worker_secret") as mock_secret, \
         patch("urllib.request.urlopen", return_value=_telegram_response({"ok": True})), \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": VALID_TOKEN}):
        assert cmd_deploy_serverless(_serverless_args(tmp_path, token=None)) == 0
    assert mock_secret.call_args_list[0].args[2] == VALID_TOKEN


def test_cmd_snippet_refuses_mtproto_frameworks(tmp_path):
    """pyrogram/hydrogram cannot be proxied; emitting a snippet would mislead."""
    args = argparse.Namespace(framework="pyrogram", out=str(tmp_path / "bot.py"))
    assert cmd_snippet(args) == 1
    assert not (tmp_path / "bot.py").exists()


def test_cmd_snippet_patch_oneliner(tmp_path):
    out_file = tmp_path / "bot.py"
    assert cmd_snippet(argparse.Namespace(framework="patch", out=str(out_file))) == 0
    assert "from andro_cfw import patch" in out_file.read_text()


def test_cli_exposes_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0




def test_cmd_init_stops_when_login_is_cancelled(tmp_path):
    """
    A cancelled credential prompt must not go on to deploy. It previously could
    not happen -- wrangler raised -- but _ensure_logged_in signals with False.
    """
    args = argparse.Namespace(path=str(tmp_path), force=True, accounts=1, name="bot")
    with patch("andro_cfw.cli._ensure_logged_in", return_value=False), \
         patch("andro_cfw.cli.deploy_worker") as mock_deploy:
        assert cmd_init(args) == 1
    mock_deploy.assert_not_called()


def test_ensure_logged_in_skips_the_prompt_when_credentials_exist():
    from andro_cfw.cli import _ensure_logged_in

    with patch("andro_cfw.cli.stored_account_labels", return_value=["default"]), \
         patch("andro_cfw.cli._prompt_api_token") as mock_prompt, \
         patch("andro_cfw.cli.login") as mock_login:
        assert _ensure_logged_in("default") is True
    mock_prompt.assert_not_called()
    mock_login.assert_not_called()


def test_ensure_logged_in_prefers_the_environment_over_prompting():
    """argv and prompts both cost the user something; an env var costs nothing."""
    from andro_cfw.cli import _ensure_logged_in

    with patch("andro_cfw.cli.stored_account_labels", return_value=[]), \
         patch("andro_cfw.cli._prompt_api_token") as mock_prompt, \
         patch("andro_cfw.cli.login") as mock_login, \
         patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "cf-token-value"}):
        assert _ensure_logged_in("default") is True

    mock_prompt.assert_not_called()
    assert mock_login.call_args.args[0] == "cf-token-value"


def test_ensure_logged_in_reports_a_rejected_token():
    from andro_cfw.cli import _ensure_logged_in
    from andro_cfw.errors import DeploymentError as DE

    with patch("andro_cfw.cli.stored_account_labels", return_value=[]), \
         patch("andro_cfw.cli._prompt_api_token", return_value="bad-token"), \
         patch("andro_cfw.cli.login", side_effect=DE("Cloudflare API error")):
        assert _ensure_logged_in("default") is False


def test_help_does_not_leak_argparse_internals(capsys):
    """
    A literal '%' in a help string makes argparse interpolate its own action
    dict into the output. The deploy-serverless help says "100% serverless".
    """
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "100% serverless" in out
    assert "option_strings" not in out


def test_every_subcommand_is_reachable(capsys):
    """Each advertised command must parse; a broken parser is invisible otherwise."""
    for command in ("login", "daemon", "logs", "init", "status", "check",
                    "snippet", "remove", "setup-path", "add-account", "serverless"):
        with pytest.raises(SystemExit) as exc:
            main([command, "--help"])
        assert exc.value.code == 0, command
