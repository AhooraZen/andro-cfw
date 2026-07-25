# Plan 005 — Add Header Parsing & ValueError Guard to Local Load Balancer

- **Target commit**: `e1946fa`
- **Goal**: Harden `LoadBalancer._proxy_request()` against malformed or non-numeric `Content-Length` headers in incoming HTTP requests to prevent unhandled `ValueError` crashes.

---

## 1. Context & Motivation

In `andro_cfw/loadbalancer.py`, `_proxy_request()` parses incoming HTTP headers before proxying traffic to Cloudflare Workers:

```python
content_length = int(handler.headers.get("Content-Length", 0) or 0)
```

If a client or proxy sends a malformed `Content-Length` header (such as `chunked` or invalid strings), `int(...)` throws an unhandled `ValueError` that interrupts the HTTP request handler thread.

---

## 2. In-Scope Files

- `andro_cfw/loadbalancer.py`
- `tests/test_loadbalancer.py`

---

## 3. Implementation Steps

### Step 1: Update `andro_cfw/loadbalancer.py`
Wrap `int(...)` conversion in a try-except block in `_proxy_request()`:

```python
try:
    content_length = int(handler.headers.get("Content-Length", 0) or 0)
except (ValueError, TypeError):
    content_length = 0
```

### Step 2: Add Unit Test in `tests/test_loadbalancer.py`
Add a unit test in `tests/test_loadbalancer.py` simulating an incoming request with a malformed `Content-Length: invalid` header and verifying the load balancer handles it safely without crashing.

---

## 4. Verification Gate

```bash
uv run --with pytest pytest
```

Expected output: `74 passed` (or higher).

---

## 5. Done Criteria

- [ ] Unhandled `ValueError` from malformed `Content-Length` headers is safely caught and defaults `content_length` to 0.
- [ ] New unit test added to `tests/test_loadbalancer.py` asserting non-numeric `Content-Length` handling.
- [ ] All 74+ unit tests pass cleanly.
