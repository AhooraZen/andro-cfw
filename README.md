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
Your Bot (Python / JS / PHP)  ←→  Cloudflare Worker (unfiltered)  ←→  api.telegram.org
```

Cloudflare's edge network is reachable from restricted regions even when Telegram's API is not, so your bot talks to the Worker and the Worker talks to Telegram.

---

## ✨ Key Features

- 🔒 **Zero VPN Required** — No VPN needed on your dev machine, server, or during webhook setup.
- ☁️ **100% Serverless Cloud Bots** — Run real Telegram bots 24/7 directly inside Cloudflare Workers (0 laptop or server required).
- 🐍 **1-Line Auto-Patcher (`andro_cfw.patch()`)** — Universal auto-detection and patching for `telebot`, `ptb`, `aiogram`, `pyrogram`, and `hydrogram`.
- 🔀 **Multi-Account Load Balancing** — Pool several Cloudflare accounts' free-tier quotas (100k req/day per account) with automatic failover and daily auto-resets.
- ⚡ **Snippet & Webhook Generator (`andro-cfw serverless`)** — 1-command deployment of 100% serverless bots with interactive prompts.
- 🔍 **Live Latency & Health Checks (`andro-cfw check`)** — Test live connection speed and Keep-Alive ping latency across deployed workers.
- 🔐 **Encrypted Session Storage** — Local session files are encrypted with Fernet (AES-128 + HMAC).

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

---

## 📖 Complete Guide: 100% Serverless Telegram Bots on Cloudflare

You can run your Telegram bot **100% serverless** on Cloudflare Edge with **24/7 uptime**, **~5ms response latency**, and **zero server costs** (using Cloudflare's free 100,000 requests/day tier).

---

### Method A: Zero-Code 1-Command Serverless Bot (`andro-cfw serverless`)

Deploy a fully functional 24/7 serverless bot in under 30 seconds:

1. **Run the deployment command**:
   ```bash
   andro-cfw serverless
   ```
2. **Enter your Telegram Bot Token** from `@BotFather` when prompted:
   ```text
   [andro-cfw] Enter your Telegram Bot Token from @BotFather: 7123456789:AAFgX...
   ```
3. **Done!** `andro-cfw` will deploy the Cloudflare Worker, configure the Webhook, and register it with Telegram automatically — with **zero VPN required**.

#### Built-in Serverless Commands:
- `/start` or `/help` — Welcome card with edge performance & latency metrics.
- `/ping` — Responds with `pong 🏓 (< 5ms Edge Latency)`.
- `/status` — Displays live Cloudflare Worker status & health.
- `/echo <text>` — Echoes back any text message.

---

### Method B: Full Custom TypeScript / JavaScript Worker Bot

If you want to build a full custom serverless bot with interactive buttons, database calls, or custom logic in JavaScript/TypeScript:

#### 1. `worker.ts` Code:

```typescript
export interface Env {
  BOT_TOKEN?: string;
}

const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // 1. Webhook Update Handler (POST /webhook)
    if (request.method === "POST" && url.pathname.includes("/webhook")) {
      try {
        // Extract token from query parameter or Env
        const token = url.searchParams.get("token") || env.BOT_TOKEN;
        const update = (await request.json()) as any;

        if (update && update.message && update.message.text && token) {
          const chatId = update.message.chat.id;
          const text = update.message.text.trim();

          let replyText = "";

          // Custom Bot Command Logic
          if (text === "/start") {
            replyText = "👋 Hello! I am running 100% Serverless on Cloudflare Edge!";
          } else if (text === "/ping") {
            replyText = "🏓 Pong from Cloudflare Worker!";
          } else if (text.startsWith("/echo ")) {
            replyText = `📢 You said: ${text.slice(6)}`;
          } else {
            replyText = `🤖 Received your message: "${text}"`;
          }

          // Reply back to Telegram
          const replyUrl = `${TELEGRAM_ORIGIN}/bot${token}/sendMessage`;
          await fetch(replyUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chat_id: chatId,
              text: replyText,
              parse_mode: "Markdown",
            }),
          });
        }
      } catch (err) {
        console.error("Webhook processing error:", err);
      }
      return new Response("OK", { status: 200 });
    }

    // 2. Reverse Proxy Pass-through for local/external bots
    const targetUrl = TELEGRAM_ORIGIN + url.pathname + url.search;
    return fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      // @ts-ignore
      duplex: "half",
    });
  },
};
```

---

### Method C: Python Bot via 1-Line Patcher (`andro_cfw.patch()`)

If you prefer writing your bot logic in Python using `telebot`, `pyrogram`, `aiogram`, or `python-telegram-bot`:

```python
import telebot
import andro_cfw

# 1-Line Auto-Patcher: Routes 100% of Telegram API calls through Cloudflare Worker
session = andro_cfw.patch()

bot = telebot.TeleBot("YOUR_BOT_TOKEN_FROM_BOTFATHER")

@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(
        message,
        "🤖 **Hello from behind the filter!**\n\n"
        f"🌐 **Worker URL**: `{session.worker_url}`\n"
        "🔒 **Status**: Unfiltered & Running Smoothly!"
    )

if __name__ == "__main__":
    print(f"🚀 Bot starting behind Cloudflare Worker ({session.worker_url})...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
```

---

### Method D: PHP / External Webhook Backend Mode (`FORWARD_WEBHOOK_URL`)

If you have an existing PHP, Node.js, Python, or Go webhook bot hosted on your own server or cPanel, you can use Cloudflare Worker as a **Webhook Filter Bypass**:

1. In your Worker's `wrangler.toml` or Cloudflare Dashboard environment variables, set:
   ```toml
   [vars]
   FORWARD_WEBHOOK_URL = "https://your-server.com/my_bot_webhook.php"
   ```
2. Whenever Telegram sends a Webhook update to your Cloudflare Worker, Cloudflare automatically strips the network filter and forwards the payload straight to your PHP backend!

---

## 🐍 Framework Snippet Generator (`andro-cfw snippet`)

Generate copy-paste ready starter code for your framework:

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
| `andro-cfw serverless`            | Deploy a 100% serverless 24/7 Telegram bot to Cloudflare Edge.        |
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

## 📄 License

MIT