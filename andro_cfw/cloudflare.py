"""
Direct Cloudflare REST API client.

This replaces the previous approach of shelling out to `npx wrangler`, which
forced andro-cfw to install Node.js on the user's machine -- on Linux via the
system package manager, under sudo. Deploying a Worker is a handful of ordinary
HTTPS calls, so none of that is necessary.

Authentication uses a Cloudflare API token, which the user creates once at
https://dash.cloudflare.com/profile/api-tokens using the "Edit Cloudflare
Workers" template. Tokens are stored encrypted alongside the session key.
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
import uuid
from typing import Optional

from .errors import DeploymentError
from .session import _OWNER_ONLY_FILE, KEY_DIR, _ensure_key, _restrict

API_ROOT = "https://api.cloudflare.com/client/v4"

CREDENTIALS_FILE = KEY_DIR / "credentials"

# Matches the compatibility_date the worker template is written against.
WORKER_COMPATIBILITY_DATE = "2024-11-01"

# The API takes a plain ES module; there is no bundler in this path, so the
# uploaded file must already be valid JavaScript.
WORKER_MODULE_NAME = "worker.mjs"

TOKEN_HELP = (
    "Create one at https://dash.cloudflare.com/profile/api-tokens\n"  # noqa: S105 - guidance text, not a credential
    "  -> Create Token -> use the 'Edit Cloudflare Workers' template.\n"
    "That template grants exactly what andro-cfw needs: Workers Scripts:Edit."
)


# --------------------------------------------------------------------------- #
# Credential storage
# --------------------------------------------------------------------------- #

def _read_credentials() -> dict:
    """Decrypt the stored per-account API tokens. Missing file means empty."""
    if not CREDENTIALS_FILE.exists():
        return {}
    from cryptography.fernet import Fernet, InvalidToken

    try:
        raw = Fernet(_ensure_key()).decrypt(CREDENTIALS_FILE.read_bytes())
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise DeploymentError(
            f"'{CREDENTIALS_FILE}' could not be decrypted. It was probably created "
            "on a different machine or user. Delete it and run `andro-cfw login` again."
        ) from exc
    return data if isinstance(data, dict) else {}


def _write_credentials(data: dict) -> None:
    from cryptography.fernet import Fernet

    KEY_DIR.mkdir(parents=True, exist_ok=True)
    token = Fernet(_ensure_key()).encrypt(json.dumps(data).encode("utf-8"))
    CREDENTIALS_FILE.write_bytes(token)
    _restrict(CREDENTIALS_FILE, _OWNER_ONLY_FILE)


def save_credentials(account_label: str, api_token: str, account_id: str) -> None:
    """Persist one account's API token, encrypted with the local key."""
    data = _read_credentials()
    data[account_label] = {"api_token": api_token, "account_id": account_id}
    _write_credentials(data)


def load_credentials(account_label: str) -> Optional[dict]:
    return _read_credentials().get(account_label)


def forget_credentials(account_label: str) -> None:
    data = _read_credentials()
    if data.pop(account_label, None) is not None:
        _write_credentials(data)


def stored_account_labels() -> list:
    return sorted(_read_credentials())


# --------------------------------------------------------------------------- #
# Multipart encoding
# --------------------------------------------------------------------------- #

def _encode_multipart(fields: dict, files: dict) -> tuple:
    """
    Build a multipart/form-data body.

    `fields` maps name -> (content_type, text). `files` maps name ->
    (filename, content_type, text). Returns (content_type_header, body_bytes).

    Hand-rolled because the package has no HTTP dependency and pulling one in
    for a single upload call is not worth it.
    """
    boundary = f"----andro-cfw-{uuid.UUID(bytes=secrets.token_bytes(16)).hex}"
    out = bytearray()

    for name, (content_type, text) in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n'.encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += text.encode("utf-8") + b"\r\n"

    for name, (filename, content_type, text) in files.items():
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += text.encode("utf-8") + b"\r\n"

    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #

class CloudflareClient:
    """
    Minimal Cloudflare Workers API client.

    Only the endpoints andro-cfw actually uses are implemented; this is not a
    general-purpose SDK.
    """

    def __init__(self, api_token: str, account_id: Optional[str] = None, timeout: int = 30):
        self.api_token = api_token
        self.account_id = account_id
        self.timeout = timeout

    # ---------------------------------------------------------------- #
    # Transport
    # ---------------------------------------------------------------- #

    def _request(self, method: str, path: str, *, body=None, content_type=None, raw_result=False):
        url = API_ROOT + path
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "User-Agent": "andro-cfw",
        }
        if content_type:
            headers["Content-Type"] = content_type

        request = urllib.request.Request(  # noqa: S310 - API_ROOT is a literal https URL
            url, data=body, method=method, headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310 - API_ROOT is a literal https URL
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            payload = exc.read()
        except urllib.error.URLError as exc:
            raise DeploymentError(
                f"Could not reach the Cloudflare API ({exc.reason}). "
                "Check your internet connection -- note that api.cloudflare.com "
                "itself is not usually filtered, unlike api.telegram.org."
            ) from exc

        try:
            data = json.loads(payload.decode("utf-8", "replace"))
        except ValueError as exc:
            raise DeploymentError("Cloudflare returned a response that was not JSON.") from exc

        if not data.get("success", False):
            raise DeploymentError(self._describe_errors(data))
        return data if raw_result else data.get("result")

    @staticmethod
    def _describe_errors(data: dict) -> str:
        errors = data.get("errors") or []
        if not errors:
            return "Cloudflare rejected the request but reported no reason."

        lines = []
        for err in errors:
            code = err.get("code")
            message = err.get("message", "unknown error")
            lines.append(f"  [{code}] {message}" if code else f"  {message}")

        hint = ""
        codes = {err.get("code") for err in errors}
        if 10000 in codes or 9109 in codes:
            hint = (
                "\n\nThis usually means the API token is invalid or lacks the "
                "Workers Scripts:Edit permission.\n" + TOKEN_HELP
            )
        return "Cloudflare API error:\n" + "\n".join(lines) + hint

    # ---------------------------------------------------------------- #
    # Account discovery
    # ---------------------------------------------------------------- #

    def verify_token(self) -> dict:
        """Confirm the token is live. Raises DeploymentError if it is not."""
        return self._request("GET", "/user/tokens/verify")

    def list_accounts(self) -> list:
        result = self._request("GET", "/accounts")
        return result if isinstance(result, list) else []

    def resolve_account_id(self) -> str:
        """
        Determine which Cloudflare account to deploy into.

        A token scoped to a single account is the normal case, so that account
        is chosen automatically; ambiguity is reported rather than guessed.
        """
        if self.account_id:
            return self.account_id

        accounts = self.list_accounts()
        if not accounts:
            raise DeploymentError(
                "This API token can't see any Cloudflare account. It is probably "
                "scoped too narrowly.\n" + TOKEN_HELP
            )
        if len(accounts) > 1:
            listed = "\n".join(f"  {a.get('id')}  {a.get('name')}" for a in accounts)
            raise DeploymentError(
                "This token has access to several Cloudflare accounts. "
                f"Pass --account-id to choose one:\n{listed}"
            )
        self.account_id = accounts[0]["id"]
        return self.account_id

    def workers_subdomain(self) -> str:
        """The account's *.workers.dev subdomain, e.g. 'my-name'."""
        account_id = self.resolve_account_id()
        result = self._request("GET", f"/accounts/{account_id}/workers/subdomain") or {}
        subdomain = result.get("subdomain")
        if not subdomain:
            raise DeploymentError(
                "This Cloudflare account has no workers.dev subdomain yet. "
                "Open https://dash.cloudflare.com -> Workers & Pages once to "
                "claim one, then run this command again."
            )
        return subdomain

    # ---------------------------------------------------------------- #
    # Worker lifecycle
    # ---------------------------------------------------------------- #

    def upload_worker(self, script_name: str, module_source: str) -> None:
        """
        Upload (or replace) a Worker in the ES-module format.

        The metadata carries `keep_bindings: ["secret_text"]`, which preserves
        already-stored secrets: without it, a re-upload silently wipes
        BOT_TOKEN and WEBHOOK_SECRET.
        """
        account_id = self.resolve_account_id()
        metadata = json.dumps({
            "main_module": WORKER_MODULE_NAME,
            "compatibility_date": WORKER_COMPATIBILITY_DATE,
            "keep_bindings": ["secret_text"],
        })
        content_type, body = _encode_multipart(
            fields={"metadata": ("application/json", metadata)},
            files={
                WORKER_MODULE_NAME: (
                    WORKER_MODULE_NAME,
                    "application/javascript+module",
                    module_source,
                )
            },
        )
        self._request(
            "PUT",
            f"/accounts/{account_id}/workers/scripts/{script_name}",
            body=body,
            content_type=content_type,
        )

    def enable_workers_dev(self, script_name: str) -> None:
        """Expose the Worker on <script>.<subdomain>.workers.dev."""
        account_id = self.resolve_account_id()
        self._request(
            "POST",
            f"/accounts/{account_id}/workers/scripts/{script_name}/subdomain",
            body=json.dumps({"enabled": True}).encode("utf-8"),
            content_type="application/json",
        )

    def put_secret(self, script_name: str, name: str, value: str) -> None:
        """Store an encrypted secret binding on the Worker."""
        account_id = self.resolve_account_id()
        self._request(
            "PUT",
            f"/accounts/{account_id}/workers/scripts/{script_name}/secrets",
            body=json.dumps({"name": name, "text": value, "type": "secret_text"}).encode("utf-8"),
            content_type="application/json",
        )

    def delete_worker(self, script_name: str) -> None:
        account_id = self.resolve_account_id()
        self._request(
            "DELETE",
            f"/accounts/{account_id}/workers/scripts/{script_name}?force=true",
        )
