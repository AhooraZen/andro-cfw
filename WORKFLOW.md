# WORKFLOW.md — andro-cfw Development & Release Workflow

Standard operating procedure for contributing, testing, and releasing `andro-cfw`.

## 1. Local Development Setup
```bash
git clone git@github.com:Andromeda-Collective/andro-cfw.git
cd andro-cfw
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## 2. Code & Fix Cycle
1. Create a feature branch: `git checkout -b feature/my-feature`
2. Implement minimum working code (follow **Ponytail** laziness & **Caveman** terseness principles)
3. Run the full verification gate — all three must pass:
   ```bash
   uv run --with pytest pytest      # 121 unit tests
   uvx ruff check andro_cfw tests
   uvx --with cryptography mypy andro_cfw
   ```
4. Verify code edits break 0 existing tests and maintain a 100% pass rate.

## 3. Release & PyPI Deployment Checklist
When preparing a new official release (e.g. `v0.4.0`):

1. **Bump Version**: Update `version` in `pyproject.toml` only. `andro_cfw.__version__` reads it from package metadata, so there is no second literal to keep in sync.
2. **Update Changelog**: Document new features, performance updates, security fixes, and test additions in `CHANGELOG.md`.
3. **Commit & Push PR**: Submit PR to `Andromeda-Collective/andro-cfw:main`.
4. **Publishing to PyPI (OIDC Trusted Publisher)**:
   - Once merged to `main`, push a version tag:
     ```bash
     git checkout main
     git pull
     git tag v0.4.0
     git push origin v0.4.0
     ```
   - GitHub Actions (`.github/workflows/release-and-changelog.yml`) will automatically build, create the GitHub Release, and publish to PyPI via OIDC tokenless authentication.
