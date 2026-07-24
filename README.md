# andro-cfw

Run your Telegram bot from countries where Telegram is network-filtered
(e.g. Iran) **without a VPN on the server**, by routing Bot API traffic
through a Cloudflare Worker reverse proxy that **you** own and deploy to
**your own** Cloudflare account.

Cloudflare's edge network is reachable from these regions even when
`api.telegram.org` is not, so the worker acts as a transparent relay:
`your bot -> your Cloudflare Worker -> api.telegram.org`.

## How it works

1. `andro-cfw init` opens your browser and runs Cloudflare's official
   `wrangler login` OAuth flow. You never share a password with this
   library — Cloudflare authenticates you directly.
2. Once authorized, andro-cfw generates a small TypeScript Worker
   (a transparent proxy to `api.telegram.org`) and deploys it to your
   account with `wrangler deploy`.
3. The resulting worker URL is saved, **encrypted**, in a `cfw.session`
   file in your project directory (encryption key stored in
   `~/.andro_cfw/key`, outside your repo).
4. In your bot code, load the session and point your Telegram library
   (telebot, python-telegram-bot, aiogram, ...) at the worker URL instead
   of `api.telegram.org`. Everything else about your bot stays the same.

This works identically on your laptop and on a server. At `init` time,
andro-cfw automatically detects your OS (Windows / macOS / Linux + distro)
and installs Node.js for you if it's missing — see "Automatic Node.js
setup" below. Once deployed, your bot's Python runtime needs no Node.js
and no VPN at all.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

### Automatic Node.js setup

`andro-cfw init` needs Node.js/npx once, to run Cloudflare's official
`wrangler` CLI. You no longer need to install it yourself: andro-cfw
detects your platform and installs it automatically if missing.

| Platform               | Detection                 | Auto-install method                          |
|------------------------|----------------------------|-----------------------------------------------|
| Windows                | `platform.system()`         | `winget`, then `choco`, then `scoop`           |
| macOS                  | `platform.system()`         | `brew install node` (or MacPorts)              |
| Debian / Ubuntu        | `/etc/os-release` (`ID`)    | NodeSource LTS script, falls back to `apt-get` |
| Fedora / RHEL / CentOS | `/etc/os-release`           | `dnf` / `yum`                                  |
| Arch / Manjaro         | `/etc/os-release`           | `pacman`                                       |
| openSUSE               | `/etc/os-release`           | `zypper`                                       |
| Alpine                 | `/etc/os-release`           | `apk`                                          |

If no supported package manager is found (or install needs a password
`sudo` can't get non-interactively), andro-cfw prints exact manual install
commands for your detected system instead of failing silently.

## Quick start

```bash
cd your-bot-project/
andro-cfw init
```

This will:
- open your browser for Cloudflare login,
- deploy a worker named `andro-cfw-xxxxxxxx` (or `--name <custom-name>`),
- create `cfw.session` in the current directory.

### Using it with `pyTelegramBotAPI` (telebot)

```python
import telebot
from andro_cfw import CFWSession

session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Hello from behind the filter! 🎉")

bot.infinity_polling()
```

### Using it with `python-telegram-bot` (v20+)

```python
from telegram.ext import ApplicationBuilder, CommandHandler
from andro_cfw import CFWSession

session = CFWSession.load()

app = (
    ApplicationBuilder()
    .token("YOUR_BOT_TOKEN")
    .base_url(session.ptb_base_url())
    .base_file_url(session.ptb_base_file_url())
    .build()
)

async def start(update, context):
    await update.message.reply_text("Hello from behind the filter! 🎉")

app.add_handler(CommandHandler("start", start))
app.run_polling()
```

### Using it with `aiogram` (v3+)

```python
from aiogram import Bot
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from andro_cfw import CFWSession

session = CFWSession.load()
api_server = TelegramAPIServer(**session.aiogram_server_url())

bot = Bot(
    token="YOUR_BOT_TOKEN",
    session=AiohttpSession(api=api_server),
)
```

## Smart multi-account load balancing

Cloudflare's Workers **Free** plan caps you at **100,000 requests/day per
account**. For busy bots that's not always enough. andro-cfw can now
spread traffic across **several Cloudflare accounts**, each contributing
its own 100k/day quota, and automatically fail over the instant one
account's quota is hit — with zero code changes and zero downtime.

```bash
andro-cfw init --accounts 2
```

This will:
1. Open your browser **twice** (once per account) for Cloudflare login —
   log in with a **different** Cloudflare account each time. Each
   account's login is stored in its own isolated folder
   (`~/.andro_cfw/accounts/account-N`), so they never overwrite each other.
2. Deploy one worker per account.
3. Save all of them into a single `cfw.session`.

Your bot code stays **exactly the same**:

```python
session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
```

Under the hood, when a session has more than one account, `session.telebot_api_url()`
(and the `ptb_*`/`aiogram_*` equivalents) point at a tiny **local**
load-balancing proxy that andro-cfw starts automatically, in-process,
the first time you access it. That proxy:

- forwards every request to the currently active Cloudflare account's worker,
- **instantly** detects an HTTP 429 / Cloudflare rate-limit response (this
  is how Cloudflare signals "daily quota exceeded"),
- transparently retries the same request on the next account with zero
  failed requests visible to your bot,
- marks the exhausted account as unusable until the next **UTC midnight**
  (Cloudflare's daily reset), and automatically starts using it again the
  moment that time passes — always preferring to fall back to account #1
  first once it's available again,
- persists all of this (which account is exhausted, until when, which one
  is active) back into the encrypted `cfw.session`, so it survives bot
  restarts too.

Add more accounts later without redeploying everything:

```bash
andro-cfw add-account
```

Check the health/rotation state of all accounts at any time:

```bash
andro-cfw status
```

## CLI reference

| Command                        | Description                                                          |
|----------------------------------|------------------------------------------------------------------------|
| `andro-cfw init`                 | Log into Cloudflare and deploy a single proxy worker.                  |
| `andro-cfw init --accounts 3`    | Log into 3 Cloudflare accounts and deploy a load-balanced worker pool. |
| `andro-cfw init --name foo`      | Deploy with a custom worker name (suffixed `-1`, `-2`... per account). |
| `andro-cfw init --force`         | Redeploy and overwrite an existing `cfw.session`.                      |
| `andro-cfw add-account`          | Add one more Cloudflare account/worker to an existing session.        |
| `andro-cfw status`               | Show worker(s), and for multi-account mode, each account's state.     |
| `andro-cfw remove`               | Delete all deployed worker(s) and the local `cfw.session`.             |

## Security notes

- `cfw.session` is encrypted with Fernet (AES128-CBC + HMAC). The key is
  stored in `~/.andro_cfw/key`, **not** inside the project, so committing
  `cfw.session` to git by accident does not by itself expose your worker
  URL to someone without the key. Still, **add `cfw.session` to
  `.gitignore`** — treat it like any other credential file.
- The generated worker is a pure pass-through proxy: it does not log,
  store, or inspect bot tokens, updates, or file contents.
- andro-cfw never asks for or stores your Cloudflare password — all
  authentication is delegated to Cloudflare's own `wrangler login` OAuth
  flow.
- You are deploying to **your own** Cloudflare account (free tier is
  sufficient for most bots), so you retain full control and can delete
  the worker at any time with `andro-cfw remove`.

## Requirements

- Python 3.9+
- Node.js — installed **automatically** by andro-cfw if missing (only
  needed for `andro-cfw init` / `add-account` / `remove`)
- One free [Cloudflare](https://dash.cloudflare.com/sign-up) account
  (or several, for load balancing)

## Changelog

### 0.2.0
- **Automatic Node.js setup**: andro-cfw detects your OS (Windows/macOS/
  Linux + distro) and package manager, and installs Node.js/npx for you
  if it's missing, instead of just erroring out.
- **Smart multi-account load balancing**: `andro-cfw init --accounts N`
  and `andro-cfw add-account` let you pool several Cloudflare accounts'
  free-tier quotas. A local in-process proxy auto-detects daily quota
  exhaustion (HTTP 429) per account, fails over instantly, and resumes
  the exhausted account automatically after Cloudflare's daily UTC reset.
- `andro-cfw status` now reports per-account health/rotation state.
- Fully backward compatible: existing single-worker `cfw.session` files
  and code using `session.worker_name` / `session.worker_url` keep working
  unchanged.

### 0.1.0
- Initial release.

## License

MIT