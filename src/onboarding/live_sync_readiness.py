"""Safe readiness checks for local onboarding live sync."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

from src.utils.config_loader import load_config


@dataclass(frozen=True)
class LiveSyncReadiness:
    """Non-sensitive readiness metadata for the local Meta first-sync runner."""

    ready: bool
    checked_at: str
    config_path: str | None
    writes_bigquery: bool
    checks: list[dict[str, Any]]
    summary: dict[str, Any]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        """Return API/CLI-safe readiness metadata."""
        return {
            "ready": self.ready,
            "checked_at": self.checked_at,
            "config_path": self.config_path,
            "writes_bigquery": self.writes_bigquery,
            "checks": self.checks,
            "summary": self.summary,
            "warnings": self.warnings,
        }


def build_live_sync_readiness_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build safe readiness metadata from runtime environment variables."""
    environment = env or os.environ
    config_path = _optional_str(environment.get("ONBOARDING_LOCAL_CONFIG_EXPORT_PATH"))
    if not config_path:
        config_path = _optional_str(environment.get("CLIENTS_CONFIG_PATH"))

    return inspect_live_sync_readiness(
        config_path=Path(config_path) if config_path else None,
        local_sync_enabled=_truthy(environment.get("ONBOARDING_ENABLE_LOCAL_SYNC_RUN")),
        meta_access_token_configured=bool(_optional_str(environment.get("META_ACCESS_TOKEN"))),
        gcp_project_id=_optional_str(environment.get("GCP_PROJECT_ID")),
        bigquery_dataset=_optional_str(environment.get("BIGQUERY_DATASET")),
        sync_enabled_platforms=_optional_str(environment.get("SYNC_ENABLED_PLATFORMS")),
        refresh_reporting_marts=environment.get("REFRESH_REPORTING_MARTS"),
    ).as_dict()


def inspect_live_sync_readiness(
    *,
    config_path: Path | None,
    local_sync_enabled: bool,
    meta_access_token_configured: bool,
    gcp_project_id: str | None,
    bigquery_dataset: str | None,
    sync_enabled_platforms: str | None,
    refresh_reporting_marts: str | None,
) -> LiveSyncReadiness:
    """Inspect local live sync prerequisites without calling Meta or BigQuery."""
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {
        "platform": "meta_ads",
        "client_count": 0,
        "enabled_meta_account_count": 0,
        "destination_count": 0,
        "report_schedule_count": 0,
        "gcp_project_configured": False,
        "bigquery_dataset_configured": False,
        "sync_platform_filter": sync_enabled_platforms or None,
        "refresh_reporting_marts": _refresh_reporting_marts_enabled(refresh_reporting_marts),
    }

    _add_check(
        checks,
        check_id="local_sync_explicitly_enabled",
        ok=local_sync_enabled,
        message=(
            "Local live sync runner is explicitly enabled."
            if local_sync_enabled
            else "Set ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true before live first-sync execution."
        ),
        warnings=warnings,
        warning_id="local_sync_runner_disabled",
    )

    _add_check(
        checks,
        check_id="local_config_export_path_configured",
        ok=config_path is not None,
        message=(
            "Local config artifact path is configured."
            if config_path
            else "Set ONBOARDING_LOCAL_CONFIG_EXPORT_PATH or CLIENTS_CONFIG_PATH."
        ),
        warnings=warnings,
        warning_id="local_config_export_path_missing",
    )

    config: dict[str, Any] | None = None
    if config_path is not None:
        exists = config_path.exists()
        _add_check(
            checks,
            check_id="local_config_artifact_exists",
            ok=exists,
            message=(
                "Local config artifact exists."
                if exists
                else "Create the onboarding local config artifact before live sync."
            ),
            warnings=warnings,
            warning_id="local_config_artifact_missing",
        )
        if exists:
            try:
                config = load_config(str(config_path))
            except Exception as exc:
                _add_check(
                    checks,
                    check_id="local_config_artifact_valid",
                    ok=False,
                    message=f"Local config artifact failed validation: {exc.__class__.__name__}.",
                    warnings=warnings,
                    warning_id="local_config_artifact_invalid",
                )
            else:
                _add_check(
                    checks,
                    check_id="local_config_artifact_valid",
                    ok=True,
                    message="Local config artifact is valid clients YAML.",
                    warnings=warnings,
                    warning_id="local_config_artifact_invalid",
                )

    if config is not None:
        config_summary = _summarize_config(config)
        summary.update(config_summary)
        if not summary["enabled_meta_account_count"]:
            warnings.append("no_enabled_meta_accounts")
        bigquery_config = config.get("bigquery", {}) if isinstance(config.get("bigquery"), dict) else {}
        summary["gcp_project_configured"] = bool(gcp_project_id or _optional_str(bigquery_config.get("project_id")))
        summary["bigquery_dataset_configured"] = bool(bigquery_dataset or _optional_str(bigquery_config.get("dataset")))
    else:
        summary["gcp_project_configured"] = bool(gcp_project_id)
        summary["bigquery_dataset_configured"] = bool(bigquery_dataset)

    _add_check(
        checks,
        check_id="enabled_meta_accounts_present",
        ok=summary["enabled_meta_account_count"] > 0,
        message=(
            f"{summary['enabled_meta_account_count']} enabled Meta account(s) are configured."
            if summary["enabled_meta_account_count"]
            else "No enabled Meta ad accounts found in the local config artifact."
        ),
        warnings=warnings,
        warning_id="no_enabled_meta_accounts",
    )
    _add_check(
        checks,
        check_id="meta_access_token_configured",
        ok=meta_access_token_configured,
        message=(
            "META_ACCESS_TOKEN is configured."
            if meta_access_token_configured
            else "META_ACCESS_TOKEN is required for live Meta sync."
        ),
        warnings=warnings,
        warning_id="meta_access_token_missing",
    )
    _add_check(
        checks,
        check_id="bigquery_project_configured",
        ok=bool(summary["gcp_project_configured"]),
        message=(
            "BigQuery project is configured."
            if summary["gcp_project_configured"]
            else "GCP_PROJECT_ID or config.bigquery.project_id is required."
        ),
        warnings=warnings,
        warning_id="bigquery_project_missing",
    )
    _add_check(
        checks,
        check_id="bigquery_dataset_configured",
        ok=bool(summary["bigquery_dataset_configured"]),
        message=(
            "BigQuery dataset is configured."
            if summary["bigquery_dataset_configured"]
            else "BIGQUERY_DATASET or config.bigquery.dataset is required."
        ),
        warnings=warnings,
        warning_id="bigquery_dataset_missing",
    )

    sync_platform_ok = not sync_enabled_platforms or "meta_ads" in {
        platform.strip() for platform in sync_enabled_platforms.split(",") if platform.strip()
    }
    _add_check(
        checks,
        check_id="sync_platform_filter_allows_meta",
        ok=sync_platform_ok,
        message=(
            "SYNC_ENABLED_PLATFORMS allows Meta sync."
            if sync_platform_ok
            else "SYNC_ENABLED_PLATFORMS must include meta_ads for this live sync."
        ),
        warnings=warnings,
        warning_id="sync_platform_filter_excludes_meta",
    )

    if summary["refresh_reporting_marts"]:
        warnings.append("refresh_reporting_marts_enabled")
    warnings.append("live_sync_writes_bigquery")

    blocking_checks = {
        "local_sync_explicitly_enabled",
        "local_config_export_path_configured",
        "local_config_artifact_exists",
        "local_config_artifact_valid",
        "enabled_meta_accounts_present",
        "meta_access_token_configured",
        "bigquery_project_configured",
        "bigquery_dataset_configured",
        "sync_platform_filter_allows_meta",
    }
    ready = all(check["ok"] for check in checks if check["id"] in blocking_checks)
    return LiveSyncReadiness(
        ready=ready,
        checked_at=_utc_now(),
        config_path=str(config_path) if config_path else None,
        writes_bigquery=True,
        checks=checks,
        summary=summary,
        warnings=_dedupe(warnings),
    )


def main() -> None:
    """CLI entrypoint for safe live-sync readiness checks."""
    load_dotenv()
    args = _parse_args()
    readiness = build_live_sync_readiness_from_env()
    if args.json:
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return

    print(f"onboarding_live_sync_ready={str(readiness['ready']).lower()}")
    print(f"writes_bigquery={str(readiness['writes_bigquery']).lower()}")
    print(f"config_path={readiness['config_path'] or ''}")
    for key, value in readiness["summary"].items():
        print(f"{key}={value}")
    for check in readiness["checks"]:
        print(f"check.{check['id']}={str(check['ok']).lower()}")
    for warning in readiness["warnings"]:
        print(f"warning={warning}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check safe readiness for local onboarding live sync.")
    parser.add_argument("--json", action="store_true", help="Print API-shaped JSON.")
    return parser.parse_args()


def _summarize_config(config: dict[str, Any]) -> dict[str, Any]:
    clients = config.get("clients") if isinstance(config.get("clients"), list) else []
    enabled_clients = [client for client in clients if isinstance(client, dict) and client.get("enabled", True)]
    destination_ids: set[str] = set()
    enabled_meta_account_count = 0
    report_schedule_count = 0
    for client in enabled_clients:
        destinations = client.get("destinations") if isinstance(client.get("destinations"), dict) else {}
        destination_ids.update(
            str(destination_id)
            for destination_id, destination_config in destinations.items()
            if isinstance(destination_config, dict) and destination_config.get("enabled", False)
        )
        schedules = client.get("report_schedules") if isinstance(client.get("report_schedules"), list) else []
        report_schedule_count += len(schedules)
        platforms = client.get("platforms") if isinstance(client.get("platforms"), dict) else {}
        meta_config = platforms.get("meta_ads") if isinstance(platforms.get("meta_ads"), dict) else {}
        if not meta_config.get("enabled", False):
            continue
        accounts = meta_config.get("accounts") if isinstance(meta_config.get("accounts"), list) else []
        enabled_meta_account_count += sum(
            1 for account in accounts if isinstance(account, dict) and account.get("enabled", True) is not False
        )

    return {
        "client_count": len(enabled_clients),
        "enabled_meta_account_count": enabled_meta_account_count,
        "destination_count": len(destination_ids),
        "report_schedule_count": report_schedule_count,
    }


def _add_check(
    checks: list[dict[str, Any]],
    *,
    check_id: str,
    ok: bool,
    message: str,
    warnings: list[str],
    warning_id: str,
) -> None:
    checks.append({"id": check_id, "ok": ok, "message": message})
    if not ok:
        warnings.append(warning_id)


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _truthy(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def _refresh_reporting_marts_enabled(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    return value.strip().lower() not in {"0", "false", "no"}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
