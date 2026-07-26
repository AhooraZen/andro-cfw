"""
Guards on the worker template that ships to every user's Cloudflare account.

These are string checks, not a JS test suite -- but each one pins a property
that regressed at least once, so a plain "does the file parse" assertion is
not enough.
"""

import re

import pytest

from andro_cfw.cloudflare import WORKER_MODULE_NAME
from andro_cfw.deploy import _load_template


@pytest.fixture(scope="module")
def worker() -> str:
    return _load_template("worker.mjs")


def test_worker_template_structure(worker):
    assert "export default {" in worker
    assert "async fetch(" in worker
    assert "https://api.telegram.org" in worker


def test_webhook_requires_the_secret_header(worker):
    """
    Telegram echoes setWebhook(secret_token=...) in this header. Without the
    check, anyone who learns the worker URL can POST fabricated updates.
    """
    assert "X-Telegram-Bot-Api-Secret-Token" in worker
    assert "WEBHOOK_SECRET" in worker
    assert "secretsMatch" in worker


def test_bot_token_is_never_read_from_the_request(worker):
    """
    The token must come from an encrypted Worker secret, never from the URL --
    a token in a query string is stored by Telegram, replayed on every update,
    and lands in every intermediate access log.
    """
    assert 'searchParams.get("token")' not in worker
    assert "url.pathname.split" not in worker


def test_cors_is_opt_in(worker):
    """
    A blanket Access-Control-Allow-Origin: * turns the worker into a general
    purpose CORS bypass for the whole Bot API.
    """
    assert "ALLOWED_ORIGINS" in worker
    assert '"Access-Control-Allow-Origin": "*"' not in worker
    assert '"Access-Control-Allow-Headers": "*"' not in worker


def test_webhook_path_is_matched_exactly(worker):
    """
    `pathname.includes("/webhook")` also swallows proxied Bot API calls whose
    path happens to contain the word.
    """
    assert 'url.pathname === "/webhook"' in worker
    assert 'pathname.includes("/webhook")' not in worker


def test_no_hardcoded_demo_bot(worker):
    """The template is a proxy, not a novelty bot shipped to every deployment."""
    for leftover in ("I'm Useless", "Pong!", "/echo ", "Cloudflare Anycast POP"):
        assert leftover not in worker, f"demo bot leftover in worker.mjs: {leftover}"


def test_hop_by_hop_headers_are_not_relayed(worker):
    assert "HOP_BY_HOP" in worker
    assert "transfer-encoding" in worker


def test_upstream_origin_is_configurable(worker):
    """
    DIR-04: allow pointing the proxy at a self-hosted telegram-bot-api server
    instead of api.telegram.org.
    """
    assert "UPSTREAM_API_ORIGIN" in worker
    assert "function upstreamOrigin(" in worker
    assert "upstreamOrigin(env)" in worker


def test_upstream_origin_falls_back_on_bad_input(worker):
    """A typo in the setting must not send traffic somewhere unexpected."""
    assert "DEFAULT_TELEGRAM_ORIGIN" in worker
    assert 'parsed.protocol !== "https:"' in worker
    assert "parsed.origin" in worker


# --------------------------------------------------------------------------- #
# Valid for direct upload to the Cloudflare API
# --------------------------------------------------------------------------- #

def test_worker_template_has_no_typescript_only_syntax(worker):
    """
    The template is uploaded verbatim -- there is no bundler and no type
    stripper on that path -- so TypeScript syntax does not fail a build here,
    it fails at runtime in every user's deployed worker.
    """
    for token in ("export interface", ": Promise<", "as any", "@ts-ignore"):
        assert token not in worker, f"TypeScript-only syntax in worker.mjs: {token}"

    assert "async fetch(request, env)" in worker
    assert re.search(r"async fetch\([^)]*:", worker) is None


def test_worker_template_is_an_es_module(worker):
    """
    upload_worker declares a main_module, which only accepts the ES module
    format; the older service-worker style would be rejected.
    """
    assert "export default {" in worker
    assert "module.exports" not in worker
    assert 'addEventListener("fetch"' not in worker


def test_worker_template_filename_matches_the_uploaded_module_name(worker):
    """
    The multipart part name, the metadata main_module and the file on disk all
    have to agree, or the upload succeeds with no entry point.
    """
    assert _load_template(WORKER_MODULE_NAME) == worker
