"""
andro-cfw
~~~~~~~~~

Run Telegram bots from filtered/restricted countries (e.g. Iran) without a VPN,
by routing Bot API traffic through a Cloudflare Worker reverse proxy that YOU
own and deploy to YOUR OWN Cloudflare account.

Typical usage::

    from andro_cfw import CFWSession

    session = CFWSession.load()

    import telebot
    telebot.apihelper.API_URL = session.telebot_api_url()
    telebot.apihelper.FILE_URL = session.telebot_file_url()

    bot = telebot.TeleBot("<BOT_TOKEN>")
    bot.infinity_polling()

Run ``andro-cfw init`` once per project to authenticate with Cloudflare and
deploy the proxy worker.
"""

from .session import CFWSession, WorkerEntry
from .errors import AndroCFWError, SessionNotFoundError, DeploymentError, ToolchainMissingError

__all__ = [
    "CFWSession",
    "WorkerEntry",
    "AndroCFWError",
    "SessionNotFoundError",
    "DeploymentError",
    "ToolchainMissingError",
]

__version__ = "0.2.1"
