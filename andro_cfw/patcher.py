from __future__ import annotations

import sys
from typing import Optional
from .session import CFWSession


def patch(session: Optional[CFWSession] = None) -> CFWSession:
    """
    Universal 1-line auto-patcher for Telegram bot frameworks.

    Inspects sys.modules and configures API base URLs for any imported
    framework (telebot, python-telegram-bot, aiogram, pyrogram, hydrogram)
    to route through the deployed Cloudflare Worker proxy.
    """
    if session is None:
        session = CFWSession.load()

    base_url = session.api_base_url()

    # 1. pyTelegramBotAPI (telebot)
    if "telebot" in sys.modules:
        tb = sys.modules["telebot"]
        tb.apihelper.API_URL = session.telebot_api_url()
        tb.apihelper.FILE_URL = session.telebot_file_url()
        if hasattr(tb.apihelper, "READ_TIMEOUT"):
            tb.apihelper.READ_TIMEOUT = 60
        if hasattr(tb.apihelper, "CUSTOM_REQUEST_TIMEOUT"):
            tb.apihelper.CUSTOM_REQUEST_TIMEOUT = (10, 60)

    # 2. Pyrogram
    if "pyrogram" in sys.modules:
        pyr = sys.modules["pyrogram"]
        if hasattr(pyr, "Client"):
            pyr.Client.api_url = base_url

    # 3. Hydrogram
    if "hydrogram" in sys.modules:
        hyd = sys.modules["hydrogram"]
        if hasattr(hyd, "Client"):
            hyd.Client.api_url = base_url

    # 4. aiogram (v2 & v3)
    if "aiogram" in sys.modules:
        aio = sys.modules["aiogram"]
        if hasattr(aio, "client") and hasattr(aio.client, "telegram") and hasattr(aio.client.telegram, "TelegramAPIServer"):
            aio.client.telegram.TelegramAPIServer.from_base(session.telebot_api_url())

    # 5. python-telegram-bot (telegram)
    if "telegram" in sys.modules:
        tg = sys.modules["telegram"]
        if hasattr(tg, "Bot") and hasattr(tg.Bot, "_base_url"):
            tg.Bot._base_url = base_url

    return session
