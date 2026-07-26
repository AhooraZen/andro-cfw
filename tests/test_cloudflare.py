import contextlib
import email
import json
import os
import stat
import urllib.error
from unittest.mock import patch

import pytest

from andro_cfw.cloudflare import (
    CloudflareClient,
    _encode_multipart,
    forget_credentials,
    load_credentials,
    save_credentials,
    stored_account_labels,
)
from andro_cfw.errors import DeploymentError

ACCOUNT = "acc-0123456789"


class FakeResponse:
    """Stands in for the object urlopen returns: read once, used as a context manager."""

    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def api_payload(result=None, success=True, errors=None) -> bytes:
    body = {"success": success, "result": result, "errors": errors or [], "messages": []}
    return json.dumps(body).encode("utf-8")


def fake_urlopen(payload, captured=None):
    """Replacement for urllib.request.urlopen that records the outgoing Request."""

    def _open(request, timeout=None):
        if captured is not None:
            captured.append(request)
        return FakeResponse(payload)

    return _open


def parse_multipart(content_type: str, body: bytes) -> dict:
    """Re-parse an encoded body with the stdlib email parser, keyed by part name."""
    message = email.message_from_bytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    assert message.is_multipart()
    return {
        part.get_param("name", header="content-disposition"): part
        for part in message.get_payload()
    }


@contextlib.contextmanager
def isolated_credentials(tmp_path):
    """Keep every credential read and write inside tmp_path, never the real ~/.andro_cfw."""
    credentials_file = tmp_path / "credentials"
    with patch("andro_cfw.cloudflare.CREDENTIALS_FILE", credentials_file), \
         patch("andro_cfw.cloudflare.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_DIR", tmp_path), \
         patch("andro_cfw.session.KEY_FILE", tmp_path / "key"):
        yield credentials_file


# --------------------------------------------------------------------------- #
# Multipart encoding
# --------------------------------------------------------------------------- #

def test_encode_multipart_body_parses_back_into_the_parts_it_was_given():
    """
    The upload is hand-rolled rather than built by an HTTP library, so a stray
    newline or a missing boundary would only surface as a Cloudflare rejection.
    """
    content_type, body = _encode_multipart(
        fields={"metadata": ("application/json", '{"main_module": "worker.mjs"}')},
        files={"worker.mjs": ("worker.mjs", "application/javascript+module", "export default {};")},
    )

    boundary = content_type.split("boundary=")[1]
    assert content_type.startswith("multipart/form-data;")
    assert boundary in content_type
    assert body.count(f"--{boundary}\r\n".encode()) == 2
    assert body.endswith(f"--{boundary}--\r\n".encode())

    parts = parse_multipart(content_type, body)
    assert set(parts) == {"metadata", "worker.mjs"}

    metadata = parts["metadata"]
    assert metadata.get_content_type() == "application/json"
    assert metadata.get_param("filename", header="content-disposition") is None
    assert json.loads(metadata.get_payload()) == {"main_module": "worker.mjs"}

    module = parts["worker.mjs"]
    assert module.get_content_type() == "application/javascript+module"
    assert module.get_param("filename", header="content-disposition") == "worker.mjs"
    assert module.get_payload().strip() == "export default {};"


# --------------------------------------------------------------------------- #
# Transport & error reporting
# --------------------------------------------------------------------------- #

def test_request_raises_when_the_api_reports_failure():
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(success=False, errors=[{"code": 10007, "message": "workers.api.error"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        with pytest.raises(DeploymentError) as exc_info:
            client._request("GET", "/user/tokens/verify")

    message = str(exc_info.value)
    assert "10007" in message
    assert "workers.api.error" in message


@pytest.mark.parametrize("code", [10000, 9109])
def test_an_authentication_error_code_adds_the_api_token_hint(code):
    """These two codes mean 'bad or under-scoped token', which the user can fix themselves."""
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(success=False, errors=[{"code": code, "message": "Authentication error"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        with pytest.raises(DeploymentError) as exc_info:
            client._request("GET", "/user/tokens/verify")

    assert "dash.cloudflare.com/profile/api-tokens" in str(exc_info.value)


def test_an_unrelated_error_code_does_not_add_the_api_token_hint():
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(success=False, errors=[{"code": 10021, "message": "Script too large"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        with pytest.raises(DeploymentError) as exc_info:
            client._request("GET", "/user/tokens/verify")

    assert "api-tokens" not in str(exc_info.value)


def test_a_failure_with_no_errors_listed_still_explains_itself():
    client = CloudflareClient("token", account_id=ACCOUNT)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(success=False))):
        with pytest.raises(DeploymentError, match="no reason"):
            client._request("GET", "/user/tokens/verify")


def test_an_unreachable_api_is_reported_as_a_connectivity_problem():
    """A raw URLError traceback tells a filtered-region user nothing actionable."""
    client = CloudflareClient("token", account_id=ACCOUNT)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network is unreachable")):
        with pytest.raises(DeploymentError) as exc_info:
            client._request("GET", "/user/tokens/verify")

    message = str(exc_info.value)
    assert "Could not reach the Cloudflare API" in message
    assert "Network is unreachable" in message
    assert "internet connection" in message


def test_a_non_json_response_is_reported_clearly():
    client = CloudflareClient("token", account_id=ACCOUNT)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(b"<html>502 Bad Gateway</html>")):
        with pytest.raises(DeploymentError, match="not JSON"):
            client._request("GET", "/user/tokens/verify")


def test_an_http_error_body_is_parsed_instead_of_propagated():
    """Cloudflare returns its error JSON with a 4xx status, so the body still matters."""
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(success=False, errors=[{"code": 10007, "message": "no such script"}])
    error = urllib.error.HTTPError("https://api.cloudflare.com", 404, "Not Found", {}, None)
    error.read = lambda: payload

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(DeploymentError, match="no such script"):
            client._request("GET", "/accounts/x/workers/scripts/y")


# --------------------------------------------------------------------------- #
# Account discovery
# --------------------------------------------------------------------------- #

def test_resolve_account_id_picks_the_only_account_the_token_can_see():
    client = CloudflareClient("token")
    payload = api_payload(result=[{"id": "acc-1", "name": "Personal"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        assert client.resolve_account_id() == "acc-1"


def test_resolve_account_id_refuses_to_guess_between_several_accounts():
    """Deploying into the wrong Cloudflare account is silent and hard to undo."""
    client = CloudflareClient("token")
    payload = api_payload(result=[
        {"id": "acc-1", "name": "Personal"},
        {"id": "acc-2", "name": "Work"},
    ])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        with pytest.raises(DeploymentError) as exc_info:
            client.resolve_account_id()

    message = str(exc_info.value)
    assert "acc-1" in message
    assert "acc-2" in message
    assert "Personal" in message
    assert "Work" in message
    assert "--account-id" in message
    assert client.account_id is None


def test_resolve_account_id_reports_a_token_that_can_see_no_account():
    client = CloudflareClient("token")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result=[]))):
        with pytest.raises(DeploymentError) as exc_info:
            client.resolve_account_id()

    assert "scoped too narrowly" in str(exc_info.value)


def test_resolve_account_id_does_not_call_the_api_when_it_is_already_known():
    client = CloudflareClient("token", account_id=ACCOUNT)

    with patch("urllib.request.urlopen", side_effect=AssertionError("no request expected")):
        assert client.resolve_account_id() == ACCOUNT


def test_workers_subdomain_returns_the_claimed_subdomain():
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(result={"subdomain": "my-name"})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        assert client.workers_subdomain() == "my-name"


def test_workers_subdomain_tells_the_user_how_to_claim_a_missing_one():
    """A fresh Cloudflare account has no subdomain, and the API just returns null for it."""
    client = CloudflareClient("token", account_id=ACCOUNT)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}))):
        with pytest.raises(DeploymentError) as exc_info:
            client.workers_subdomain()

    message = str(exc_info.value)
    assert "no workers.dev subdomain yet" in message
    assert "dash.cloudflare.com" in message


# --------------------------------------------------------------------------- #
# Worker lifecycle
# --------------------------------------------------------------------------- #

def test_upload_worker_puts_the_module_to_the_script_endpoint():
    client = CloudflareClient("token", account_id=ACCOUNT)
    captured = []

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}), captured)):
        client.upload_worker("my-bot", "export default { fetch() {} };")

    request = captured[0]
    assert request.get_method() == "PUT"
    assert request.full_url.endswith(f"/accounts/{ACCOUNT}/workers/scripts/my-bot")
    assert request.get_header("Authorization") == "Bearer token"

    parts = parse_multipart(request.get_header("Content-type"), request.data)
    assert parts["worker.mjs"].get_payload().strip() == "export default { fetch() {} };"


def test_upload_worker_keeps_the_secrets_already_stored_on_the_worker():
    """
    Without keep_bindings a re-upload wipes BOT_TOKEN and WEBHOOK_SECRET, and the
    worker starts answering every request with an auth failure.
    """
    client = CloudflareClient("token", account_id=ACCOUNT)
    captured = []

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}), captured)):
        client.upload_worker("my-bot", "export default {};")

    parts = parse_multipart(captured[0].get_header("Content-type"), captured[0].data)
    metadata = json.loads(parts["metadata"].get_payload())
    assert metadata["main_module"] == "worker.mjs"
    assert metadata["keep_bindings"] == ["secret_text"]


def test_enable_workers_dev_posts_the_enabled_flag():
    client = CloudflareClient("token", account_id=ACCOUNT)
    captured = []

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}), captured)):
        client.enable_workers_dev("my-bot")

    request = captured[0]
    assert request.get_method() == "POST"
    assert request.full_url.endswith(f"/accounts/{ACCOUNT}/workers/scripts/my-bot/subdomain")
    assert json.loads(request.data) == {"enabled": True}


def test_put_secret_sends_the_value_in_the_request_body():
    client = CloudflareClient("token", account_id=ACCOUNT)
    captured = []

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}), captured)):
        client.put_secret("my-bot", "BOT_TOKEN", "123456:AAquickbrownfox")

    request = captured[0]
    assert request.get_method() == "PUT"
    assert request.full_url.endswith(f"/accounts/{ACCOUNT}/workers/scripts/my-bot/secrets")
    assert json.loads(request.data) == {
        "name": "BOT_TOKEN",
        "text": "123456:AAquickbrownfox",
        "type": "secret_text",
    }


def test_put_secret_failure_never_echoes_the_secret_value():
    """The message is printed to the terminal and pasted into bug reports."""
    client = CloudflareClient("token", account_id=ACCOUNT)
    payload = api_payload(success=False, errors=[{"code": 10021, "message": "binding rejected"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(payload)):
        with pytest.raises(DeploymentError) as exc_info:
            client.put_secret("my-bot", "BOT_TOKEN", "123456:AAquickbrownfox")

    assert "123456:AAquickbrownfox" not in str(exc_info.value)
    assert "AAquickbrownfox" not in repr(exc_info.value)


def test_delete_worker_issues_a_delete():
    client = CloudflareClient("token", account_id=ACCOUNT)
    captured = []

    with patch("urllib.request.urlopen", side_effect=fake_urlopen(api_payload(result={}), captured)):
        client.delete_worker("my-bot")

    request = captured[0]
    assert request.get_method() == "DELETE"
    assert f"/accounts/{ACCOUNT}/workers/scripts/my-bot" in request.full_url


# --------------------------------------------------------------------------- #
# Credential storage
# --------------------------------------------------------------------------- #

def test_credentials_survive_a_save_and_load_round_trip(tmp_path):
    with isolated_credentials(tmp_path):
        save_credentials("personal", "cf-token-abc", "acc-1")
        stored = load_credentials("personal")
        assert stored["api_token"] == "cf-token-abc"
        assert stored["account_id"] == "acc-1"
        # A pasted token is recorded as such, so client_for knows not to try
        # refreshing it the way it refreshes an OAuth grant.
        assert stored["auth_type"] == "token"


def test_loading_an_account_that_was_never_saved_returns_none(tmp_path):
    with isolated_credentials(tmp_path):
        assert load_credentials("personal") is None
        save_credentials("personal", "cf-token-abc", "acc-1")
        assert load_credentials("work") is None


def test_forget_credentials_removes_only_the_named_account(tmp_path):
    with isolated_credentials(tmp_path):
        save_credentials("personal", "cf-token-abc", "acc-1")
        save_credentials("work", "cf-token-def", "acc-2")

        forget_credentials("personal")

        assert load_credentials("personal") is None
        assert load_credentials("work")["api_token"] == "cf-token-def"


def test_forgetting_an_unknown_account_is_a_no_op(tmp_path):
    with isolated_credentials(tmp_path) as credentials_file:
        save_credentials("personal", "cf-token-abc", "acc-1")
        before = credentials_file.read_bytes()

        forget_credentials("nope")

        assert credentials_file.read_bytes() == before
        assert load_credentials("personal")["api_token"] == "cf-token-abc"


def test_stored_account_labels_are_listed_sorted(tmp_path):
    with isolated_credentials(tmp_path):
        for label in ("work", "personal", "backup"):
            save_credentials(label, f"token-{label}", f"acc-{label}")

        assert stored_account_labels() == ["backup", "personal", "work"]


def test_stored_account_labels_is_empty_before_any_login(tmp_path):
    with isolated_credentials(tmp_path):
        assert stored_account_labels() == []


def test_a_corrupt_credentials_file_asks_the_user_to_log_in_again(tmp_path):
    with isolated_credentials(tmp_path) as credentials_file:
        credentials_file.write_bytes(b"not fernet ciphertext")
        with pytest.raises(DeploymentError, match="could not be decrypted"):
            load_credentials("personal")


def test_the_api_token_is_never_written_to_disk_in_the_clear(tmp_path):
    """The file sits in the user's home directory alongside backups and sync clients."""
    with isolated_credentials(tmp_path) as credentials_file:
        save_credentials("personal", "cf-token-abcdef123456", "acc-1")

        raw = credentials_file.read_bytes()
        assert b"cf-token-abcdef123456" not in raw
        assert b"personal" not in raw
        assert b"api_token" not in raw


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has no POSIX modes; os.chmod only toggles the read-only bit. "
           "Access is governed by the ACL that %USERPROFILE% already carries.",
)
def test_credentials_file_is_owner_only(tmp_path):
    with isolated_credentials(tmp_path) as credentials_file:
        save_credentials("personal", "cf-token-abc", "acc-1")
        assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600
