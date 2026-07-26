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

That is the whole setup. As of v1.0.0 there is no JavaScript toolchain to
install: the Cloudflare Worker is deployed through the REST API from
`andro_cfw/cloudflare.py`, and `andro_cfw/templates/worker.mjs` is uploaded
as-is (the upload API has no bundler, so the template must stay plain ES module
JavaScript — do not convert it to TypeScript).

### Cloudflare credentials for manual testing
Create a token at <https://dash.cloudflare.com/profile/api-tokens> → Create
Token → **"Edit Cloudflare Workers"** template, then:
```bash
andro-cfw login          # stores it Fernet-encrypted at ~/.andro_cfw/credentials (0600)
andro-cfw init           # deploys a worker + writes cfw.session
andro-cfw daemon         # shared local proxy; dashboard at http://127.0.0.1:8787/__andro/
```
Never commit a token, a `cfw.session`, or `~/.andro_cfw/` contents.

## 2. Code & Fix Cycle
1. Create a feature branch: `git checkout -b feature/my-feature`
2. Implement minimum working code (follow **Ponytail** laziness & **Caveman** terseness principles)
3. Run the full verification gate — all three must pass:
   ```bash
   uv run --with pytest pytest      # 220 unit tests
   uvx ruff check andro_cfw tests
   uvx --with cryptography mypy andro_cfw
   ```
4. Verify code edits break 0 existing tests and maintain a 100% pass rate.

## 3. Release & PyPI Deployment Checklist
When preparing a new official release (e.g. `v1.0.0`):

1. **Bump Version**: Update `version` in `pyproject.toml` only. `andro_cfw.__version__` reads it from package metadata, so there is no second literal to keep in sync.
2. **Update Changelog**: Document new features, performance updates, security fixes, and test additions in `CHANGELOG.md`.
   Name the files that changed and explain why each change matters — match the depth of the existing entries.
3. **Update the docs**: `README.md` and `README.en.md` are kept byte-identical; `README.fa.md` is written natively in Persian, not translated.
4. **Commit & Push PR**: Submit PR to `Andromeda-Collective/andro-cfw:main`.
5. **Publishing to PyPI (OIDC Trusted Publisher)**:
   - Once merged to `main`, push a version tag:
     ```bash
     git checkout main
     git pull
     git tag v1.0.0
     git push origin v1.0.0
     ```
   - GitHub Actions (`.github/workflows/release-and-changelog.yml`) will automatically build, create the GitHub Release, and publish to PyPI via OIDC tokenless authentication.
