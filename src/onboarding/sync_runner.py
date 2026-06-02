"""First-sync runners for onboarding flows."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.onboarding.config_bridge import export_local_clients_config


class OnboardingFirstSyncRunner(Protocol):
    """Run first sync for a selected onboarding draft."""

    def __call__(self, sync_job: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        """Run sync and return safe execution metadata."""


class LocalMetaSyncRunner:
    """Run Meta sync from a locally exported onboarding config artifact."""

    def __init__(
        self,
        *,
        config_path: Path | str,
        repo_root: Path | str,
        python_bin: str | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        self.config_path = Path(config_path)
        self.repo_root = Path(repo_root)
        self.python_bin = python_bin or sys.executable
        self.timeout_seconds = timeout_seconds

    def __call__(self, sync_job: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        """Export selected accounts and run the Meta sync entrypoint."""
        started_at = _utc_now()
        export = export_local_clients_config(selection, self.config_path)
        env = {
            **os.environ,
            "CLIENTS_CONFIG_PATH": str(self.config_path),
            "SYNC_ENABLED_PLATFORMS": "meta_ads",
        }
        completed = subprocess.run(
            [self.python_bin, "-m", "src.main"],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("local_meta_sync_failed")

        return {
            "runner": "local_meta_sync",
            "status": "success",
            "started_at": started_at,
            "finished_at": _utc_now(),
            "account_count": export.account_count,
            "destination_count": len(export.destinations),
            "config_path": str(self.config_path),
            "writes_bigquery": True,
            "return_code": completed.returncode,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
