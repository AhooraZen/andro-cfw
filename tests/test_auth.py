import os
from unittest.mock import MagicMock, patch

import pytest

from andro_cfw.auth import ACCOUNTS_DIR, _account_env, cloudflare_login, whoami
from andro_cfw.errors import DeploymentError


def test_account_env():
    env_none = _account_env(None)
    assert "WRANGLER_HOME" not in env_none or env_none.get("WRANGLER_HOME") == os.environ.get("WRANGLER_HOME")

    env_acc = _account_env("account-1")
    target_dir = str(ACCOUNTS_DIR / "account-1")
    assert env_acc["WRANGLER_HOME"] == target_dir
    assert env_acc["XDG_CONFIG_HOME"] == target_dir
    assert (ACCOUNTS_DIR / "account-1").exists()


def test_cloudflare_login_success():
    with patch("andro_cfw.auth.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        cloudflare_login()
        mock_run.assert_called_once()
        args, _kwargs = mock_run.call_args
        assert args[0] == ["npx", "--yes", "wrangler", "login"]


def test_cloudflare_login_failure():
    with patch("andro_cfw.auth.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        with pytest.raises(DeploymentError) as exc_info:
            cloudflare_login(account_label="account-1")
        assert "Cloudflare login failed" in str(exc_info.value)


def test_whoami():
    with patch("andro_cfw.auth.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Logged in as test@example.com", stderr="")
        res = whoami("account-1")
        assert res == "Logged in as test@example.com"


def test_account_label_cannot_escape_the_accounts_directory(tmp_path):
    """
    The label becomes a directory name under $HOME. A traversing label would
    let `--name ../../.ssh` point wrangler's OAuth storage anywhere.
    """
    from andro_cfw.auth import _account_env
    from andro_cfw.errors import DeploymentError

    for evil in ("../escape", "a/b", "..", ".", "with space", "~", "acc\x00ount"):
        with pytest.raises(DeploymentError):
            _account_env(evil)


def test_account_dir_is_owner_only(tmp_path, monkeypatch):
    """The directory holds live Cloudflare OAuth tokens."""
    import stat as stat_mod

    from andro_cfw import auth

    monkeypatch.setattr(auth, "ACCOUNTS_DIR", tmp_path / "accounts")
    env = auth._account_env("account-1")

    account_dir = tmp_path / "accounts" / "account-1"
    assert env["WRANGLER_HOME"] == str(account_dir)
    assert env["XDG_CONFIG_HOME"] == str(account_dir)
    assert stat_mod.S_IMODE(account_dir.stat().st_mode) == 0o700
    assert stat_mod.S_IMODE((tmp_path / "accounts").stat().st_mode) == 0o700


def test_account_env_without_a_label_is_untouched(monkeypatch):
    from andro_cfw.auth import _account_env

    monkeypatch.setenv("WRANGLER_HOME", "/preexisting")
    env = _account_env(None)
    assert env["WRANGLER_HOME"] == "/preexisting"
