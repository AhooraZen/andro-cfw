# Changelog

All notable changes to the `andro-cfw` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v0.4.0] - 2026-07-26

Security and correctness release. **Contains breaking changes** — read the
migration notes below before upgrading.

### 🔒 Security

- **Bot token removed from the webhook URL.** `andro-cfw serverless` previously
  registered `https://<worker>/webhook?token=<BOT_TOKEN>` with Telegram. That
  URL is stored in the bot's webhook configuration and re-sent on every update.
  The token is now stored as an encrypted Cloudflare Worker secret
  (`wrangler secret put BOT_TOKEN`) and the webhook URL carries no credentials.
  **If you deployed with v0.3.x, revoke that bot token with @BotFather and
  re-run `andro-cfw serverless`.**
- **Webhook authentication.** A fresh 32-byte secret is passed to
  `setWebhook(secret_token=...)`; the worker verifies the returned
  `X-Telegram-Bot-Api-Secret-Token` header in constant time and rejects
  unauthenticated updates with 401. Previously anyone who learned the worker URL
  could inject fabricated updates.
- **The worker no longer trusts a caller-supplied `?token=` query parameter.**
- **CORS is opt-in.** `Access-Control-Allow-Origin: *` with
  `Access-Control-Allow-Headers: *` turned every deployed worker into a
  general-purpose CORS bypass for the Bot API. Set `ALLOWED_ORIGINS` to
  re-enable it for specific origins (or `*`).
- **NodeSource install is opt-in.** Node.js installation on Debian/Ubuntu no
  longer pipes a downloaded shell script into `sudo bash` by default; the distro
  package is used instead. Set `ANDRO_CFW_ALLOW_NODESOURCE=1` for the old
  behavior. `ANDRO_CFW_NO_AUTO_INSTALL=1` disables automatic installs entirely.
- **Bot tokens are no longer echoed.** The token prompt uses `getpass`, and
  `$TELEGRAM_BOT_TOKEN` is preferred over `--token` (argv is world-readable).
- **Tighter file modes.** `~/.andro_cfw` and the per-account wrangler OAuth
  directories are created `0700`; the Fernet key stays `0600`.
- **Account labels are validated** so they cannot escape `~/.andro_cfw/accounts`.
- **URL schemes are pinned** to http/https before any `urlopen` call.

### ⚡ Added

- **Self-hosted Bot API support (`UPSTREAM_API_ORIGIN`).** The worker proxied to
  a hardcoded `api.telegram.org`; it can now target your own
  [`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) instance, which
  lifts Telegram's 50 MB upload cap. Only the origin is used, and a malformed or
  non-http(s) value falls back to Telegram rather than sending traffic somewhere
  unintended.
- **The load balancer streams payloads instead of buffering them.** Response
  bodies are relayed in 64 KB chunks — only the first 512 bytes are held, to
  recognise a Cloudflare quota page. Request bodies stay in memory up to 1 MB and
  spill to a temp file above that, so concurrent file transfers no longer pin
  tens of megabytes of RAM while remaining replayable for quota failover.
  Chunked upstream responses (no `Content-Length` after urllib decodes them) are
  delimited with `Connection: close`, and `HEAD` correctly sends no body.

### 🐛 Fixed

- **`andro_cfw.patch()` actually works now.** The `aiogram`,
  `python-telegram-bot`, `pyrogram` and `hydrogram` branches were all no-ops: a
  bot called `patch()`, saw no error, and talked directly to `api.telegram.org`.
  - `aiogram`: mutates the shared `PRODUCTION` server object, which is what
    `BaseSession.__init__` binds as a default argument.
  - `python-telegram-bot`: wraps `Bot.__init__`, since PTB bakes its base URL
    into the signature and `ApplicationBuilder` always passes one explicitly.
  - `pyrogram` / `hydrogram` / `telethon`: **removed.** These speak MTProto, not
    the HTTP Bot API, so an HTTP proxy cannot route them. `patch()` now emits a
    `RuntimeWarning` instead of silently doing nothing, and
    `andro-cfw snippet -f pyrogram` refuses rather than emitting misleading code.
- **`setWebhook` result is parsed.** Registration was reported as successful on
  any HTTP 200, but the Bot API returns `{"ok": false, ...}` with status 200 for
  most rejections.
- **Session writes are atomic** (temp file + `fsync` + `os.replace`). The load
  balancer persists quota state from request threads; an interleaved write could
  leave an undecryptable `cfw.session` and force a full re-init.
- **Load balancer returns a framed 503** when every account is down. The
  previous unframed HTTP/1.1 response left the client hanging until timeout.
- **`CFWSession.load()` tolerates unknown fields**, so an older install can read
  a session written by a newer one instead of raising `TypeError`.
- **`api_base_url()` raises an actionable error** on a session with no worker,
  instead of `AttributeError: 'NoneType' object has no attribute 'rstrip'`.
- **Hop-by-hop headers are no longer relayed** in either direction, and
  `Accept-Encoding` is stripped upstream so quota detection reads text, not gzip.
- **Request bodies are capped** at 64 MB instead of allocating whatever
  `Content-Length` claims.
- **`LoadBalancer.stop()` closes the listening socket** and joins its thread.
- **Session persistence happens outside the balancer lock**, so a disk write no
  longer serializes every in-flight proxied request.
- **`check_health()` honors `http://` URLs** and always closes its connection.
- **Version is single-sourced** from package metadata. The `v0.3.2` tag shipped
  code reporting `0.3.0`; `andro-cfw --version` now cannot drift.

### 💥 Breaking

- The shipped `worker.ts` no longer contains the hardcoded demo bot that replied
  to `/start`, `/ping`, `/status` and `/echo` with "I'm Useless" text. The
  template is a proxy and a webhook relay; put your bot logic behind
  `FORWARD_WEBHOOK_URL` or write your own worker.
- `SECRET_TOKEN` was renamed to `WEBHOOK_SECRET`.
- `andro-cfw serverless` dropped `--bot-file` (it only printed a message) and
  `--yes`, and gained `--forward-url`.
- `andro-cfw snippet` no longer offers `pyrogram` / `hydrogram`; a new `patch`
  snippet demonstrates the one-line integration.

### 🧪 Testing & tooling

- 76 → **133 tests**. The four `patch()` tests previously asserted against
  `MagicMock`, which auto-creates any attribute touched — they passed no matter
  what the code did. They now use real modules and real frozen dataclasses.
- New coverage: end-to-end load-balancer failover over a real socket, concurrent
  session persistence, atomic-write rollback, webhook secret generation, token
  validation, path-traversal rejection, and file-mode assertions.
- CI now gates on **ruff** and **mypy**, and runs on macOS and Windows in
  addition to Linux (`platform_utils.py` branches per OS and was Linux-only
  tested). Python 3.13 added to the matrix.
- Ships `py.typed`.

---

## [v0.3.0] - 2026-07-25

### 🚀 Added
- **100% Serverless Cloudflare Edge Engine (`andro-cfw serverless`)**:
  - Added `andro-cfw serverless` command (aliases: `deploy-serverless`, `deploy-webhook`) to deploy 24/7 serverless Telegram bots to Cloudflare Edge in under 30 seconds.
  - Added built-in serverless bot handlers for `/start`, `/help`, `/ping`, `/status`, and `/echo <text>`.
  - Added dynamic `token` parameter extraction from query strings (`?token=...`) and path patterns (`/webhook/...`).
  - Added zero-VPN automated `setWebhook` registration through the worker proxy endpoint.
- **Universal Framework Auto-Patcher (`andro_cfw.patch()`)**:
  - Added 1-line universal framework auto-detection and patching for `telebot`, `pyrogram`, `hydrogram`, `aiogram` (v2 & v3), and `python-telegram-bot` (`telegram`).
- **Downstream Webhook Forwarding (`FORWARD_WEBHOOK_URL`)**:
  - Added `FORWARD_WEBHOOK_URL` support to `templates/worker.ts` to allow Cloudflare Workers to act as an unfiltered reverse proxy for external PHP, Node.js, Python, or Go webhook backends.
- **Automated CI/CD & PyPI Release Pipelines**:
  - Added `.github/workflows/release-and-changelog.yml` with OIDC Trusted Publisher integration to automatically publish tagged releases to PyPI.
  - Added `.github/workflows/ci.yml` for multi-Python matrix testing (Python 3.9, 3.10, 3.11, 3.12).
- **Comprehensive Documentation & Multi-Language Guides**:
  - Added 4-method complete working guides (Python, TS/JS Worker, PHP/Forwarding, 1-command CLI) to `README.md`, `README.fa.md`, and `README.en.md`.

### ⚡ Performance & Optimization
- **10x Faster Ping Latency Measurement**:
  - Upgraded `check_health()` in `andro_cfw/session.py` to use HTTP Keep-Alive socket connection pooling, dropping measured ping times from ~500ms to **~59ms**.
- **Long-Polling Socket Alignment**:
  - Configured `READ_TIMEOUT = 60` and `CUSTOM_REQUEST_TIMEOUT = (10, 60)` for `telebot` in `andro_cfw/patcher.py` to prevent false socket read timeouts during 30s long-polling cycles.

### 🛡️ Security & Reliability
- **Header Parsing Guard**:
  - Wrapped `Content-Length` header parsing in `andro_cfw/loadbalancer.py` in try-except guards to prevent unhandled `ValueError` crashes on malformed client headers.
- **Worker Error Boundary & CORS**:
  - Added 502 Bad Gateway JSON error boundaries and `OPTIONS` preflight CORS handling to `templates/worker.ts`.
  - Added `X-Telegram-Bot-Api-Secret-Token` header verification for `/webhook` endpoints when `SECRET_TOKEN` is configured.
- **Protected Managed Symlinks**:
  - Updated `platform_utils.py` to prevent `setup-path` from overwriting `pipx`-managed symlinks in `~/.local/bin/andro-cfw`.

### 🧪 Test Suite
- **Expanded to 76 Passing Unit Tests**:
  - Added test coverage for `andro_cfw/colors.py` (ANSI formatting & non-TTY safety).
  - Added test coverage for `andro_cfw/templates.py` (`worker.ts` template structure).
  - Added test coverage for `aiogram` and `telegram` mock patchers in `tests/test_patcher.py`.
  - Added test coverage for invalid `Content-Length` header handling in `tests/test_loadbalancer.py`.
  - Added test coverage for `cmd_deploy_serverless` CLI command in `tests/test_cli.py`.

---

## [v0.2.1] - 2026-07-24

### 🚀 Added
- ANSI Terminal Colors & `ColoredHelpFormatter` in `andro_cfw/colors.py`.
- Safe Cross-Platform PATH Registration (`andro-cfw setup-path`) for POSIX shells and Windows Registry.
- Clean Ctrl+C (`KeyboardInterrupt`) termination in CLI with exit code `130`.

---

## [v0.2.0] - 2026-07-20

### 🚀 Added
- Multi-Account Load Balancing pool support (`andro-cfw init --accounts N` and `andro-cfw add-account`).
- Automatic daily quota failover (100k requests/day free tier per Cloudflare account) with automatic UTC midnight resets.
- Code snippet generator command (`andro-cfw snippet -f <framework>`).
- Encrypted session storage (`cfw.session`) using AES-128-CBC + HMAC via Fernet cryptography.

---

## [v0.1.0] - 2026-07-10

### 🚀 Initial Release
- Core reverse proxy Worker template (`templates/worker.ts`).
- Interactive Cloudflare OAuth login flow via `wrangler login`.
- Basic project initialization (`andro-cfw init`) and removal (`andro-cfw remove`).
