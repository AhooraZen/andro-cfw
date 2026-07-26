from __future__ import annotations

import secrets
import time
import urllib.error
import urllib.request
from importlib import resources
from typing import Optional

from . import oauth
from .cloudflare import (
    WORKER_MODULE_NAME,
    CloudflareClient,
    forget_credentials,
    load_credentials,
    save_credentials,
    update_credentials,
)
from .colors import log_dim, log_success, log_working
from .errors import DeploymentError

# How long to wait for a freshly enabled workers.dev hostname to start
# resolving. The API returns before DNS has propagated, so a deploy that is
# actually fine can look broken for a few seconds.
WORKERS_DEV_READY_TIMEOUT = 45
WORKERS_DEV_POLL_INTERVAL = 3


def _random_worker_name() -> str:
    return "andro-cfw-" + secrets.token_hex(4)


def _load_template(name: str) -> str:
    return resources.files("andro_cfw.templates").joinpath(name).read_text(encoding="utf-8")


def client_for(account_label: Optional[str]) -> CloudflareClient:
    """
    Build an API client from the stored credentials for `account_label`.

    `None` means the default single-account setup, stored under 'default'.
    """
    label = account_label or "default"
    creds = load_credentials(label)
    if not creds:
        raise DeploymentError(
            f"No Cloudflare credentials stored for '{label}'. "
            "Run `andro-cfw login` first."
        )

    # An OAuth access token is short lived. Refresh it here rather than at
    # every call site, so a long-running daemon never fails on an expiry.
    if oauth.needs_refresh(creds):
        creds = oauth.refresh(creds)
        update_credentials(label, creds)

    return CloudflareClient(creds["api_token"], creds.get("account_id"))


def login(api_token: str, account_label: Optional[str] = None,
          account_id: Optional[str] = None) -> str:
    """
    Verify an API token and store it encrypted. Returns the resolved account id.
    """
    label = account_label or "default"
    client = CloudflareClient(api_token, account_id)

    log_working("Verifying the Cloudflare API token...")
    client.verify_token()
    resolved_account_id = client.resolve_account_id()

    save_credentials(label, api_token, resolved_account_id)
    log_success(f"Cloudflare credentials stored for '{label}'.")
    return resolved_account_id


def browser_login(account_label: Optional[str] = None,
                  account_id: Optional[str] = None) -> str:
    """
    Log in through Cloudflare's own consent screen instead of a pasted token.

    The credential never leaves Cloudflare's domain in a form the user has to
    handle, and what is stored is a short-lived access token plus a refresh
    token rather than a permanent one.
    """
    label = account_label or "default"
    credentials = oauth.browser_login()

    client = CloudflareClient(credentials["api_token"], account_id)
    resolved_account_id = client.resolve_account_id()
    credentials["account_id"] = resolved_account_id

    update_credentials(label, credentials)
    log_success(f"Logged in to Cloudflare as '{label}' via your browser.")
    return resolved_account_id


def logout(account_label: Optional[str] = None) -> bool:
    """Revoke an OAuth grant where possible and forget the stored credential."""
    label = account_label or "default"
    creds = load_credentials(label)
    if not creds:
        return False
    if creds.get("auth_type") == "oauth":
        oauth.revoke(creds)
    forget_credentials(label)
    log_success(f"Removed stored credentials for '{label}'.")
    return True


def _wait_until_live(worker_url: str) -> bool:
    """Poll the worker until its workers.dev hostname resolves and answers."""
    deadline = time.time() + WORKERS_DEV_READY_TIMEOUT
    while time.time() < deadline:
        try:
            request = urllib.request.Request(  # noqa: S310 - https workers.dev URL built above
                worker_url, headers={"User-Agent": "andro-cfw"}
            )
            with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 - https workers.dev URL built above
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError:
            return True   # it answered, which is all we needed to know
        except Exception:  # noqa: S110 - DNS not live yet is the expected case while polling
            pass
        time.sleep(WORKERS_DEV_POLL_INTERVAL)
    return False


def deploy_worker(
    worker_name: Optional[str] = None,
    account_label: Optional[str] = None,
) -> tuple:
    """
    Upload the proxy Worker and expose it on workers.dev.

    Returns (worker_name, worker_url).
    """
    client = client_for(account_label)
    worker_name = worker_name or _random_worker_name()

    label_note = f" (account: {account_label})" if account_label else ""
    log_working(f"Uploading Cloudflare Worker '{worker_name}'{label_note}...")
    client.upload_worker(worker_name, _load_template(WORKER_MODULE_NAME))

    log_working("Enabling the workers.dev route...")
    client.enable_workers_dev(worker_name)
    subdomain = client.workers_subdomain()
    worker_url = f"https://{worker_name}.{subdomain}.workers.dev"

    log_working("Waiting for the worker to come online...")
    if not _wait_until_live(worker_url):
        log_dim(
            "The worker was uploaded but is not answering yet. workers.dev DNS "
            "can take a minute on a brand-new subdomain -- run `andro-cfw check` shortly."
        )

    log_success(f"Worker deployed: {worker_url}")
    return worker_name, worker_url


def put_worker_secret(
    worker_name: str,
    key: str,
    value: str,
    account_label: Optional[str] = None,
) -> None:
    """Store `value` as an encrypted Cloudflare Worker secret named `key`."""
    client = client_for(account_label)
    try:
        client.put_secret(worker_name, key, value)
    except DeploymentError as exc:
        # Never surface the raw value; only the binding name is safe to print.
        raise DeploymentError(
            f"Failed to store the '{key}' secret on worker '{worker_name}'.\n{exc}"
        ) from None
    log_success(f"Stored '{key}' as an encrypted Cloudflare Worker secret.")


def teardown_worker(worker_name: str, account_label: Optional[str] = None) -> None:
    """Delete a previously deployed worker (used by `andro-cfw remove`)."""
    log_working(f"Deleting Cloudflare Worker '{worker_name}'...")
    try:
        client_for(account_label).delete_worker(worker_name)
    except DeploymentError as exc:
        # Removal is best effort: a worker deleted from the dashboard already,
        # or an expired token, must not block cleaning up the local session.
        log_dim(f"Could not delete '{worker_name}': {exc}")
