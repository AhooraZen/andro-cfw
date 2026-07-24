from unittest.mock import patch, MagicMock
import pytest

from andro_cfw.deploy import (
    _random_worker_name,
    _load_template,
    deploy_worker,
    teardown_worker,
)
from andro_cfw.errors import DeploymentError


def test_random_worker_name():
    name = _random_worker_name()
    assert name.startswith("andro-cfw-")
    assert len(name) == 18


def test_load_template():
    ts = _load_template("worker.ts")
    assert "export default" in ts
    tmpl = _load_template("wrangler.toml.tmpl")
    assert "{worker_name}" in tmpl


def test_deploy_worker_success():
    wrangler_output = (
        "✨ Deployed worker andro-cfw-test successfully!\n"
        "Published andro-cfw-test (0.2s)\n"
        "  https://andro-cfw-test.user.workers.dev\n"
    )
    with patch("andro_cfw.deploy.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=wrangler_output, stderr="")
        name, url = deploy_worker(worker_name="custom-name")
        assert name == "custom-name"
        assert url == "https://andro-cfw-test.user.workers.dev"


def test_deploy_worker_failure_exitcode():
    with patch("andro_cfw.deploy.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: Auth failed")
        with pytest.raises(DeploymentError) as exc_info:
            deploy_worker()
        assert "Failed to deploy the Cloudflare Worker" in str(exc_info.value)


def test_deploy_worker_no_url():
    with patch("andro_cfw.deploy.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Deployed ok", stderr="")
        with pytest.raises(DeploymentError) as exc_info:
            deploy_worker()
        assert "workers.dev URL could not be detected" in str(exc_info.value)


def test_teardown_worker():
    with patch("andro_cfw.deploy.check_node_toolchain"), \
         patch("subprocess.run") as mock_run:
        teardown_worker("my-worker", account_label="account-1")
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert "delete" in args[0]
        assert "my-worker" in args[0]
