"""First-sync runners for onboarding flows."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from src.onboarding.config_bridge import export_local_clients_config
from src.onboarding.live_sync_readiness import inspect_live_sync_readiness


class OnboardingFirstSyncRunner(Protocol):
    """Run first sync for a selected onboarding draft."""

    def __call__(self, sync_job: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        """Run sync and return safe execution metadata."""


SUPPORTED_LOCAL_SYNC_PLATFORMS = {"meta_ads", "google_ads"}


class LocalPlatformSyncRunner:
    """Run a selected platform sync from a locally exported onboarding config artifact."""

    def __init__(
        self,
        *,
        platform: str,
        config_path: Path | str,
        repo_root: Path | str,
        python_bin: str | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        if platform not in SUPPORTED_LOCAL_SYNC_PLATFORMS:
            raise ValueError("platform must be 'meta_ads' or 'google_ads'.")
        self.platform = platform
        self.config_path = Path(config_path)
        self.repo_root = Path(repo_root)
        self.python_bin = python_bin or sys.executable
        self.timeout_seconds = timeout_seconds

    def __call__(self, sync_job: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        """Export selected accounts and run the platform sync entrypoint."""
        started_at = _utc_now()
        export = export_local_clients_config(selection, self.config_path)
        readiness = inspect_live_sync_readiness(
            platform=self.platform,
            config_path=self.config_path,
            local_sync_enabled=True,
            meta_access_token_configured=bool(os.getenv("META_ACCESS_TOKEN", "").strip()),
            google_ads_developer_token_configured=bool(os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()),
            google_ads_client_id_configured=bool(os.getenv("GOOGLE_ADS_CLIENT_ID", "").strip()),
            google_ads_client_secret_configured=bool(os.getenv("GOOGLE_ADS_CLIENT_SECRET", "").strip()),
            google_ads_refresh_token_configured=bool(os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()),
            gcp_project_id=os.getenv("GCP_PROJECT_ID", "").strip() or None,
            bigquery_dataset=os.getenv("BIGQUERY_DATASET", "").strip() or None,
            sync_enabled_platforms=self.platform,
            refresh_reporting_marts=os.getenv("REFRESH_REPORTING_MARTS"),
        ).as_dict()
        if not readiness["ready"]:
            raise RuntimeError(f"local_{_platform_error_slug(self.platform)}_sync_not_ready")
        env = {
            **os.environ,
            "CLIENTS_CONFIG_PATH": str(self.config_path),
            "ONBOARDING_LIVE_SYNC_PLATFORM": self.platform,
            "SYNC_ENABLED_PLATFORMS": self.platform,
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
            raise RuntimeError(f"local_{_platform_error_slug(self.platform)}_sync_failed")

        return {
            "runner": f"local_{_platform_error_slug(self.platform)}_sync",
            "platform": self.platform,
            "status": "success",
            "started_at": started_at,
            "finished_at": _utc_now(),
            "account_count": export.account_count,
            "destination_count": len(export.destinations),
            "config_path": str(self.config_path),
            "writes_bigquery": True,
            "readiness": readiness,
            "return_code": completed.returncode,
        }


class LocalMetaSyncRunner(LocalPlatformSyncRunner):
    """Run Meta sync from a locally exported onboarding config artifact."""

    def __init__(
        self,
        *,
        config_path: Path | str,
        repo_root: Path | str,
        python_bin: str | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        super().__init__(
            platform="meta_ads",
            config_path=config_path,
            repo_root=repo_root,
            python_bin=python_bin,
            timeout_seconds=timeout_seconds,
        )


class LocalGoogleAdsSyncRunner(LocalPlatformSyncRunner):
    """Run Google Ads sync from a locally exported onboarding config artifact."""

    def __init__(
        self,
        *,
        config_path: Path | str,
        repo_root: Path | str,
        python_bin: str | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        super().__init__(
            platform="google_ads",
            config_path=config_path,
            repo_root=repo_root,
            python_bin=python_bin,
            timeout_seconds=timeout_seconds,
        )


def _platform_error_slug(platform: str) -> str:
    return "google_ads" if platform == "google_ads" else "meta"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
