# Plan 001: Fix Test Mock Artifact Leaks and Add Wrapper Generation Unit Test

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3608474..HEAD -- tests/test_loadbalancer.py tests/test_platform_utils.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests | dx
- **Planned at**: commit `3608474`, 2026-07-25
- **Issue**: none

## Why this matters
Running `pytest` currently creates untracked files like `<MagicMock id='139787570137808'>` in the repository root directory because tests mock `_session_path` with a `MagicMock` object without setting string path properties or isolating filesystem persistence. Additionally, the new `setup-path` CLI wrapper script auto-generation in `andro_cfw/platform_utils.py` needs explicit unit test coverage to ensure cross-platform regression safety.

## Current state
- `tests/test_loadbalancer.py` (lines 50, 134, 154) mocks `_session_path` as a plain `MagicMock()`. When `LoadBalancer._mark_exhausted` calls `self.session._persist()`, `session._session_path` is cast to string as `"<MagicMock id='...'>"`, creating untracked files in the root folder.
- `tests/test_platform_utils.py` contains tests for `_add_to_posix_user_path` and `_add_to_windows_user_path`, but does not test `andro-cfw` executable script wrapper auto-creation (`~/.local/bin/andro-cfw` and `Scripts/andro-cfw.cmd`).

## Commands you will need
| Purpose | Command | Expected on success |
|-----------|--------------------------|---------------------|
| Run tests | `uv run --with pytest pytest` | exit 0, 64+ passed |
| Check git status | `git status --porcelain` | exit 0, no untracked `<MagicMock...>` files |

## Scope
**In scope**:
- `tests/test_loadbalancer.py`
- `tests/test_platform_utils.py`

**Out of scope**:
- `andro_cfw/` source files (tests only)

## Steps

### Step 1: Clean up mock session path handling in `tests/test_loadbalancer.py`
Replace `session._session_path = MagicMock()` with a mock that points to a temporary file path created via `tmp_path`, or mock `session.save` / `session._persist` in `test_loadbalancer.py`.

```python
# Use tmp_path in test_loadbalancer.py fixtures or set _session_path to tmp_path / "cfw.session"
session._session_path = tmp_path / "cfw.session"
```

**Verify**:
Run `uv run --with pytest pytest` then `git status --porcelain` to verify no `<MagicMock...>` files are generated.

### Step 2: Add unit tests for CLI wrapper creation in `tests/test_platform_utils.py`
Add explicit test cases `test_add_to_posix_user_path_creates_executable_wrapper` and `test_add_to_windows_user_path_creates_cmd_wrapper` to `tests/test_platform_utils.py`.

```python
def test_add_to_posix_user_path_creates_executable_wrapper(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc_file = tmp_path / ".zshrc"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    target_dir = tmp_path / ".local" / "bin"
    assert _add_to_posix_user_path(target_dir) is True
    wrapper = target_dir / "andro-cfw"
    assert wrapper.exists()
    assert "#!/bin/sh" in wrapper.read_text()
    assert "exec" in wrapper.read_text()
```

**Verify**: `uv run --with pytest pytest` passes all tests.

## Done criteria
- [ ] `uv run --with pytest pytest` passes 64+ unit tests cleanly.
- [ ] `git status --porcelain` produces zero untracked `<MagicMock...>` files after running tests.
- [ ] Unit tests for POSIX and Windows wrapper script creation exist in `tests/test_platform_utils.py`.
- [ ] `plans/README.md` status updated.

## STOP conditions
- If existing tests fail before edits, verify environment.
