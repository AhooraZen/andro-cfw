# Changelog

All notable changes to the `andro-cfw` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
