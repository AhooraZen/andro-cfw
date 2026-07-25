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
- **1-Line Auto-Patcher (`andro_cfw.patch()`)** — 1-line auto-detection and patching for telebot, ptb, aiogram, pyrogram, hydrogram
- **100% Serverless Webhook Engine** — option to run bot logic 100% inside Cloudflare Worker 24/7 (0 laptop/server required)
- **Smart multi-account load balancing** — pool several Cloudflare accounts' free-tier quotas (`andro-cfw init --accounts N` or `andro-cfw add-account`), with automatic instant failover and daily auto-reset
- **Framework Code Generator (`andro-cfw snippet`)** — generate copy-paste ready starter code for telebot, ptb, aiogram, pyrogram, or hydrogram
- **Live Network & Health Diagnostics (`andro-cfw check`)** — test live connection speed, HTTP status, and Keep-Alive ping latency of all deployed workers
- **ANSI Terminal Colors & Clean Progress** — clear colored step-by-step logging with automatic non-TTY & `NO_COLOR` safety
- **Safe Cross-Platform PATH Registration (`andro-cfw setup-path`)** — safely registers executable folder in Windows Registry (`HKCU\Environment\PATH`) or POSIX shells without overwriting PATH

---

## 📦 Installation & Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

### Registered Executable / PATH Setup

If running `andro-cfw` in your terminal gives `command not found`, register it safely into your User PATH:

```bash
python -m andro_cfw.cli setup-path
```
- **On Windows**: Safely appends Python's `Scripts\` folder to `HKCU\Environment\PATH` via Windows Registry without overwriting existing PATH variables.
- **On Linux / macOS**: Safely appends `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` / `~/.zshrc`.

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

## ⚡ 100% Serverless Webhook Bots (24/7 Free Cloud Hosting)

Beyond running as a local reverse proxy for Python bots, your deployed Cloudflare Worker can run your Telegram bot **100% serverless** directly at Cloudflare's Edge — with **24/7 uptime**, **~5ms response latency**, and **zero servers or laptops required**.

### How to Enable 100% Serverless Webhook Mode:

1. **Deploy your Cloudflare Worker with andro-cfw**:
   ```bash
   andro-cfw init
   ```

2. **Set your Bot Token on your Worker**:
   Add your `BOT_TOKEN` to your worker's `wrangler.toml` or Cloudflare Dashboard environment variables:
   ```toml
   [vars]
   BOT_TOKEN = "YOUR_BOT_TOKEN_FROM_BOTFATHER"
   ```

3. **Register your Webhook with Telegram**:
   Open this URL in your browser or terminal:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_WORKER_URL>/webhook"
   ```

4. **That's it!**:
   Whenever a user sends a message or `/start` command to your bot, Telegram sends an instant HTTP POST to your Cloudflare Worker. Cloudflare executes your bot logic in **~5ms** directly at the Edge and returns the reply 24/7 — even when your laptop is turned off!

---

## 🐍 1-Line Universal Framework Auto-Patcher (`andro_cfw.patch()`)

```python
import telebot
import andro_cfw

# 1-line setup: automatically detects imported framework and routes API calls through proxy
andro_cfw.patch()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Hello from behind the filter! 🎉")

bot.infinity_polling()
```

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

Test live network connectivity, HTTP response code, and Keep-Alive latency (ms) across all deployed workers:

```bash
andro-cfw check
```

Output example:
```
  Worker [0]: account-1
    URL     : https://andro-cfw-12345678.workers.dev
    Status  : HTTP 200 OK (59.1 ms)
    Quota   : [available]
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

---

## 📄 License

MIT