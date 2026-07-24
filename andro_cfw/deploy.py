from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Optional

from .errors import DeploymentError
from .toolchain import check_node_toolchain

WORKERS_DEV_URL_RE = re.compile(r"https?://[a-zA-Z0-9.\-]+\.workers\.dev")


def _random_worker_name() -> str:
    return "andro-cfw-" + secrets.token_hex(4)


def _load_template(name: str) -> str:
    return resources.files("andro_cfw.templates").joinpath(name).read_text(encoding="utf-8")


def deploy_worker(worker_name: Optional[str] = None) -> tuple[str, str]:
    """
    Build a minimal Cloudflare Worker project in a temp directory and
    deploy it with `wrangler deploy`. Returns (worker_name, worker_url).

    Requires the user to already be authenticated (see auth.cloudflare_login).
    """
    check_node_toolchain()

    worker_name = worker_name or _random_worker_name()

    with tempfile.TemporaryDirectory(prefix="andro-cfw-") as tmp:
        tmp_path = Path(tmp)

        worker_ts = _load_template("worker.ts")
        wrangler_tmpl = _load_template("wrangler.toml.tmpl")

        (tmp_path / "worker.ts").write_text(worker_ts, encoding="utf-8")
        (tmp_path / "wrangler.toml").write_text(
            wrangler_tmpl.format(worker_name=worker_name), encoding="utf-8"
        )

        print(f"[andro-cfw] Deploying Cloudflare Worker '{worker_name}'...")
        result = subprocess.run(
            ["npx", "--yes", "wrangler", "deploy"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        combined_output = result.stdout + "\n" + result.stderr

        if result.returncode != 0:
            raise DeploymentError(
                "Failed to deploy the Cloudflare Worker.\n\n"
                f"--- wrangler output ---\n{combined_output}\n"
                "Make sure you ran `andro-cfw init` and completed the Cloudflare "
                "login step, then try again."
            )

        match = WORKERS_DEV_URL_RE.search(combined_output)
        if not match:
            raise DeploymentError(
                "Worker deployed but the workers.dev URL could not be detected "
                "in wrangler's output. Check your Cloudflare dashboard "
                "(Workers & Pages) to find the URL manually.\n\n"
                f"--- wrangler output ---\n{combined_output}"
            )

        worker_url = match.group(0)
        return worker_name, worker_url


def teardown_worker(worker_name: str) -> None:
    """Delete a previously deployed worker (used by `andro-cfw remove`)."""
    check_node_toolchain()
    subprocess.run(
        ["npx", "--yes", "wrangler", "delete", "--name", worker_name, "--force"],
        capture_output=True,
        text=True,
    )
