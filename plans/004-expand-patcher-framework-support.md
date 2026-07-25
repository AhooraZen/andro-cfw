# Plan 004 — Expand `andro_cfw.patch()` Framework Support & Edge Case Handling

- **Target commit**: `e1946fa`
- **Goal**: Expand `andro_cfw.patch()` to automatically patch `aiogram` (v2 & v3) and `python-telegram-bot` (`telegram`) when imported in `sys.modules`, matching the framework list promised in documentation and snippet generator.

---

## 1. Context & Motivation

`andro_cfw.patch()` provides a 1-line auto-detection and patching API for Telegram bot frameworks.
Currently, `andro_cfw/patcher.py` handles `telebot`, `pyrogram`, and `hydrogram`. However, `aiogram` and `python-telegram-bot` (`telegram`) are documented in the README and snippet generator but need explicit auto-patching logic in `andro_cfw/patcher.py`.

---

## 2. In-Scope Files

- `andro_cfw/patcher.py`
- `tests/test_patcher.py`

---

## 3. Implementation Steps

### Step 1: Update `andro_cfw/patcher.py`
Add detection for `aiogram` and `telegram` in `sys.modules`:

```python
    # 4. aiogram (v2 & v3)
    if "aiogram" in sys.modules:
        aio = sys.modules["aiogram"]
        if hasattr(aio, "client") and hasattr(aio.client, "telegram") and hasattr(aio.client.telegram, "TelegramAPIServer"):
            server_urls = session.aiogram_server_url()
            aio.client.telegram.TelegramAPIServer.from_base(server_urls["base"])

    # 5. python-telegram-bot (telegram)
    if "telegram" in sys.modules:
        tg = sys.modules["telegram"]
        if hasattr(tg, "Bot") and hasattr(tg.Bot, "_base_url"):
            tg.Bot._base_url = base_url
```

### Step 2: Add Unit Tests in `tests/test_patcher.py`
Add tests verifying mock modules for `aiogram` and `telegram` are correctly patched when present in `sys.modules`.

---

## 4. Verification Gate

```bash
uv run --with pytest pytest
```

Expected output: `74 passed` (or higher).

---

## 5. Done Criteria

- [ ] `andro_cfw.patch()` correctly inspects and patches `aiogram` and `telegram` if present in `sys.modules`.
- [ ] No regression on `telebot`, `pyrogram`, or `hydrogram` patching.
- [ ] All unit tests pass cleanly.
