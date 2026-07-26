import urllib.error
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from andro_cfw.cloudflare import WORKER_MODULE_NAME
from andro_cfw.deploy import (
    _load_template,
    _random_worker_name,
    _wait_until_live,
    client_for,
    deploy_worker,
    login,
    put_worker_secret,
    teardown_worker,
)
from andro_cfw.errors import DeploymentError


class FakeClient:
    """
    Stands in for CloudflareClient, recording every call with its real
    arguments so tests can assert on the sequence rather than on mock plumbing.
    """

    def __init__(self, subdomain="user"):
        self.subdomain = subdomain
        self.calls = []

    def upload_worker(self, script_name, module_source):
        self.calls.append(("upload_worker", script_name, module_source))

    def enable_workers_dev(self, script_name):
        self.calls.append(("enable_workers_dev", script_name))

    def workers_subdomain(self):
        self.calls.append(("workers_subdomain",))
        return self.subdomain

    def put_secret(self, script_name, name, value):
        self.calls.append(("put_secret", script_name, name, value))

    def delete_worker(self, script_name):
        self.calls.append(("delete_worker", script_name))

    def method_names(self):
        return [call[0] for call in self.calls]


class FakeResponse:
    """The context-manager object urlopen returns, with just a status."""

    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def client():
    return FakeClient()


@contextmanager
def no_network(client, live=True):
    """Route deploy through `client` with the readiness poll stubbed out."""
    with patch("andro_cfw.deploy.client_for", return_value=client), \
         patch("andro_cfw.deploy._wait_until_live", return_value=live):
        yield


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_random_worker_name_is_prefixed_and_differs_across_calls():
    names = {_random_worker_name() for _ in range(20)}
    assert len(names) == 20
    assert all(name.startswith("andro-cfw-") for name in names)


def test_load_template_returns_the_worker_module_source():
    source = _load_template(WORKER_MODULE_NAME)
    assert "export default {" in source
    assert "async fetch(" in source


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #

def test_client_for_tells_the_user_to_log_in_when_nothing_is_stored():
    with patch("andro_cfw.deploy.load_credentials", return_value=None), \
         pytest.raises(DeploymentError) as excinfo:
        client_for("work")

    message = str(excinfo.value)
    assert "work" in message
    assert "andro-cfw login" in message


def test_client_for_builds_a_client_from_the_stored_credentials():
    creds = {"api_token": "tok-123", "account_id": "acct-456"}
    with patch("andro_cfw.deploy.load_credentials", return_value=creds) as load:
        built = client_for(None)

    load.assert_called_once_with("default")
    assert built.api_token == "tok-123"
    assert built.account_id == "acct-456"


@pytest.mark.parametrize("given_label,stored_label", [(None, "default"), ("work", "work")])
def test_login_verifies_the_token_and_stores_the_resolved_account_id(given_label, stored_label):
    """
    Every later API call is scoped to the stored account id. Persisting None
    because resolution was skipped breaks the next deploy, not the login.
    """
    api = MagicMock()
    api.resolve_account_id.return_value = "acct-789"

    with patch("andro_cfw.deploy.CloudflareClient", return_value=api), \
         patch("andro_cfw.deploy.save_credentials") as save:
        resolved = login("tok-123", account_label=given_label)

    api.verify_token.assert_called_once_with()
    assert resolved == "acct-789"
    save.assert_called_once_with(stored_label, "tok-123", "acct-789")


# --------------------------------------------------------------------------- #
# Deploying
# --------------------------------------------------------------------------- #

def test_deploy_worker_uploads_before_exposing_the_worker_on_workers_dev(client):
    """
    Order is load bearing: enabling the workers.dev route for a script that has
    not been uploaded yet is a 404 from Cloudflare, not a deploy.
    """
    with no_network(client):
        name, url = deploy_worker(worker_name="andro-cfw-test")

    assert name == "andro-cfw-test"
    assert url == "https://andro-cfw-test.user.workers.dev"
    assert client.method_names() == ["upload_worker", "enable_workers_dev", "workers_subdomain"]
    assert client.calls[0] == (
        "upload_worker", "andro-cfw-test", _load_template(WORKER_MODULE_NAME),
    )


def test_deploy_worker_generates_a_name_when_the_caller_gives_none(client):
    with no_network(client):
        name, url = deploy_worker()

    assert name.startswith("andro-cfw-")
    assert client.calls[0][1] == name
    assert url == f"https://{name}.user.workers.dev"


def test_deploy_worker_succeeds_when_the_hostname_is_not_answering_yet(client):
    """
    workers.dev DNS can take a minute on a brand-new subdomain. Reporting that
    as a failed deploy sends users chasing a problem that fixes itself.
    """
    with no_network(client, live=False):
        name, url = deploy_worker(worker_name="andro-cfw-slow")

    assert (name, url) == ("andro-cfw-slow", "https://andro-cfw-slow.user.workers.dev")
    assert client.method_names() == ["upload_worker", "enable_workers_dev", "workers_subdomain"]


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #

def test_put_worker_secret_passes_the_value_through(client):
    with patch("andro_cfw.deploy.client_for", return_value=client):
        put_worker_secret("andro-cfw-test", "BOT_TOKEN", "12345:AAsecret")

    assert client.calls == [("put_secret", "andro-cfw-test", "BOT_TOKEN", "12345:AAsecret")]


def test_put_worker_secret_failure_never_repeats_the_secret_value():
    """
    This message reaches the terminal and whatever the user pastes into a bug
    report, so it may name the binding but never what was being stored in it.
    """
    api = MagicMock()
    api.put_secret.side_effect = DeploymentError("Cloudflare API error:\n  [10000] bad token")

    with patch("andro_cfw.deploy.client_for", return_value=api), \
         pytest.raises(DeploymentError) as excinfo:
        put_worker_secret("andro-cfw-test", "BOT_TOKEN", "12345:AAsecret")

    assert "BOT_TOKEN" in str(excinfo.value)
    assert "12345:AAsecret" not in str(excinfo.value)
    assert "12345:AAsecret" not in repr(excinfo.value)


# --------------------------------------------------------------------------- #
# Teardown
# --------------------------------------------------------------------------- #

def test_teardown_worker_deletes_the_worker(client):
    with patch("andro_cfw.deploy.client_for", return_value=client):
        teardown_worker("andro-cfw-test", account_label="work")

    assert client.calls == [("delete_worker", "andro-cfw-test")]


def test_teardown_worker_does_not_raise_when_the_api_rejects_the_delete():
    """
    Removal is best effort: a worker already deleted from the dashboard, or an
    expired token, must not block cleaning up the local session.
    """
    api = MagicMock()
    api.delete_worker.side_effect = DeploymentError("script_not_found")

    with patch("andro_cfw.deploy.client_for", return_value=api):
        teardown_worker("andro-cfw-test")

    api.delete_worker.assert_called_once_with("andro-cfw-test")


# --------------------------------------------------------------------------- #
# Readiness polling
# --------------------------------------------------------------------------- #

def test_wait_until_live_returns_true_once_the_worker_answers():
    with patch("andro_cfw.deploy.urllib.request.urlopen", return_value=FakeResponse(200)), \
         patch("andro_cfw.deploy.time.sleep") as sleep:
        assert _wait_until_live("https://andro-cfw-test.user.workers.dev") is True

    sleep.assert_not_called()


def test_wait_until_live_treats_an_http_error_as_live():
    """A 404 still proves the hostname resolved and the script is running."""
    error = urllib.error.HTTPError(
        "https://andro-cfw-test.user.workers.dev", 404, "Not Found", {}, None
    )
    with patch("andro_cfw.deploy.urllib.request.urlopen", side_effect=error), \
         patch("andro_cfw.deploy.time.sleep") as sleep:
        assert _wait_until_live("https://andro-cfw-test.user.workers.dev") is True

    sleep.assert_not_called()


def test_wait_until_live_gives_up_once_the_deadline_passes():
    # Deadline is set from the first reading; the last one is past it.
    clock = iter([0.0, 1.0, 2.0, 10_000.0])

    with patch("andro_cfw.deploy.urllib.request.urlopen", side_effect=OSError("name not resolved")), \
         patch("andro_cfw.deploy.time.time", side_effect=lambda: next(clock)), \
         patch("andro_cfw.deploy.time.sleep") as sleep:
        assert _wait_until_live("https://andro-cfw-test.user.workers.dev") is False

    assert sleep.call_count == 2
