# Changelog

All notable changes to the `andro-cfw` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### 🐛 Fixed

- **Webhook forwarding to another Cloudflare Worker silently dropped every
  update.** `handleWebhook` relayed with `fetch(env.FORWARD_WEBHOOK_URL, …)`,
  and a `fetch()` from one Worker to another Worker's `workers.dev` hostname is
  not dispatched to that Worker. Nothing threw: the relay looked healthy, the
  worker answered Telegram `200 OK`, `getWebhookInfo` reported no error, and the
  backend was never invoked. Confirmed from Workers logs — the target script
  recorded zero invocations while the proxy recorded one per update.

### ✨ Added

- **`FORWARD_SERVICE` service binding.** When bound, `/webhook` relays through
  it instead of `FORWARD_WEBHOOK_URL`, which is the only reliable way to reach
  another Worker. `FORWARD_WEBHOOK_URL` is unchanged and still correct for an
  ordinary HTTP backend.
- **A non-2xx from the forward target is now logged.** Previously only a thrown
  exception was, so a backend answering 500 was indistinguishable from success.
- **The webhook secret is passed through to the forward target.** A backend's
  own URL is usually public, and without the header it had no way to tell a
  relayed update from one someone POSTed at it directly.

---

## [v1.0.0] - 2026-07-26

The release that removes Node.js. **Contains breaking changes** — every user
must re-authenticate; see the migration notes at the end of this entry.

### 💥 Breaking

- **`wrangler` and Node.js are gone.** Every Cloudflare operation used to shell
  out to `npx wrangler`, which meant the package had to put a working Node.js on
  the user's machine first: ~250 lines in `andro_cfw/toolchain.py` that probed
  for `apt` / `dnf` / `pacman` / `zypper` / `apk` / `brew` / `winget`, ran the
  matching install command, and — on Debian and Ubuntu — could pipe a downloaded
  NodeSource shell script into `sudo bash`. Deploying a Worker is a handful of
  ordinary HTTPS calls, so none of that was ever necessary. Installing
  andro-cfw is now `pip install andro-cfw` and nothing else.
- **Authentication is a Cloudflare API token, not `wrangler login`.** The OAuth
  browser flow (`andro_cfw/auth.py`, per-account `WRANGLER_HOME` directories) is
  replaced by **`andro-cfw login`**. Create a token at
  <https://dash.cloudflare.com/profile/api-tokens> → Create Token → the
  **"Edit Cloudflare Workers"** template, which grants exactly
  `Workers Scripts:Edit`. **Every 0.4.x user must run `andro-cfw login` once per
  account before any command that touches Cloudflare will work.**
- **Modules deleted:** `andro_cfw/auth.py`, `andro_cfw/toolchain.py`,
  `andro_cfw/templates/worker.ts`, `andro_cfw/templates/wrangler.toml.tmpl`.
- **The worker template is `worker.mjs`,** plain ES module JavaScript. The
  Workers upload API has no bundler and will not accept TypeScript, so the
  source that ships must already be valid JavaScript. Custom workers written in
  TypeScript now have to be compiled before upload.
- **`ANDRO_CFW_ALLOW_NODESOURCE` and `ANDRO_CFW_NO_AUTO_INSTALL` no longer
  exist.** Both existed to control an installer that is gone; they are silently
  ignored and can be dropped from shell profiles.
- **The per-process load balancer is replaced by a shared daemon.**
  `andro-cfw daemon` is now the supported way to run a multi-account pool.

### 🔐 Browser login (optional)

- **`andro-cfw login --browser`** runs Cloudflare's OAuth 2.0 authorization-code
  flow with PKCE, in pure Python — no Node, no wrangler. The credential is
  issued on Cloudflare's own domain, the consent screen lists the exact scopes,
  and what is stored is a short-lived access token plus a refresh token that
  `client_for()` renews transparently before it expires.
- Scopes requested are the minimum to deploy a Worker and set its secrets:
  `account:read`, `user:read`, `workers:write`, `workers_scripts:write`,
  `workers_routes:write`, `offline_access`. No KV, R2, D1 or zone access.
- **`andro-cfw logout`** revokes the grant with Cloudflare and forgets it.
- The browser flow needs an OAuth client id (`ANDRO_CFW_OAUTH_CLIENT_ID`), which
  andro-cfw does not ship. Reusing wrangler's public client id would work, but
  Cloudflare's consent screen names the application being authorised: users
  would be told *Wrangler* wants access, and the grant would file under Wrangler
  in their authorised-applications list. A test asserts that id never appears in
  the source.
- Pasting an API token remains the default and the only headless option.

### 🔒 Security

- **No code path can install software or ask for `sudo` any more.** The removal
  of `toolchain.py` takes with it the `curl … | sudo bash` NodeSource path
  (opt-in since v0.4.0, but still present), every system package-manager
  invocation, and the privilege escalation they required. andro-cfw is now a
  pure-Python package that makes HTTPS requests.
- **API tokens are stored encrypted.** `~/.andro_cfw/credentials` is Fernet
  encrypted with the same local key that protects `cfw.session` and written
  `0600`. Previously, wrangler's OAuth refresh tokens sat in plaintext JSON in
  the per-account config directories.
- **Least-privilege credentials.** The recommended "Edit Cloudflare Workers"
  token scope cannot read DNS records, zones, or billing — unlike an OAuth
  session, which carried the full permissions of the logged-in dashboard user.
  Cloudflare error codes 10000/9109 are recognised and answered with the exact
  token-creation instructions instead of a raw API dump.
- **The daemon and its dashboard bind to `127.0.0.1` only.**
- **Secret values are never echoed on failure.** `put_worker_secret()` reports
  the binding name and the Cloudflare error, never the value it tried to store.

### ⚡ Added

- **`andro-cfw daemon` — one shared local proxy per machine.** Every bot process
  used to start its own load balancer. Three bots meant three balancers: each
  independently discovering a 429, all writing to the same session file, none
  aware of what the others had already consumed. The daemon is a single
  long-lived proxy that all of them share, so there is one set of counters, one
  health view, and one failover decision.
- **Exact request accounting (`andro_cfw/store.py`).** Because the daemon
  proxies every request, it counts them: per worker, per UTC day, in SQLite at
  `~/.andro_cfw/usage.db` (WAL mode, so the dashboard can read while requests
  are being recorded; history is pruned to a retention window so the samples
  table does not grow forever under long polling).
- **Quota-aware rotation before the limit, not after the failure.** An account
  is retired at **95%** of the free plan's 100,000 requests/day. Previously
  there was no request counting at all — failover was purely reactive, so every
  single switch cost one failed request.
- **Latency-aware worker selection.** The daemon picks the healthy worker with
  the lowest *median* recent latency rather than the lowest index. Median, not
  mean, so one 30-second timeout cannot disqualify an otherwise good account.
- **Transient 5xx responses are retried with backoff** inside the daemon instead
  of being handed to the bot as an error.
- **Local dashboard at `http://127.0.0.1:<port>/__andro/`,** served by the
  daemon itself: worker health, quota consumption per account, a latency chart,
  and a failover event log. No external assets, loopback only.
- **`andro-cfw logs`** prints the same failover/quota/retry event log in the
  terminal.
- **`andro-cfw login`** verifies the token against `/user/tokens/verify`,
  resolves the account id, and stores both encrypted. A token with access to
  several accounts lists them and asks for `--account-id` rather than guessing
  one.
- **`andro_cfw/cloudflare.py` — a minimal Cloudflare REST client.** Upload,
  workers.dev route, secrets, delete, subdomain and account lookup, over
  `urllib` with a hand-rolled multipart encoder. No new runtime dependency.

### 🐛 Fixed

- **A bot whose HTTP client sends no `User-Agent` was silently unreachable.**
  urllib stamps `Python-urllib/3.x` on such requests, and Cloudflare's Browser
  Integrity Check answers that exact signature with `403 error 1010` before the
  request reaches the Worker at all. A neutral agent is now substituted when —
  and only when — the client sent none. Found on the first live end-to-end run;
  no unit test could have caught it, since it depends on Cloudflare's edge.
- **Quota exhaustion no longer costs a request.** See above: the old balancer
  could only learn an account was out of quota by being told `429`, so each
  rotation surfaced one failure to the bot.
- **Concurrent bots no longer fight over quota state.** Independent balancers
  writing overlapping `exhausted_until` / `active_index` values to one session
  file produced decisions based on each process's partial view; the daemon owns
  that state.
- **Re-uploading a worker no longer wipes its secrets.** The upload sends
  `keep_bindings: ["secret_text"]`, so `BOT_TOKEN` and `WEBHOOK_SECRET` survive
  a redeploy.
- **A brand-new `workers.dev` hostname is waited for.** The API returns before
  DNS has propagated, which made a perfectly good deploy look broken; deploys
  now poll for up to 45 seconds and say so plainly if it is still not resolving.
- **An account with no `workers.dev` subdomain gets an actionable message**
  telling the user to claim one in the dashboard, instead of a failed deploy
  with an empty hostname.
- **Cloudflare connectivity errors distinguish themselves from Telegram's.**
  `api.cloudflare.com` is not usually filtered even where `api.telegram.org` is,
  so a failure there means a genuine network problem and now says that.

### 🧪 Testing & tooling

- `tests/test_auth.py` and `tests/test_toolchain.py` are deleted along with the
  modules they covered — roughly a fifth of the suite existed to test an
  installer that no longer ships.
- New coverage for the REST client (multipart encoding, error-code hinting,
  account resolution, `keep_bindings`), for the usage store (daily rollover on
  the UTC boundary, median latency, retention pruning), and for the daemon's
  pre-emptive rotation at the headroom threshold.
- Documentation rewritten across `README.md`, `README.en.md` and `README.fa.md`:
  installation, authentication, the daemon, the dashboard, and a migration
  section for 0.4.x users.

### 📦 Distribution

- **Not published to PyPI, deliberately.** This is a personal tool. Install it
  from the repository (`pip install git+https://github.com/AhooraZen/andro-cfw.git`)
  or from the wheel attached to a GitHub release. The release workflow no longer
  has a PyPI step, and `pyproject.toml` carries the `Private :: Do Not Upload`
  classifier, which PyPI rejects — so an accidental publish cannot happen even
  by hand.

### 🧭 Migrating from 0.4.x

1. Run **`andro-cfw login`** with a token from the "Edit Cloudflare Workers"
   template — once per Cloudflare account if you run a pool.
2. Your existing `cfw.session` keeps working; no re-deploy is required.
3. Start **`andro-cfw daemon`** if you want counting, early rotation and the
   dashboard. Bots work without it, they are simply not accounted for.
4. Node.js installed by an older andro-cfw can be uninstalled.

> **Known limitation:** webhook traffic travels from Telegram directly to the
> Worker and never passes through the daemon, so the counters and the dashboard
> cover long-polling and outbound Bot API calls only. For a webhook-driven bot
> the reported usage reads low — Cloudflare's own dashboard is the authority
> there.

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

- 76 → **222 tests**. The four `patch()` tests previously asserted against
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
