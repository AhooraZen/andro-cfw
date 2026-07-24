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
- **Multi-library support** — telebot, python-telegram-bot, aiogram, pyrogram, hydrogram
- **No monkey-patching** — just swap the API URL, everything else stays normal
- **Zero-setup Node.js** — andro-cfw detects your OS/distro and installs Node.js automatically if missing
- **Smart multi-account load balancing** — pool several Cloudflare accounts' free-tier quotas (`andro-cfw init --accounts N` or `andro-cfw add-account`), with automatic instant failover and daily auto-reset
- **Framework Code Generator (`andro-cfw snippet`)** — generate copy-paste ready starter code for telebot, ptb, aiogram, pyrogram, or hydrogram
- **Live Network & Health Diagnostics (`andro-cfw check`)** — test live connection speed, HTTP status, and ping latency of all deployed workers
- **ANSI Terminal Colors & Clean Progress** — clear colored step-by-step logging with automatic non-TTY & `NO_COLOR` safety
- **Safe Cross-Platform PATH Registration (`andro-cfw setup-path`)** — safely registers executable folder in Windows Registry (`HKCU\Environment\PATH`) or POSIX shells without overwriting PATH

---

## 📦 Installation

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

---

## 🚀 Setup (one time)

```bash
cd your-bot-project/
andro-cfw init
```

This will:
1. Detect your OS and auto-install Node.js if missing
2. Open your browser for Cloudflare login (OAuth)
3. Automatically build and deploy a Worker to your account
4. Create an encrypted `cfw.session` file in the current directory

---

## ⚡ Framework Snippet Generator (`andro-cfw snippet`)

Generate copy-paste ready Python code for your preferred Telegram bot framework:

```bash
# Print starter snippet for Telebot
andro-cfw snippet -f telebot

# Generate ready-to-run bot.py for Aiogram / Pyrogram / PTB / Hydrogram
andro-cfw snippet -f aiogram -o bot.py
andro-cfw snippet -f pyrogram -o bot.py
andro-cfw snippet -f hydrogram -o bot.py
andro-cfw snippet -f ptb -o bot.py
```

---

## 🔍 Worker Health & Latency Check (`andro-cfw check`)

Test live network connectivity, HTTP response code, and latency (ms) across all deployed workers:

```bash
andro-cfw check
```

Output example:
```
  Worker [0]: account-1
    URL     : https://andro-cfw-12345678.workers.dev
    Status  : HTTP 200 OK (45.2 ms)
    Quota   : [available]
```

---

## 🔀 Smart Multi-Account Load Balancing

Cloudflare's Workers **Free** plan caps you at **100,000 requests/day per account**. andro-cfw can spread traffic across **several Cloudflare accounts**, each contributing its own 100k/day quota, and automatically fail over the instant one account's quota is hit.

- **Initialize with N accounts**:
  ```bash
  andro-cfw init --accounts 2
  ```
- **Add another account to an existing session**:
  ```bash
  andro-cfw add-account
  ```

---

## 🐍 Usage Code Examples

### Usage with pyTelegramBotAPI (telebot)

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

### Usage with python-telegram-bot (v20+)

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

### Usage with aiogram (v3+)

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

### Usage with Pyrogram / Hydrogram

```python
from pyrogram import Client
from andro_cfw import CFWSession

session = CFWSession.load()
app = Client("my_bot", bot_token="YOUR_BOT_TOKEN", api_id=12345, api_hash="HASH")
app.api_url = session.api_base_url()
```

---

## 📋 CLI Reference

| Command                          | Description                                                          |
|-----------------------------------|------------------------------------------------------------------------|
| `andro-cfw init`                  | Log into Cloudflare and deploy a single proxy worker.                  |
| `andro-cfw init --accounts 3`     | Log into 3 Cloudflare accounts and deploy a load-balanced worker pool. |
| `andro-cfw add-account`           | Add one more Cloudflare account/worker to an existing session.         |
| `andro-cfw snippet -f telebot`    | Generate ready-to-run Python code for Telebot, PTB, Aiogram, Pyrogram, or Hydrogram. |
| `andro-cfw check`                 | Test live network connectivity and ping response times of deployed worker(s). |
| `andro-cfw status`                | Show the worker(s) saved for this project, and per-account health.     |
| `andro-cfw setup-path`            | Safely add andro-cfw executable directory to User PATH.                |
| `andro-cfw remove`                | Delete the deployed worker(s) and local `cfw.session`.                 |

---

## 🔐 Security Notes

- **`cfw.session` is encrypted** with Fernet (AES-128-CBC + HMAC). Key stored in `~/.andro_cfw/key`.
- **Add `cfw.session` to `.gitignore`**.
- The generated worker is a **pure pass-through proxy**: it does not log, store, or inspect bot tokens or updates.

---

## 🗒️ Changelog

### 0.2.1
- **Framework Starter Code Generator (`andro-cfw snippet`)**: Generate copy-paste ready starter Python code for Telebot, PTB, Aiogram, Pyrogram, or Hydrogram.
- **Worker Health & Ping Checker (`andro-cfw check`)**: Ping worker proxies to measure response latency (ms) and HTTP status.
- **Safe PATH Registration (`andro-cfw setup-path`)**: Safely appends executable folder to Windows Registry (`HKCU\Environment\PATH`) or POSIX shells without overwriting PATH.
- **ANSI Terminal Formatting**: Colorful step-by-step progress logging in CLI.
- **64 Automated Unit Tests**: Comprehensive test suite covering all modules.

### 0.2.0
- Automatic Node.js setup & Smart Multi-Account Load Balancing (`--accounts N`, `add-account`).

---

## 📄 License

MIT