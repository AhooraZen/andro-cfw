"""
Browser login via Cloudflare's OAuth 2.0 authorization-code flow with PKCE.

Why this exists alongside API tokens: pasting a long-lived API token into a
third-party CLI asks the user for a lot of trust up front. The browser flow
keeps the credential exchange on Cloudflare's own domain, shows the user
exactly which scopes are being requested, and yields a short-lived access token
plus a refresh token rather than a permanent one.

Registering the OAuth client
----------------------------
andro-cfw ships no client id of its own. Register one at
https://developers.cloudflare.com/fundamentals/oauth/create-an-oauth-client/
as a public client using "Authorization Code with PKCE", with the redirect URI
below, then set ANDRO_CFW_OAUTH_CLIENT_ID (or edit OAUTH_CLIENT_ID here).

A note on why we do NOT reuse wrangler's client id, which is public and would
"just work": Cloudflare's consent screen names the application being authorised.
Borrowing wrangler's id would tell the user that *Wrangler* is requesting
access, and would file the grant under Wrangler in their list of authorised
applications. That is a worse trust story than asking for an API token, not a
better one, so it is not done here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Optional

from .colors import log_dim, log_step, log_working
from .errors import DeploymentError

AUTH_URL = "https://dash.cloudflare.com/oauth2/auth"
TOKEN_URL = "https://dash.cloudflare.com/oauth2/token"  # noqa: S105 - an endpoint, not a secret
REVOKE_URL = "https://dash.cloudflare.com/oauth2/revoke"

# Must exactly match the redirect URI registered on the OAuth client.
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8976
CALLBACK_PATH = "/oauth/callback"
CALLBACK_URL = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"

# Least privilege: enough to deploy a Worker, expose it on workers.dev, store
# its secrets, and identify the account. Deliberately no KV, R2, D1 or zone
# write scopes -- andro-cfw does not touch those.
SCOPES = (
    "account:read",
    "user:read",
    "workers:write",
    "workers_scripts:write",
    "workers_routes:write",
    "offline_access",
)

OAUTH_CLIENT_ID = ""   # set via ANDRO_CFW_OAUTH_CLIENT_ID or edit here

# Tokens are refreshed this many seconds before they actually expire, so a
# long-running daemon never uses one that dies mid-request.
REFRESH_SKEW_SECONDS = 120

LOGIN_TIMEOUT_SECONDS = 300


def client_id() -> Optional[str]:
    return (os.environ.get("ANDRO_CFW_OAUTH_CLIENT_ID") or OAUTH_CLIENT_ID).strip() or None


def is_available() -> bool:
    """Whether browser login can be offered at all."""
    return client_id() is not None


def _pkce_pair() -> tuple:
    """Return (verifier, challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot handler that captures the authorization code."""

    result: ClassVar[dict] = {}

    def log_message(self, fmt, *args):     # silence the default access log
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result = {k: v[0] for k, v in params.items()}

        if "error" in _CallbackHandler.result:
            body = b"andro-cfw: access was denied. You can close this tab."
        else:
            body = b"andro-cfw: login complete. You can close this tab."

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - TOKEN_URL/REVOKE_URL are literal https constants
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "andro-cfw",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 - literal https constant
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read()
    except urllib.error.URLError as exc:
        raise DeploymentError(f"Could not reach Cloudflare's OAuth endpoint ({exc.reason}).") from exc

    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except ValueError as exc:
        raise DeploymentError("Cloudflare's OAuth endpoint returned a non-JSON response.") from exc

    if "error" in data:
        description = data.get("error_description") or data["error"]
        raise DeploymentError(f"Cloudflare rejected the OAuth exchange: {description}")
    return data


def _expiry_from(payload: dict) -> float:
    return time.time() + float(payload.get("expires_in", 3600))


def browser_login(open_browser: bool = True) -> dict:
    """
    Run the full authorization-code + PKCE flow.

    Returns {"api_token", "refresh_token", "expires_at", "auth_type": "oauth"}.
    """
    configured_id = client_id()
    if not configured_id:
        raise DeploymentError(
            "Browser login is not configured: no OAuth client id.\n"
            "Register a public OAuth client with the redirect URI\n"
            f"  {CALLBACK_URL}\n"
            "at https://developers.cloudflare.com/fundamentals/oauth/create-an-oauth-client/\n"
            "then set ANDRO_CFW_OAUTH_CLIENT_ID.\n\n"
            "Until then, use an API token: `andro-cfw login`."
        )

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": configured_id,
        "redirect_uri": CALLBACK_URL,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    authorize_url = f"{AUTH_URL}?{query}"

    try:
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    except OSError as exc:
        raise DeploymentError(
            f"Could not listen on {CALLBACK_URL} ({exc}). The port is registered "
            "with the OAuth client and cannot be changed here -- close whatever "
            "is using it (another wrangler or andro-cfw login) and retry."
        ) from exc

    _CallbackHandler.result = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        log_step("Opening your browser to log in with Cloudflare...")
        log_dim(f"If it does not open, paste this into your browser:\n{authorize_url}")
        if open_browser:
            webbrowser.open(authorize_url)

        log_working("Waiting for you to authorise andro-cfw...")
        deadline = time.time() + LOGIN_TIMEOUT_SECONDS
        while not _CallbackHandler.result and time.time() < deadline:
            time.sleep(0.2)
        captured = dict(_CallbackHandler.result)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    if not captured:
        raise DeploymentError("Timed out waiting for the Cloudflare login to complete.")
    if "error" in captured:
        raise DeploymentError(
            f"Cloudflare login was denied: {captured.get('error_description', captured['error'])}"
        )
    # A mismatched state means the callback did not originate from the request
    # we started, so the code must not be exchanged.
    if not secrets.compare_digest(captured.get("state", ""), state):
        raise DeploymentError("OAuth state mismatch -- ignoring the callback.")
    if "code" not in captured:
        raise DeploymentError("Cloudflare's callback carried no authorization code.")

    payload = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": configured_id,
        "code": captured["code"],
        "redirect_uri": CALLBACK_URL,
        "code_verifier": verifier,
    })

    return {
        "auth_type": "oauth",
        "api_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": _expiry_from(payload),
    }


def refresh(credentials: dict) -> dict:
    """
    Exchange a refresh token for a fresh access token.

    Returns an updated copy of `credentials`.
    """
    configured_id = client_id()
    refresh_token = credentials.get("refresh_token")
    if not configured_id or not refresh_token:
        raise DeploymentError(
            "This OAuth login cannot be refreshed. Run `andro-cfw login --browser` again."
        )

    payload = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": configured_id,
        "refresh_token": refresh_token,
    })

    updated = dict(credentials)
    updated["api_token"] = payload["access_token"]
    updated["expires_at"] = _expiry_from(payload)
    # Cloudflare may rotate the refresh token; keep the old one if it does not.
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    return updated


def needs_refresh(credentials: dict, at: Optional[float] = None) -> bool:
    if credentials.get("auth_type") != "oauth":
        return False
    expires_at = credentials.get("expires_at")
    if not expires_at:
        return False
    return (at if at is not None else time.time()) >= expires_at - REFRESH_SKEW_SECONDS


def revoke(credentials: dict) -> None:
    """Best-effort revocation, so `andro-cfw logout` actually invalidates."""
    configured_id = client_id()
    token = credentials.get("refresh_token") or credentials.get("api_token")
    if not configured_id or not token:
        return
    try:
        _post_form(REVOKE_URL, {"client_id": configured_id, "token": token})
    except DeploymentError:
        # An already-expired token cannot be revoked, and that is fine.
        pass
