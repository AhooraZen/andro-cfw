"""
Tests for andro_cfw.patch().

These deliberately use real objects, not MagicMock, for anything an assertion
depends on. A MagicMock auto-creates every attribute you touch, so asserting
against one proves the test ran -- not that the patch did anything.
"""

import sys
import types
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from andro_cfw import CFWSession, WorkerEntry, patch

WORKER_URL = "https://test.workers.dev"


def make_session():
    return CFWSession(workers=[WorkerEntry("test-worker", WORKER_URL, "acc1")])


@pytest.fixture(autouse=True)
def _clean_modules(monkeypatch):
    """Ensure no framework leaks between tests via sys.modules."""
    for name in ("telebot", "aiogram", "telegram", "pyrogram", "hydrogram", "telethon"):
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_patch_telebot(monkeypatch):
    telebot = types.ModuleType("telebot")
    telebot.apihelper = types.SimpleNamespace(
        API_URL="https://api.telegram.org/bot{0}/{1}",
        FILE_URL="https://api.telegram.org/file/bot{0}/{1}",
        READ_TIMEOUT=25,
    )
    monkeypatch.setitem(sys.modules, "telebot", telebot)

    session = make_session()
    assert patch(session) is session

    assert telebot.apihelper.API_URL == f"{WORKER_URL}/bot{{0}}/{{1}}"
    assert telebot.apihelper.FILE_URL == f"{WORKER_URL}/file/bot{{0}}/{{1}}"
    assert telebot.apihelper.READ_TIMEOUT == 60


def test_patch_aiogram_mutates_shared_production_server(monkeypatch):
    """
    aiogram binds PRODUCTION as a default argument at import time, so the patch
    has to mutate that object in place. This reproduces the frozen dataclass
    aiogram actually ships.
    """

    @dataclass(frozen=True)
    class TelegramAPIServer:
        base: str
        file: str

    production = TelegramAPIServer(
        base="https://api.telegram.org/bot{token}/{method}",
        file="https://api.telegram.org/file/bot{token}/{path}",
    )
    # Hold a second reference the way aiogram's default argument does.
    default_arg_reference = production

    telegram_mod = types.ModuleType("aiogram.client.telegram")
    telegram_mod.PRODUCTION = production
    client_mod = types.ModuleType("aiogram.client")
    client_mod.telegram = telegram_mod
    aiogram = types.ModuleType("aiogram")
    aiogram.client = client_mod
    monkeypatch.setitem(sys.modules, "aiogram", aiogram)

    patch(make_session())

    assert default_arg_reference.base == f"{WORKER_URL}/bot{{token}}/{{method}}"
    assert default_arg_reference.file == f"{WORKER_URL}/file/bot{{token}}/{{path}}"


def test_patch_ptb_redirects_default_base_url(monkeypatch):
    """python-telegram-bot bakes its base URL into Bot.__init__'s signature."""
    recorded = {}

    class Bot:
        def __init__(self, token, base_url="https://api.telegram.org/bot",
                     base_file_url="https://api.telegram.org/file/bot"):
            recorded["base_url"] = base_url
            recorded["base_file_url"] = base_file_url

    telegram = types.ModuleType("telegram")
    telegram.Bot = Bot
    monkeypatch.setitem(sys.modules, "telegram", telegram)

    patch(make_session())

    # As ApplicationBuilder does: pass Telegram's own default explicitly.
    Bot("123:abc", base_url="https://api.telegram.org/bot",
        base_file_url="https://api.telegram.org/file/bot")
    assert recorded["base_url"] == f"{WORKER_URL}/bot"
    assert recorded["base_file_url"] == f"{WORKER_URL}/file/bot"

    # And when the caller supplies nothing at all.
    recorded.clear()
    Bot("123:abc")
    assert recorded["base_url"] == f"{WORKER_URL}/bot"


def test_patch_ptb_leaves_explicit_custom_url_alone(monkeypatch):
    recorded = {}

    class Bot:
        def __init__(self, token, base_url=None, base_file_url=None):
            recorded["base_url"] = base_url

    telegram = types.ModuleType("telegram")
    telegram.Bot = Bot
    monkeypatch.setitem(sys.modules, "telegram", telegram)

    patch(make_session())
    Bot("123:abc", base_url="https://my-own-bot-api.example.com/bot")
    assert recorded["base_url"] == "https://my-own-bot-api.example.com/bot"


def test_patch_ptb_is_idempotent(monkeypatch):
    """Calling patch() twice must not stack wrappers around Bot.__init__."""

    class Bot:
        def __init__(self, token, base_url=None):
            pass

    telegram = types.ModuleType("telegram")
    telegram.Bot = Bot
    monkeypatch.setitem(sys.modules, "telegram", telegram)

    patch(make_session())
    first = Bot.__init__
    patch(make_session())
    assert Bot.__init__ is first


@pytest.mark.parametrize("name", ["pyrogram", "hydrogram", "telethon"])
def test_patch_warns_for_mtproto_frameworks(monkeypatch, name):
    """
    MTProto clients cannot be routed through an HTTP Bot API proxy. Earlier
    versions silently set a meaningless attribute; the user must be told.
    """
    monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    with pytest.warns(RuntimeWarning, match="cannot proxy"):
        patch(make_session())


def test_patch_warns_when_no_framework_imported():
    with pytest.warns(RuntimeWarning, match="no supported framework"):
        patch(make_session())


def test_patch_survives_a_broken_framework_module(monkeypatch):
    """A framework that raises during patching must not kill the user's bot."""
    telebot = MagicMock()
    type(telebot).apihelper = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setitem(sys.modules, "telebot", telebot)

    session = make_session()
    with pytest.warns(RuntimeWarning):
        assert patch(session) is session
