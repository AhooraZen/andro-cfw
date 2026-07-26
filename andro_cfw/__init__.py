"""
andro-cfw
~~~~~~~~~

Run Telegram bots from filtered/restricted countries (e.g. Iran) without a VPN,
by routing Bot API traffic through a Cloudflare Worker reverse proxy that YOU
own and deploy to YOUR OWN Cloudflare account.

Typical usage -- import your framework first, then patch it::

    import telebot
    from andro_cfw import patch

    patch()

    bot = telebot.TeleBot("<BOT_TOKEN>")
    bot.infinity_polling()

Or configure the URLs yourself::

    from andro_cfw import CFWSession

    session = CFWSession.load()
    telebot.apihelper.API_URL = session.telebot_api_url()
    telebot.apihelper.FILE_URL = session.telebot_file_url()

Run ``andro-cfw init`` once per project to authenticate with Cloudflare and
deploy the proxy worker.
"""

from importlib import metadata

from .errors import AndroCFWError, DeploymentError, SessionNotFoundError, ToolchainMissingError
from .patcher import patch
from .session import CFWSession, WorkerEntry

__all__ = [
    "AndroCFWError",
    "CFWSession",
    "DeploymentError",
    "SessionNotFoundError",
    "ToolchainMissingError",
    "WorkerEntry",
    "__version__",
    "patch",
]

try:
    # Single source of truth: the version declared in pyproject.toml. Keeping a
    # second literal here is how the v0.3.2 tag ended up shipping "0.3.0".
    __version__ = metadata.version("andro-cfw")
except metadata.PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+unknown"
