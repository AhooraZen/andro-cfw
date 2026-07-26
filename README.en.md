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

With several Cloudflare accounts pooled together, a shared local daemon sits in the middle and picks the healthiest one for you:

```
Bot A ┐
Bot B ┼→  andro-cfw daemon (127.0.0.1)  →  Worker #1 / #2 / #3  →  api.telegram.org
Bot C ┘         counts + routes + retries
```

---

## ✨ Key Features

- 🔒 **Zero VPN Required** — No VPN needed on your dev machine, server, or during webhook setup.
- 🐍 **Pure Python install** — one `pip install` is the whole setup. Deployment speaks to the Cloudflare REST API over HTTPS, so there is no Node.js toolchain, no package manager to invoke, and nothing that asks for `sudo`.
- ☁️ **100% Serverless Cloud Bots** — Run real Telegram bots 24/7 directly inside Cloudflare Workers (0 laptop or server required).
- 🧠 **Shared Proxy Daemon (`andro-cfw daemon`)** — One long-lived local proxy that every bot on the machine shares, instead of one private balancer per bot process.
- 📈 **Exact Quota Accounting** — The daemon proxies every request, so it counts them and rotates accounts **before** the 100,000/day free-tier limit, not after a 429.
- 📊 **Local Dashboard** — Worker health, per-account quota, a latency chart, and a failover log at `http://127.0.0.1:8787/__andro/`.
- 🐍 **1-Line Auto-Patcher (`andro_cfw.patch()`)** — Auto-detects and patches the imported HTTP Bot API framework: `telebot`, `python-telegram-bot`, or `aiogram`. (MTProto clients such as pyrogram/hydrogram/telethon cannot be routed through an HTTP proxy — `patch()` warns instead of failing silently.)
- 🔀 **Multi-Account Load Balancing** — Pool several Cloudflare accounts' free-tier quotas (100k req/day per account) with latency-aware routing and daily auto-resets.
- ⚡ **Snippet & Webhook Generator (`andro-cfw serverless`)** — 1-command deployment of 100% serverless bots with interactive prompts.
- 🔍 **Live Latency & Health Checks (`andro-cfw check`)** — Test live connection speed and Keep-Alive ping latency across deployed workers.
- 🔐 **Encrypted Local Storage** — The session file and your Cloudflare API tokens are encrypted with Fernet (AES-128 + HMAC).

---

## 📦 Installation & Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install git+https://github.com/AhooraZen/andro-cfw.git
```

> **Not on PyPI, by design.** This is a personal tool, so it is installed
> straight from the repository (or from the wheel attached to a GitHub
> release). `pyproject.toml` carries the `Private :: Do Not Upload` classifier,
> which PyPI rejects — an accidental publish cannot happen.

That is the entire installation. Nothing else is downloaded, compiled, or installed on your system.

### Registered Executable / PATH Setup

If running `andro-cfw` in your terminal gives `command not found`, register it safely into your User PATH:

```bash
python -m andro_cfw.cli setup-path
```

---

> **Verified against a live Cloudflare account.** `login`, `init`, `check`,
> `remove`, the pass-through proxy, the webhook route and the daemon's quota
> accounting have all been exercised end to end on a real deployed Worker, not
> only in tests.

## 🔑 Step 1 — Log in with a Cloudflare API token (`andro-cfw login`)

andro-cfw authenticates with a scoped **API token** that you create once:

1. Open [`https://dash.cloudflare.com/profile/api-tokens`](https://dash.cloudflare.com/profile/api-tokens).
2. **Create Token** → pick the **"Edit Cloudflare Workers"** template → **Continue to summary** → **Create Token**.
3. Copy the token (Cloudflare shows it exactly once), then:

```bash
andro-cfw login
```

Paste the token at the hidden prompt. andro-cfw verifies it against the Cloudflare API, resolves your account ID, and stores it encrypted with Fernet — the same local key that protects `cfw.session` — at `~/.andro_cfw/credentials`, mode `0600`.

That template grants exactly what is needed (`Workers Scripts:Edit`) and nothing more. If your token can see more than one Cloudflare account, andro-cfw lists them and asks you to choose with `--account-id` rather than guessing.

## 🚀 Step 2 — Deploy your worker (`andro-cfw init`)

```bash
andro-cfw init                 # one account, one worker
andro-cfw init --accounts 3    # a load-balanced pool of three
```

The worker source is uploaded straight to the Cloudflare API, the `workers.dev` route is enabled, and the resulting URL is saved into an encrypted `cfw.session` in your project directory.

---

### Two ways to authenticate

| | `andro-cfw login` | `andro-cfw login --browser` |
|---|---|---|
| What you hand over | An API token you create and paste | Nothing — you approve on Cloudflare's own site |
| What is stored | The token, until you revoke it | A short-lived access token, refreshed automatically |
| Works headless | Yes (`$CLOUDFLARE_API_TOKEN`) | No, it needs a browser |
| Setup | None | Requires an OAuth client id (see below) |

The token flow is the default because it needs no setup and works on a server.
The browser flow asks less of your trust: the credential is issued on
Cloudflare's domain, the consent screen lists the exact scopes, and what lands
on disk expires.

**Enabling the browser flow.** andro-cfw deliberately ships no OAuth client id.
Register a public client with "Authorization Code with PKCE" and the redirect
URI `http://localhost:8976/oauth/callback` at
[Cloudflare's OAuth client docs](https://developers.cloudflare.com/fundamentals/oauth/create-an-oauth-client/),
then set `ANDRO_CFW_OAUTH_CLIENT_ID`.

> **Why not just reuse wrangler's client id?** It is public, and it would work.
> But Cloudflare's consent screen names the application being authorised — the
> user would be told that *Wrangler* wants access, and the grant would appear
> under Wrangler in their list of authorised applications. That is a worse trust
> story than asking for a token, so andro-cfw does not do it.

Either way, credentials are encrypted at `~/.andro_cfw/credentials` (mode 0600)
with the same local key as your session, and `andro-cfw logout` revokes and
removes them.

## 🧠 The shared proxy daemon (`andro-cfw daemon`)

Run one daemon per machine:

```bash
andro-cfw daemon
```

It binds to `127.0.0.1` only, and every bot you start afterwards routes through it — `andro_cfw.patch()` and `CFWSession` pick it up automatically instead of spinning up a private balancer inside each process.

**Why this replaced the in-process balancer.** Previously every bot process started its own load balancer. Three bots meant three balancers, each independently discovering that an account had returned 429, each writing to the same session file, and none of them aware of how much quota the others had already burned. There was no request counting at all — failover was purely reactive, so **every switch cost one failed request**.

The daemon proxies every request itself, so it can simply count them:

- **Counted, not guessed.** Request counts per account per UTC day live in a SQLite database at `~/.andro_cfw/usage.db`.
- **Rotates early.** An account is retired once it reaches **95%** of the free plan's 100,000 requests/day, so your bot never meets the 429 that used to trigger failover.
- **Latency-aware.** Among the healthy workers it picks the one with the lowest **median** latency (median, not mean — a single 30-second timeout should not disqualify a good account), rather than simply the lowest index.
- **Retries transient failures.** A 5xx from the edge is retried with backoff instead of being handed to your bot as an error.
- **One source of truth.** All bots on the machine share one set of counters, one health view, and one failover decision.

### ⚠️ What the counters do *not* cover

**Webhook traffic goes from Telegram directly to your Worker and never passes through the daemon.** Nothing on your machine sees those requests, so they cannot be counted.

The numbers in the dashboard therefore cover **long-polling and outbound Bot API calls only**. If your bot is webhook-driven, expect the reported usage to read low — sometimes near zero — while your real Cloudflare consumption is much higher. Check the Cloudflare dashboard for the authoritative figure in that case.

---

## 📊 Local dashboard

While the daemon is running, open:

```
http://127.0.0.1:8787/__andro/
```

The daemon prints the address on startup; `8787` is the default and `--port` changes it. The page is served by the daemon itself — plain HTML, no external assets, bound to loopback — and shows:

- **Worker health** — which accounts are up, which are cooling off.
- **Quota consumption per account** — today's counted requests against the 100,000/day allowance.
- **A latency chart** — median response time per worker over the recent window.
- **A failover event log** — every switch, quota trip, and exhausted retry, with timestamps.

The same event log is available in the terminal with `andro-cfw logs`.

---

## 📖 Complete Guide: 100% Serverless Telegram Bots on Cloudflare

You can run your Telegram bot **100% serverless** on Cloudflare Edge with **24/7 uptime**, **~5ms response latency**, and **zero server costs** (using Cloudflare's free 100,000 requests/day tier).

---

### Method A: 1-Command Serverless Webhook (`andro-cfw serverless`)

Point Telegram at your worker and relay every update to your own backend:

1. **Run the deployment command**:
   ```bash
   andro-cfw serverless --forward-url https://your-backend.example.com/telegram
   ```
2. **Provide your bot token.** In order of preference:
   - `TELEGRAM_BOT_TOKEN` in the environment,
   - the hidden prompt (input is not echoed),
   - `--token` (least preferred: argv is readable by every process on the machine).
3. **Done.** `andro-cfw` stores the token as an encrypted Cloudflare Worker
   secret, generates a fresh webhook secret, and registers the webhook with
   Telegram — with **zero VPN required**.

#### How the webhook is secured

| | |
|---|---|
| Bot token | Uploaded over HTTPS as an encrypted Cloudflare Worker secret (`BOT_TOKEN`). Never placed in the webhook URL. |
| Webhook auth | A 32-byte secret is passed to `setWebhook(secret_token=...)`; Telegram echoes it in `X-Telegram-Bot-Api-Secret-Token` and the worker rejects any update that does not match. |
| CORS | Off by default. Set `ALLOWED_ORIGINS` only if a browser must call the worker. |

> **Upgrading from v0.3.x?** Earlier releases embedded the bot token in the
> webhook URL as `?token=...`. That URL is stored by Telegram and replayed on
> every update. Re-run `andro-cfw serverless` to rotate onto the header-based
> scheme, and **revoke the old token with @BotFather** — treat it as exposed.

---

### Method B: Full Custom JavaScript Worker Bot

If you want to build a full custom serverless bot with interactive buttons, database calls, or custom logic, write it as a Worker module and paste it into the Cloudflare dashboard (**Workers & Pages** → your worker → **Edit code**).

The shipped template is `worker.mjs` — plain ES module JavaScript. The upload API has no bundler, so whatever the worker runs must already be valid JavaScript; TypeScript has to be compiled first if you prefer writing it.

#### 1. `worker.mjs` code:

```javascript
const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Webhook update handler (POST /webhook)
    if (request.method === "POST" && url.pathname.includes("/webhook")) {
      try {
        // The token comes from the Worker secret, never from the request.
        const token = env.BOT_TOKEN;
        const update = await request.json();

        if (update && update.message && update.message.text && token) {
          const chatId = update.message.chat.id;
          const text = update.message.text.trim();

          let replyText = "";

          // Custom bot command logic
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

    // 2. Reverse proxy pass-through for local/external bots
    const targetUrl = TELEGRAM_ORIGIN + url.pathname + url.search;
    return fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      duplex: "half",
    });
  },
};
```

---

### Method C: Python Bot via 1-Line Patcher (`andro_cfw.patch()`)

If you prefer writing your bot logic in Python using `telebot`, `aiogram`, or `python-telegram-bot`:

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

Start `andro-cfw daemon` first if you want quota accounting, latency-aware routing, and the dashboard; the bot code above does not change either way.

---

### Method D: PHP / External Webhook Backend Mode (`FORWARD_WEBHOOK_URL`)

If you have an existing PHP, Python, or Go webhook bot hosted on your own server or cPanel, you can use Cloudflare Worker as a **Webhook Filter Bypass**:

1. Point the worker at your backend. The easy way is to let andro-cfw store the
   secret for you while deploying:
   ```bash
   andro-cfw serverless --forward-url https://your-server.com/my_bot_webhook.php
   ```
   You can also set `FORWARD_WEBHOOK_URL` by hand in the Cloudflare dashboard
   under **Workers & Pages → your worker → Settings → Variables and Secrets**.
2. Every update Telegram sends to your Worker is forwarded verbatim to your
   backend, so the network filter never touches your server.

> **If your backend is itself a Cloudflare Worker, `FORWARD_WEBHOOK_URL` will
> not work.** A `fetch()` from one Worker to another Worker's `workers.dev`
> hostname is not dispatched to that Worker: the call appears to succeed, the
> update is accepted with `200 OK`, and the backend simply never runs. Add a
> [service binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/)
> named `FORWARD_SERVICE` pointing at the target Worker instead — the worker
> prefers it over `FORWARD_WEBHOOK_URL` when both are present.

The worker always answers Telegram with `200 OK`, even if your backend is
down — a non-200 makes Telegram redeliver the same update indefinitely, which
turns a brief outage into a retry storm.

---

## 🐍 Framework Snippet Generator (`andro-cfw snippet`)

Generate copy-paste ready starter code for your framework:

```bash
# Print starter snippet for Telebot
andro-cfw snippet -f telebot

# Generate ready-to-run bot.py for telebot / PTB / aiogram
andro-cfw snippet -f aiogram -o bot.py
andro-cfw snippet -f patch -o bot.py
andro-cfw snippet -f ptb -o bot.py
```

---

## 🛠 Self-Hosted Bot API Server (`UPSTREAM_API_ORIGIN`)

By default the worker proxies to `https://api.telegram.org`. Point it at your own
[`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) instance to lift
Telegram's 50 MB upload cap or keep media on your own infrastructure.

Set `UPSTREAM_API_ORIGIN` on the deployed worker from the Cloudflare dashboard
(**Workers & Pages → your worker → Settings → Variables and Secrets**), for
example `https://bot-api.your-server.com`.

Only the origin is used — any path or query in the value is dropped, and a
malformed or non-http(s) value falls back to `api.telegram.org` rather than
sending traffic somewhere unintended.

### Large uploads and downloads

The daemon streams request and response bodies rather than buffering them.
Request bodies stay in memory up to 1 MB and spill to a temp file above that, so
concurrent file transfers do not pin RAM — while still being replayable if a
worker has to be swapped mid-request.

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
| `andro-cfw login`                 | Store a Cloudflare API token, encrypted, for later deployments.        |
| `andro-cfw init`                  | Deploy a single proxy worker and create `cfw.session`.                 |
| `andro-cfw init --accounts 3`     | Deploy a load-balanced pool across 3 Cloudflare accounts.              |
| `andro-cfw daemon`                | Run the shared local proxy + dashboard that all your bots route through. |
| `andro-cfw serverless`            | Deploy a 100% serverless 24/7 Telegram bot to Cloudflare Edge.         |
| `andro-cfw add-account`           | Add one more Cloudflare account/worker to an existing session.         |
| `andro-cfw snippet -f telebot`    | Generate ready-to-run Python code for telebot, ptb, aiogram, or the `patch()` one-liner. |
| `andro-cfw check`                 | Test live network connectivity and ping response times of deployed worker(s). |
| `andro-cfw status`                | Show the worker(s) saved for this project, and per-account health.     |
| `andro-cfw logs`                  | Print recent daemon events: failovers, quota trips, exhausted retries.  |
| `andro-cfw setup-path`            | Safely add andro-cfw executable directory to User PATH.                |
| `andro-cfw remove`                | Delete the deployed worker(s) and local `cfw.session`.                 |

---

## 🔄 Migrating from 0.4.x

Everything you deployed still works — the worker on Cloudflare is unchanged from
your bot's point of view, and your existing `cfw.session` is read as-is.

Two things to do, one thing you can clean up:

1. **Authenticate again, with an API token.** The old browser OAuth flow is gone.
   Create a token with the **"Edit Cloudflare Workers"** template at
   [`https://dash.cloudflare.com/profile/api-tokens`](https://dash.cloudflare.com/profile/api-tokens)
   and run `andro-cfw login` (once per account, if you run a pool). Until you do,
   any command that touches Cloudflare will tell you to log in.
2. **Start the daemon.** `andro-cfw daemon` gives you quota accounting, early
   rotation, and the dashboard. Without it your bots still work; they simply
   route directly and nothing is counted.
3. **Node.js is no longer used.** If an earlier version of andro-cfw installed
   Node.js on your machine, nothing here needs it any more — uninstall it if you
   installed it only for this tool. The `ANDRO_CFW_ALLOW_NODESOURCE` and
   `ANDRO_CFW_NO_AUTO_INSTALL` environment variables no longer do anything and
   can be removed from your shell profile.

Your bot code does not change. `andro_cfw.patch()`, `CFWSession`, and the
generated snippets all keep the same API.

---

## 🔐 Security Notes

- **`cfw.session` is encrypted** with Fernet (AES-128-CBC + HMAC). Key stored in `~/.andro_cfw/key`.
- **Your Cloudflare API token is encrypted too**, in `~/.andro_cfw/credentials` (mode `0600`), with the same key. Delete that file to log out.
- Use the **"Edit Cloudflare Workers"** token template. It grants `Workers Scripts:Edit` and nothing else — a leaked token cannot touch your DNS, your zones, or your billing.
- **Add `cfw.session` to `.gitignore`**.
- **Nothing is installed with elevated privileges.** andro-cfw is a pure-Python package that makes HTTPS calls; it never invokes a package manager and never asks for `sudo`.
- The daemon and its dashboard bind to `127.0.0.1` only.
- The generated worker is a **pure pass-through proxy**: it does not log, store, or inspect bot tokens or updates.

---

## 📄 License

MIT
