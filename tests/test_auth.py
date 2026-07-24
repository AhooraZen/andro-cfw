import os
from unittest.mock import patch, MagicMock
import pytest

from andro_cfw.auth import _account_env, cloudflare_login, whoami, ACCOUNTS_DIR
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
        args, kwargs = mock_run.call_args
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
