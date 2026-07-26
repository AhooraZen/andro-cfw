# GEMINI.md — andro-cfw Context & Conventions

Repository guide for Google Antigravity (AGY) & Gemini coding agents.

## Project Summary
`andro-cfw`: Python library & CLI tool deploying Cloudflare Workers as unfiltered reverse proxies and 24/7 serverless webhook engines for Telegram bots in restricted regions (e.g. Iran). Zero VPN required, and since v1.0.0 zero Node.js — deployment talks to the Cloudflare REST API directly.

## Toolchain & Stack
- **Language**: Python 3.9+ (core CLI/library), plain ES module JavaScript (Cloudflare Worker template — the upload API has no bundler, so no TypeScript)
- **Package Manager**: `uv` for Python (`uv pip install`, `uv run`, `uv build`). No JS toolchain: the package has no build step for the worker and installs nothing outside the venv.
- **Runtime dependencies**: `cryptography` only. HTTP is stdlib `urllib`; usage accounting is stdlib `sqlite3`.
- **Cloudflare auth**: scoped API token ("Edit Cloudflare Workers" template), stored Fernet-encrypted at `~/.andro_cfw/credentials` (0600)
- **Testing**: `uv run --with pytest pytest` (222 unit tests in `tests/`)
- **Lint / types**: `uvx ruff check andro_cfw tests` and `uvx --with cryptography mypy andro_cfw` — both gate CI
- **Code Search**: `rg` (ripgrep)
- **Secrets**: Never commit raw tokens, Cloudflare API tokens, or Fernet session keys

## Key Files & Layout
- `andro_cfw/cloudflare.py`: Minimal Cloudflare REST API client (token verify, account/subdomain lookup, worker upload, secrets, delete) + encrypted credential storage
- `andro_cfw/deploy.py`: `login()`, `deploy_worker()`, `put_worker_secret()`, `teardown_worker()` on top of the REST client
- `andro_cfw/store.py`: SQLite usage accounting for the daemon (`~/.andro_cfw/usage.db`) — per-worker/per-UTC-day request counts, latency samples, failover events
- `andro_cfw/loadbalancer.py`: Local HTTP proxy used by the shared daemon — quota-aware rotation at 95% of 100k/day, lowest-median-latency selection, 5xx retry with backoff
- `andro_cfw/patcher.py`: `andro_cfw.patch()` 1-line auto-patcher for `telebot`, `aiogram`, `telegram` (HTTP Bot API only; MTProto clients warn)
- `andro_cfw/session.py`: Encrypted `cfw.session` storage & health diagnostics (`check_health()`)
- `andro_cfw/templates/worker.mjs`: Dual-mode Cloudflare Worker template (reverse proxy + 24/7 serverless webhook relay)
- `andro_cfw/cli.py`: CLI entry points (`login`, `init`, `daemon`, `serverless`, `add-account`, `status`, `check`, `snippet`, `logs`, `remove`, `setup-path`)
- `plans/`: Monotonic implementation plan markdown files

## Behavioural Notes
- The daemon is shared machine-wide: one process, one set of counters. Do not reintroduce a per-process balancer.
- Its dashboard is served under the `/__andro` control prefix (default `http://127.0.0.1:8787/__andro/`); the daemon binds loopback only.
- Usage counts cover long-polling and outbound Bot API calls **only** — webhook updates go from Telegram straight to the Worker and never reach the daemon. Say so wherever the numbers are surfaced.

## Verification Commands
```bash
uv run --with pytest pytest
```
All code edits must maintain 100% test suite pass rate.
