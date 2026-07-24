# andro-cfw

[![PyPI](https://img.shields.io/pypi/v/andro-cfw?color=blue)](https://pypi.org/project/andro-cfw/)
[![Python](https://img.shields.io/pypi/pyversions/andro-cfw)](https://pypi.org/project/andro-cfw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/readme-EN%20%7C%20FA-blue)](README.md)

> **English** | [فارسی](README.fa.md)

---

## 🎯 What does this library do?

In countries like Iran where `api.telegram.org` is network-filtered, developers need a VPN or a foreign server to run their Telegram bots.

**andro-cfw** solves this with a simple trick: it deploys a Cloudflare Worker as a reverse proxy between your bot and Telegram:

```
Your Python bot  ←→  Cloudflare Worker (unfiltered)  ←→  api.telegram.org
```

Cloudflare's edge network is reachable from these regions even when Telegram's API is not, so your bot talks to the Worker and the Worker talks to Telegram. Simple as that.

---

## ✨ Features

- **No VPN** — not on your dev machine, not on your server
- **You own the worker** — deployed to YOUR Cloudflare account, full control
- **Secure auth** — uses Cloudflare's official OAuth (`wrangler login`), your password never touches this library
- **Encrypted session** — `cfw.session` is encrypted with Fernet (AES-128 + HMAC), key stored separately in `~/.andro_cfw/key`
- **Multi-library support** — telebot, python-telegram-bot, aiogram
- **No monkey-patching** — just swap the API URL, everything else stays normal
- **Zero-setup Node.js** *(new in 0.2.0)* — andro-cfw detects your OS/distro and installs Node.js automatically if it's missing
- **Smart multi-account load balancing** *(new in 0.2.0)* — pool several Cloudflare accounts' free-tier quotas, with automatic instant failover and daily auto-reset

---

## 📦 Installation

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

**Node.js is no longer something you need to install yourself.** `andro-cfw init` needs Node.js/npx once, to run Cloudflare's official `wrangler` CLI — and andro-cfw now detects your platform and installs it for you automatically if it's missing:

| Platform               | Detected via               | Auto-install method                          |
|-------------------------|-----------------------------|-----------------------------------------------|
| Windows                 | `platform.system()`         | `winget`, then `choco`, then `scoop`           |
| macOS                   | `platform.system()`         | `brew install node` (or MacPorts)              |
| Debian / Ubuntu         | `/etc/os-release`           | NodeSource LTS script, falls back to `apt-get` |
| Fedora / RHEL / CentOS  | `/etc/os-release`           | `dnf` / `yum`                                  |
| Arch / Manjaro          | `/etc/os-release`           | `pacman`                                       |
| openSUSE                | `/etc/os-release`           | `zypper`                                       |
| Alpine                  | `/etc/os-release`           | `apk`                                          |

If no supported package manager is found (or the install needs a password `sudo` can't get non-interactively), andro-cfw prints exact manual install commands for your detected system instead of failing silently. Once deployed, your bot's Python runtime needs no Node.js at all.

---

## 🚀 Setup (one time)

```bash
cd your-bot-project/
andro-cfw init
```

This will:
1. Detect your OS and auto-install Node.js if it's missing
2. Open your browser for Cloudflare login (OAuth)
3. Automatically build and deploy a Worker to your account
4. Create an encrypted `cfw.session` file in the current directory

---

## 🐍 Usage with pyTelegramBotAPI (telebot)

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

## 🐍 Usage with python-telegram-bot (v20+)

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

## 🐍 Usage with aiogram (v3+)

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

> All three libraries work exactly the same whether your session has one Cloudflare account or several (see below) — you never change your bot code, only the `andro-cfw init` command.

---

## 🔀 Smart multi-account load balancing (new)

Cloudflare's Workers **Free** plan caps you at **100,000 requests/day per account**. For busy bots, that's not always enough. andro-cfw can spread traffic across **several Cloudflare accounts**, each contributing its own 100k/day quota, and automatically fail over the instant one account's quota is hit — with zero code changes and zero downtime.

```bash
andro-cfw init --accounts 2
```

This will:
1. Open your browser **twice** — once per account. Log in with a **different** Cloudflare account each time. Each login is stored in its own isolated folder (`~/.andro_cfw/accounts/account-N`), so they never overwrite each other.
2. Deploy one Worker per account.
3. Save all of them into a single `cfw.session`.

Your bot code stays **exactly the same**:

```python
session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
```

Under the hood, when a session has more than one account, `telebot_api_url()` (and the `ptb_*` / `aiogram_*` equivalents) point at a tiny **local** load-balancing proxy that andro-cfw starts automatically, in-process, the first time you access it. That proxy:

- forwards every request to the currently active account's worker,
- **instantly** detects an HTTP 429 / Cloudflare rate-limit response (Cloudflare's signal for "daily quota exceeded"),
- transparently retries the same request on the next account, with zero failed requests visible to your bot,
- marks the exhausted account as unusable until the next **UTC midnight** (Cloudflare's daily reset), and automatically resumes using it the moment that time passes — always preferring to fall back to account #1 first once it's available again,
- persists all of this (which account is exhausted, until when, which one is active) back into the encrypted `cfw.session`, so it survives bot restarts too.

Add more accounts later without redeploying everything:

```bash
andro-cfw add-account
```

Check the health/rotation state of all accounts at any time:

```bash
andro-cfw status
```

---

## 📋 CLI Reference

| Command                          | Description                                                          |
|-----------------------------------|------------------------------------------------------------------------|
| `andro-cfw init`                  | Log into Cloudflare and deploy a single proxy worker.                  |
| `andro-cfw init --accounts 3`     | Log into 3 Cloudflare accounts and deploy a load-balanced worker pool. |
| `andro-cfw init --name foo`       | Deploy with a custom worker name.                                       |
| `andro-cfw init --force`          | Redeploy and overwrite an existing `cfw.session`.                       |
| `andro-cfw add-account`           | Add one more Cloudflare account/worker to an existing session.         |
| `andro-cfw status`                | Show the worker(s) saved for this project, and per-account health.     |
| `andro-cfw remove`                | Delete the deployed worker(s) and local `cfw.session`.                 |

---

## 🔐 Security Notes

- **`cfw.session` is encrypted** with Fernet (AES-128-CBC + HMAC). The key lives in `~/.andro_cfw/key`, **not** inside the project, so committing `cfw.session` to git by accident does not by itself expose your worker URL(s).
- **Still, add `cfw.session` to `.gitignore`** — treat it like any other credential file.
- The generated worker is a **pure pass-through proxy**: it does not log, store, or inspect bot tokens, updates, or file contents.
- **Your Cloudflare password never touches this library** — all authentication is delegated to Cloudflare's own `wrangler login` OAuth flow, isolated per account when using multi-account mode.
- You are deploying to **your own** Cloudflare account(s) (free tier is sufficient), so you retain full control and can delete any/all workers at any time.

---

## 📋 Requirements

- Python 3.9+
- Node.js — installed **automatically** by andro-cfw if missing (only needed for `andro-cfw init` / `add-account` / `remove`)
- One free [Cloudflare](https://dash.cloudflare.com/sign-up) account (or several, for load balancing)

---

## 🗒️ Changelog

### 0.2.0
- **Automatic Node.js setup**: detects your OS (Windows/macOS/Linux + distro) and package manager, and installs Node.js/npx for you if missing.
- **Smart multi-account load balancing**: `andro-cfw init --accounts N` and `andro-cfw add-account` pool several Cloudflare accounts' free-tier quotas, with instant automatic failover on daily quota exhaustion and automatic resumption after Cloudflare's daily UTC reset.
- `andro-cfw status` now reports per-account health/rotation state.
- Fully backward compatible with existing single-worker `cfw.session` files.

### 0.1.0
- Initial release.

---

## 📄 License

MIT