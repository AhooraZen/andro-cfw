# Plan 002: Suppress LoadBalancer Proxy Log Noise & Cleanup Code Quality

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3608474..HEAD -- andro_cfw/loadbalancer.py andro_cfw/cli.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: correctness | tech-debt
- **Planned at**: commit `3608474`, 2026-07-25
- **Issue**: none

## Why this matters
`ThreadingHTTPServer` / `BaseHTTPRequestHandler` in `andro_cfw/loadbalancer.py` outputs standard HTTP request log lines (`"GET /bot123/getMe HTTP/1.1" 200 -`) directly to `sys.stderr` for every request processed by the local proxy. When running Telegram bots, this floods the bot's terminal console with noisy HTTP log outputs. Overriding `log_message` in the custom request handler suppresses this unhelpful noise while keeping error handling intact. Additionally, `andro_cfw/cli.py:114` contains an inline `__import__("time")` call that should be cleaned up.

## Current state
- `andro_cfw/loadbalancer.py:80-200`: `_Handler` inherits from `BaseHTTPRequestHandler` without overriding `log_message(self, format, *args)`. Standard library default prints all proxy requests to stderr.
- `andro_cfw/cli.py:114`: calls `__import__("time").time()` inline during status string formatting.

## Commands you will need
| Purpose | Command | Expected on success |
|-----------|--------------------------|---------------------|
| Run tests | `uv run --with pytest pytest` | exit 0, all pass |

## Scope
**In scope**:
- `andro_cfw/loadbalancer.py`
- `andro_cfw/cli.py`

**Out of scope**:
- `session.py`, `auth.py`

## Steps

### Step 1: Override `log_message` in `_Handler` in `andro_cfw/loadbalancer.py`
Add `log_message` override to `_Handler` class in `andro_cfw/loadbalancer.py` to suppress standard HTTP access log lines while keeping server operations quiet.

```python
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:
        # Suppress standard HTTP access log lines to keep bot console output clean
        pass
```

**Verify**: `uv run --with pytest pytest` passes all loadbalancer tests.

### Step 2: Replace inline `__import__("time")` in `andro_cfw/cli.py`
Ensure `import time` is at top of `andro_cfw/cli.py` and replace inline `__import__("time").time()` at line 114 with `time.time()`.

**Verify**: `uv run --with pytest pytest` passes all tests.

## Done criteria
- [ ] `_Handler.log_message` in `andro_cfw/loadbalancer.py` suppresses default HTTP log spam.
- [ ] `__import__("time")` in `andro_cfw/cli.py` replaced with top-level `import time`.
- [ ] `uv run --with pytest pytest` passes all unit tests.
- [ ] `plans/README.md` status updated.

## STOP conditions
- If modifying `_Handler` breaks HTTP proxying response handling.
