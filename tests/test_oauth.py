"""
Tests for the browser login flow.

Nothing here touches the network or a browser: the callback is driven by
posting to the local server the flow itself opens, which is the only way to
exercise the state check and the code exchange honestly.
"""

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import pytest

from andro_cfw import oauth
from andro_cfw.errors import DeploymentError

CLIENT_ID = "test-client-id"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ANDRO_CFW_OAUTH_CLIENT_ID", CLIENT_ID)


def token_payload(**overrides):
    payload = {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    payload.update(overrides)
    return payload


def drive_callback(params: dict, delay: float = 0.05):
    """Hit the flow's local callback server once it is listening."""
    def run():
        time.sleep(delay)
        url = f"{oauth.CALLBACK_URL}?{urllib.parse.urlencode(params)}"
        for _ in range(50):
            try:
                urllib.request.urlopen(url, timeout=2).read()  # noqa: S310 - localhost callback
                return
            except urllib.error.URLError:
                time.sleep(0.05)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def test_browser_login_is_unavailable_without_a_client_id(monkeypatch):
    """
    andro-cfw ships no client id. Rather than borrowing wrangler's — which would
    put "Wrangler" on the user's consent screen — the flow refuses and points at
    the token path.
    """
    monkeypatch.delenv("ANDRO_CFW_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setattr(oauth, "OAUTH_CLIENT_ID", "")

    assert oauth.is_available() is False
    with pytest.raises(DeploymentError, match="andro-cfw login"):
        oauth.browser_login(open_browser=False)


def test_client_id_comes_from_the_environment(configured):
    assert oauth.client_id() == CLIENT_ID
    assert oauth.is_available() is True


def test_wranglers_client_id_is_not_embedded():
    """Guard against someone 'fixing' the setup friction by pasting it in."""
    from pathlib import Path

    source = Path(oauth.__file__).read_text(encoding="utf-8")
    assert "54d11594-84e4-41aa-b438-e81b8fa78ee7" not in source


# --------------------------------------------------------------------------- #
# PKCE
# --------------------------------------------------------------------------- #

def test_pkce_challenge_is_the_s256_of_the_verifier():
    """A wrong transform is accepted at authorize time and fails at exchange."""
    verifier, challenge = oauth._pkce_pair()

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected
    assert "=" not in challenge
    assert 43 <= len(verifier) <= 128


def test_pkce_pairs_are_unique():
    assert len({oauth._pkce_pair()[0] for _ in range(20)}) == 20


# --------------------------------------------------------------------------- #
# The flow
# --------------------------------------------------------------------------- #

def test_successful_login_exchanges_the_code_and_returns_a_refreshable_grant(configured):
    captured = {}

    def fake_post(url, fields):
        captured["url"] = url
        captured["fields"] = fields
        return token_payload()

    with patch.object(oauth, "_post_form", side_effect=fake_post), \
         patch.object(oauth.webbrowser, "open") as opened:
        # The state is generated inside browser_login, so the callback has to be
        # driven with whatever value it put in the URL it tried to open.
        result = _login_with_state_echo(opened)

    assert result["auth_type"] == "oauth"
    assert result["api_token"] == "access-1"
    assert result["refresh_token"] == "refresh-1"
    assert result["expires_at"] > time.time()

    assert captured["url"] == oauth.TOKEN_URL
    assert captured["fields"]["grant_type"] == "authorization_code"
    assert captured["fields"]["code"] == "the-code"
    assert captured["fields"]["client_id"] == CLIENT_ID
    assert captured["fields"]["redirect_uri"] == oauth.CALLBACK_URL
    assert captured["fields"]["code_verifier"]


def _login_with_state_echo(opened_mock):
    """
    Run browser_login, echoing back whatever state it generated.

    browser_login opens the authorize URL; we read the state out of it and
    complete the callback with the same value, which is what a real browser
    redirect does.
    """
    result_box = {}

    def run():
        result_box["value"] = oauth.browser_login(open_browser=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    for _ in range(100):
        if opened_mock.call_args:
            break
        time.sleep(0.05)

    url = opened_mock.call_args.args[0]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    for _ in range(100):
        try:
            urllib.request.urlopen(  # noqa: S310 - localhost callback
                f"{oauth.CALLBACK_URL}?{urllib.parse.urlencode({'code': 'the-code', 'state': state})}",
                timeout=2,
            ).read()
            break
        except urllib.error.URLError:
            time.sleep(0.05)

    thread.join(timeout=10)
    return result_box["value"]


def test_authorize_url_carries_pkce_and_least_privilege_scopes(configured):
    with patch.object(oauth, "_post_form", return_value=token_payload()), \
         patch.object(oauth.webbrowser, "open") as opened:
        _login_with_state_echo(opened)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(opened.call_args.args[0]).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [oauth.CALLBACK_URL]
    assert query["client_id"] == [CLIENT_ID]

    scopes = query["scope"][0].split()
    assert "workers_scripts:write" in scopes
    assert "offline_access" in scopes
    # andro-cfw touches none of these; asking for them would be over-reach.
    for over_reach in ("workers_kv:write", "zone:read", "ssl_certs:write", "d1:write"):
        assert over_reach not in scopes


def test_a_mismatched_state_is_refused(configured):
    """
    The state ties the callback to the request we started. Without this check a
    third party could feed us an authorization code of their choosing.
    """
    with patch.object(oauth, "_post_form") as exchange, \
         patch.object(oauth.webbrowser, "open"), \
         patch.object(oauth, "LOGIN_TIMEOUT_SECONDS", 5):
        drive_callback({"code": "attacker-code", "state": "not-the-real-state"})
        with pytest.raises(DeploymentError, match="state mismatch"):
            oauth.browser_login(open_browser=False)

    exchange.assert_not_called()


def test_denied_consent_is_reported(configured):
    with patch.object(oauth, "_post_form") as exchange, \
         patch.object(oauth.webbrowser, "open"), \
         patch.object(oauth, "LOGIN_TIMEOUT_SECONDS", 5):
        drive_callback({"error": "access_denied", "error_description": "user said no"})
        with pytest.raises(DeploymentError, match="user said no"):
            oauth.browser_login(open_browser=False)

    exchange.assert_not_called()


def test_login_times_out_instead_of_hanging_forever(configured):
    with patch.object(oauth.webbrowser, "open"), \
         patch.object(oauth, "LOGIN_TIMEOUT_SECONDS", 0.3):
        with pytest.raises(DeploymentError, match="Timed out"):
            oauth.browser_login(open_browser=False)


def test_the_callback_port_is_released_after_a_failed_login(configured):
    """Otherwise a single denied login would block every later attempt."""
    with patch.object(oauth.webbrowser, "open"), \
         patch.object(oauth, "LOGIN_TIMEOUT_SECONDS", 0.3):
        for _ in range(2):
            with pytest.raises(DeploymentError):
                oauth.browser_login(open_browser=False)


# --------------------------------------------------------------------------- #
# Refresh
# --------------------------------------------------------------------------- #

def test_needs_refresh_only_applies_to_oauth_grants():
    assert oauth.needs_refresh({"auth_type": "token", "api_token": "x"}) is False
    assert oauth.needs_refresh({"auth_type": "oauth"}) is False


def test_needs_refresh_fires_before_the_token_actually_expires():
    """
    A token that expires mid-request fails the request. The skew means the
    daemon renews while the old one is still valid.
    """
    now = time.time()
    creds = {"auth_type": "oauth", "expires_at": now + oauth.REFRESH_SKEW_SECONDS - 1}
    assert oauth.needs_refresh(creds, at=now) is True

    creds = {"auth_type": "oauth", "expires_at": now + oauth.REFRESH_SKEW_SECONDS + 60}
    assert oauth.needs_refresh(creds, at=now) is False


def test_refresh_swaps_the_access_token_and_keeps_the_account(configured):
    creds = {
        "auth_type": "oauth",
        "api_token": "old-access",
        "refresh_token": "refresh-1",
        "account_id": "acc-123",
        "expires_at": 0,
    }
    with patch.object(oauth, "_post_form", return_value=token_payload(access_token="new-access")) as post:
        updated = oauth.refresh(creds)

    assert post.call_args.args[1]["grant_type"] == "refresh_token"
    assert updated["api_token"] == "new-access"
    assert updated["account_id"] == "acc-123"
    assert updated["expires_at"] > time.time()
    assert creds["api_token"] == "old-access"   # input not mutated


def test_refresh_keeps_the_old_refresh_token_when_none_is_returned(configured):
    """Cloudflare may or may not rotate it; dropping it would break the next renewal."""
    creds = {"auth_type": "oauth", "api_token": "a", "refresh_token": "refresh-1"}
    payload = token_payload()
    payload.pop("refresh_token")

    with patch.object(oauth, "_post_form", return_value=payload):
        updated = oauth.refresh(creds)

    assert updated["refresh_token"] == "refresh-1"


def test_refresh_without_a_refresh_token_asks_for_a_new_login(configured):
    with pytest.raises(DeploymentError, match="login --browser"):
        oauth.refresh({"auth_type": "oauth", "api_token": "a"})


# --------------------------------------------------------------------------- #
# Transport & revocation
# --------------------------------------------------------------------------- #

def test_oauth_errors_are_surfaced_with_their_description():
    class FakeResponse:
        def read(self):
            return json.dumps({
                "error": "invalid_grant",
                "error_description": "code already used",
            }).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        with pytest.raises(DeploymentError, match="code already used"):
            oauth._post_form(oauth.TOKEN_URL, {"grant_type": "refresh_token"})


def test_revoke_is_best_effort(configured):
    """A already-dead token cannot be revoked, and logout must not fail on it."""
    with patch.object(oauth, "_post_form", side_effect=DeploymentError("gone")):
        oauth.revoke({"auth_type": "oauth", "refresh_token": "r"})   # must not raise


def test_revoke_does_nothing_without_a_configured_client(monkeypatch):
    monkeypatch.delenv("ANDRO_CFW_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setattr(oauth, "OAUTH_CLIENT_ID", "")
    with patch.object(oauth, "_post_form") as post:
        oauth.revoke({"auth_type": "oauth", "refresh_token": "r"})
    post.assert_not_called()
