from __future__ import annotations

import functools
import sys
import warnings
from typing import Optional

from .session import CFWSession

# Frameworks that speak MTProto directly to Telegram's datacenters rather than
# the HTTP Bot API. An HTTP reverse proxy cannot route them, so patching them is
# impossible -- we warn instead of pretending it worked.
MTPROTO_FRAMEWORKS = ("pyrogram", "hydrogram", "telethon")

_DEFAULT_TELEGRAM_HOST = "api.telegram.org"


def _is_still_pointing_at_telegram(url: Optional[str]) -> bool:
    """True if `url` is unset or still targets Telegram's origin directly."""
    return url is None or _DEFAULT_TELEGRAM_HOST in url


def _patch_telebot(module, session: CFWSession) -> bool:
    """Point pyTelegramBotAPI's module-level API URLs at the proxy."""
    apihelper = getattr(module, "apihelper", None)
    if apihelper is None:
        return False

    apihelper.API_URL = session.telebot_api_url()
    apihelper.FILE_URL = session.telebot_file_url()

    # Long polling through an extra hop needs a read timeout longer than the
    # ~50s Telegram holds getUpdates open for, or the socket dies every cycle.
    if hasattr(apihelper, "READ_TIMEOUT"):
        apihelper.READ_TIMEOUT = 60
    return True


def _patch_aiogram(module, session: CFWSession) -> bool:
    """
    Redirect aiogram 3.x by mutating the shared ``PRODUCTION`` server object.

    ``BaseSession.__init__`` binds ``PRODUCTION`` as a default argument at
    import time, so replacing the module attribute would not affect sessions
    created later. Mutating the object itself does, and reaches every session
    that has not been given an explicit ``api=`` override.
    """
    telegram_mod = getattr(getattr(module, "client", None), "telegram", None)
    production = getattr(telegram_mod, "PRODUCTION", None)
    if production is None:
        return False

    urls = session.aiogram_server_url()
    # TelegramAPIServer is a frozen dataclass; object.__setattr__ bypasses that.
    object.__setattr__(production, "base", urls["base"])
    object.__setattr__(production, "file", urls["file"])
    return True


def _patch_ptb(module, session: CFWSession) -> bool:
    """
    Wrap ``telegram.Bot.__init__`` so any bot still aimed at api.telegram.org is
    redirected to the proxy.

    python-telegram-bot bakes its default base URL into the signature, and
    ``ApplicationBuilder`` always passes one explicitly, so there is no
    attribute to overwrite -- the constructor has to be intercepted. A URL the
    caller deliberately set to some other host is left alone.
    """
    bot_cls = getattr(module, "Bot", None)
    if bot_cls is None:
        return False
    if getattr(bot_cls, "_andro_cfw_patched", False):
        return True

    original_init = bot_cls.__init__
    base_url = session.ptb_base_url()
    base_file_url = session.ptb_base_file_url()

    @functools.wraps(original_init)
    def patched_init(self, *args, **kwargs):
        # Only rewrite when base_url/base_file_url came through as keywords;
        # a positional base_url would make injecting a keyword a TypeError.
        if len(args) <= 1:
            if _is_still_pointing_at_telegram(kwargs.get("base_url")):
                kwargs["base_url"] = base_url
            if _is_still_pointing_at_telegram(kwargs.get("base_file_url")):
                kwargs["base_file_url"] = base_file_url
        return original_init(self, *args, **kwargs)

    bot_cls.__init__ = patched_init
    bot_cls._andro_cfw_patched = True
    return True


_PATCHERS = {
    "telebot": _patch_telebot,
    "aiogram": _patch_aiogram,
    "telegram": _patch_ptb,
}


def patch(session: Optional[CFWSession] = None) -> CFWSession:
    """
    One-line auto-patcher for HTTP Bot API frameworks.

    Inspects ``sys.modules`` and redirects every already-imported supported
    framework (pyTelegramBotAPI, aiogram 3.x, python-telegram-bot) through the
    deployed Cloudflare Worker proxy. Import your framework *before* calling
    this.

    Frameworks that use MTProto (pyrogram, hydrogram, telethon) cannot be
    proxied by an HTTP Bot API reverse proxy; if one is imported, a
    ``RuntimeWarning`` is emitted rather than silently doing nothing.

    Returns the session that was applied.
    """
    if session is None:
        session = CFWSession.load()

    patched = []
    for name, patcher in _PATCHERS.items():
        module = sys.modules.get(name)
        if module is None:
            continue
        try:
            if patcher(module, session):
                patched.append(name)
        except Exception as exc:
            warnings.warn(
                f"andro-cfw could not patch '{name}': {exc}. "
                f"Configure the base URL manually -- see `andro-cfw snippet -f {name}`.",
                RuntimeWarning,
                stacklevel=2,
            )

    for name in MTPROTO_FRAMEWORKS:
        if name in sys.modules:
            warnings.warn(
                f"andro-cfw cannot proxy '{name}': it talks MTProto to Telegram's "
                "datacenters, not the HTTP Bot API, so a Cloudflare Worker proxy "
                f"has no effect. Use {name}'s own proxy setting (SOCKS5/MTProto) "
                "instead.",
                RuntimeWarning,
                stacklevel=2,
            )

    if not patched:
        warnings.warn(
            "andro-cfw.patch() found no supported framework in sys.modules. "
            "Import telebot, aiogram, or telegram BEFORE calling patch().",
            RuntimeWarning,
            stacklevel=2,
        )

    return session
