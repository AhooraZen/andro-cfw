# andro-cfw

[![PyPI](https://img.shields.io/pypi/v/andro-cfw?color=blue)](https://pypi.org/project/andro-cfw/)
[![Python](https://img.shields.io/pypi/pyversions/andro-cfw)](https://pypi.org/project/andro-cfw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/readme-EN%20%7C%20FA-blue)](README.md)

> **English** | [فارسی](README.fa.md)

---

## 🎯 What does this library do?

In countries like Iran where `api.telegram.org` is restricted or filtered, developers traditionally need a VPN or a VPS abroad to run Telegram bots.

**andro-cfw** solves this with a smart trick: it deploys a Cloudflare Worker as a reverse proxy between your bot and Telegram:

```
Your Python Bot  ←→  Cloudflare Worker (Unfiltered)  ←→  api.telegram.org
```

Cloudflare's global Edge network is accessible directly without a VPN, so your bot connects to your Worker and the Worker relays requests to Telegram. Simple as that.

---

## ✨ Features

- **No VPN Required** — neither on your local dev environment nor on your production server.
- **You Own the Worker** — deploys to your own Cloudflare account; you maintain complete control.
- **Secure OAuth Authentication** — logs in via Cloudflare's official OAuth (`wrangler login`); your password is never seen or handled by andro-cfw.
- **Encrypted Session** — saves `cfw.session` encrypted with Fernet (AES-128-CBC + HMAC), storing keys safely in `~/.andro_cfw/key`.
- **Smart Multi-Account Load Balancing** — optionally pool multiple Cloudflare accounts (`--accounts N`) to scale past the 100k daily request limit with automatic failover and daily UTC reset.
- **Multi-Library Support** — works seamlessly with `pyTelegramBotAPI (telebot)`, `python-telegram-bot`, and `aiogram`.
- **No Monkey-Patching** — just point base URLs to your session proxy; your bot logic stays 100% clean and standard.

---

## 📦 Installation

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

**Prerequisite:** [Node.js](https://nodejs.org) — only needed during `andro-cfw init` / `remove` (for the `wrangler` CLI). If missing, andro-cfw attempts auto-installation using your system's package manager (`pacman`, `apt`, `dnf`, `brew`, `winget`).

---

## 🚀 One-Time Setup (`init`)

```bash
cd your-bot-project/
andro-cfw init
```

This command:
1. Checks and verifies your Node.js & Wrangler CLI toolchain.
2. Opens your default browser for official Cloudflare OAuth login.
3. Automatically creates and deploys your proxy Worker.
4. Generates an encrypted `cfw.session` file in your project folder.

If your environment PATH needs `andro-cfw` executable registered:
```bash
andro-cfw setup-path
```

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
    bot.reply_to(message, "Hello! This bot is working behind restricted regions! 🎉")

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
    await update.message.reply_text("Hello! This bot is running without a VPN! 🎉")

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

---

## 📋 CLI Commands

| Command | Description |
|---------|-------------|
| `andro-cfw init` | Cloudflare login + deploy worker + generate session |
| `andro-cfw init --name foo` | Deploy worker with custom name |
| `andro-cfw init --force` | Redeploy and overwrite existing session |
| `andro-cfw init --accounts 2` | Set up multi-account load balancing |
| `andro-cfw add-account` | Add another Cloudflare account worker to the pool |
| `andro-cfw status` | Show status of deployed worker(s) |
| `andro-cfw setup-path` | Safely add executable directory to User PATH |
| `andro-cfw remove` | Delete worker(s) & local session |

---

## 🔐 Security

- **Encrypted `cfw.session`** — encrypted using Fernet (AES-128-CBC + HMAC). Secret key stored in `~/.andro_cfw/key` outside project directory.
- **Git Safety** — Always add `cfw.session` to `.gitignore`. Even if committed by mistake, it cannot be decrypted without your private key.
- **Pure Proxy Worker** — Worker code is a zero-log pass-through proxy; it stores no tokens and logs no request contents.

---

## 📋 Requirements

- Python 3.9+
- Node.js (only for `init` & `remove`)
- Free [Cloudflare Account](https://dash.cloudflare.com/sign-up)

---

## 📄 License

MIT
