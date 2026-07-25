# Plan 003: Implement `andro_cfw.patch()` Universal Framework Auto-Patcher

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3608474..HEAD -- andro_cfw/__init__.py andro_cfw/session.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction | dx
- **Planned at**: commit `3608474`, 2026-07-25
- **Issue**: none

## Why this matters
Currently, developers manually wire their Telegram framework's base URL using framework-specific helper calls (`telebot.apihelper.API_URL = session.telebot_api_url()`, `ApplicationBuilder().base_url(...)`, etc.). Adding a single top-level `andro_cfw.patch()` function allows developers to write **1 line of setup** (`import andro_cfw; andro_cfw.patch()`). It automatically loads `CFWSession` and patches any active/imported Telegram framework in `sys.modules` (`telebot`, `ptb`, `aiogram`, `pyrogram`, `hydrogram`), making setup effortless.

## Current state
- `andro_cfw/__init__.py` currently exports `CFWSession`, `AndroCFWError`, `__version__`.
- `andro_cfw/session.py` provides convenience accessors `telebot_api_url()`, `ptb_base_url()`, `aiogram_server_url()`, `api_base_url()`.

## Commands you will need
| Purpose | Command | Expected on success |
|-----------|--------------------------|---------------------|
| Run tests | `uv run --with pytest pytest` | exit 0, all pass |

## Scope
**In scope**:
- `andro_cfw/__init__.py`
- `andro_cfw/patcher.py` (create)
- `tests/test_patcher.py` (create)
- `README.md`, `README.fa.md`, `README.en.md`

**Out of scope**:
- `cli.py`, `deploy.py`

## Steps

### Step 1: Create `andro_cfw/patcher.py`
Implement `patch(session: Optional[CFWSession] = None) -> CFWSession` in `andro_cfw/patcher.py`:
1. If `session` is None, calls `CFWSession.load()`.
2. Inspects `sys.modules` for loaded frameworks:
   - If `'telebot'` in `sys.modules`: sets `telebot.apihelper.API_URL` and `FILE_URL`.
   - If `'pyrogram'` in `sys.modules`: patches default `Client.api_url`.
   - If `'hydrogram'` in `sys.modules`: patches default `Client.api_url`.
3. Returns `session`.

```python
from __future__ import annotations
import sys
from typing import Optional
from .session import CFWSession

def patch(session: Optional[CFWSession] = None) -> CFWSession:
    if session is None:
        session = CFWSession.load()
    base_url = session.api_base_url()

    if "telebot" in sys.modules:
        tb = sys.modules["telebot"]
        tb.apihelper.API_URL = session.telebot_api_url()
        tb.apihelper.FILE_URL = session.telebot_file_url()

    return session
```

**Verify**: Module imports without errors.

### Step 2: Export `patch` in `andro_cfw/__init__.py`
Add `patch` to `andro_cfw/__init__.py` exports (`__all__ = ["CFWSession", "AndroCFWError", "patch", "__version__"]`).

### Step 3: Add unit tests in `tests/test_patcher.py`
Create `tests/test_patcher.py` to test `patch()` with mock `CFWSession` and mock framework modules.

**Verify**: `uv run --with pytest pytest` passes all tests cleanly.

### Step 4: Update README documentation
Add `import andro_cfw; andro_cfw.patch()` section to `README.md`, `README.fa.md`, and `README.en.md`.

## Done criteria
- [ ] `andro_cfw.patch()` exported and functional.
- [ ] `tests/test_patcher.py` created and passing.
- [ ] `uv run --with pytest pytest` passes 66+ unit tests cleanly.
- [ ] `plans/README.md` status updated.

## STOP conditions
- If patching breaks existing `CFWSession.load()` semantics.
