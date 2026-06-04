"""Tests for safe onboarding live-sync readiness checks."""

from __future__ import annotations

import json

from src.onboarding.config_bridge import export_local_clients_config
from src.onboarding.live_sync_readiness import build_live_sync_readiness_from_env, inspect_live_sync_readiness


def sample_selection() -> dict:
    """Return a fake onboarding selection with a non-secret account id."""
    return {
        "workspace_id": "workspace_demo",
        "connector_id": "meta_ads",
        "client_name": "Demo Shop Taiwan",
        "accounts": [
            {
                "external_account_id": "act_demo_1001",
                "account_name": "Demo Shop Taiwan",
            }
        ],
        "destinations": ["bigquery", "looker_studio", "ai_report_email"],
        "report_schedule": {
            "report_type": "monthly",
            "delivery_day": "1",
            "timezone": "Asia/Taipei",
            "depth": "standard",
        },
    }


def google_selection() -> dict:
    """Return a fake Google Ads onboarding selection with a non-secret customer id."""
    return {
        "workspace_id": "workspace_demo",
        "connector_id": "google_ads",
        "client_name": "Demo Google Ads",
        "accounts": [
            {
                "external_account_id": "123-456-7890",
                "account_name": "Demo Google Ads",
            }
        ],
        "destinations": ["bigquery", "looker_studio"],
    }


def test_live_sync_readiness_reports_missing_requirements_safely(tmp_path) -> None:
    config_path = tmp_path / "missing.yaml"

    readiness = inspect_live_sync_readiness(
        config_path=config_path,
        local_sync_enabled=False,
        meta_access_token_configured=False,
        gcp_project_id=None,
        bigquery_dataset=None,
        sync_enabled_platforms="meta_ads",
        refresh_reporting_marts="false",
    ).as_dict()

    assert readiness["ready"] is False
    assert readiness["writes_bigquery"] is True
    assert "local_sync_runner_disabled" in readiness["warnings"]
    assert "local_config_artifact_missing" in readiness["warnings"]
    assert "meta_access_token_missing" in readiness["warnings"]
    assert "bigquery_project_missing" in readiness["warnings"]
    assert "bigquery_dataset_missing" in readiness["warnings"]
    assert "act_demo_1001" not in json.dumps(readiness)


def test_live_sync_readiness_accepts_valid_local_config_without_exposing_ids(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(sample_selection(), config_path)

    readiness = inspect_live_sync_readiness(
        config_path=config_path,
        local_sync_enabled=True,
        meta_access_token_configured=True,
        gcp_project_id=None,
        bigquery_dataset=None,
        sync_enabled_platforms="meta_ads",
        refresh_reporting_marts="false",
    ).as_dict()
    output = json.dumps(readiness)

    assert readiness["ready"] is True
    assert readiness["summary"]["client_count"] == 1
    assert readiness["summary"]["enabled_meta_account_count"] == 1
    assert readiness["summary"]["destination_count"] == 3
    assert readiness["summary"]["report_schedule_count"] == 1
    assert readiness["summary"]["gcp_project_configured"] is True
    assert readiness["summary"]["bigquery_dataset_configured"] is True
    assert "live_sync_writes_bigquery" in readiness["warnings"]
    assert "act_demo_1001" in config_path.read_text(encoding="utf-8")
    assert "act_demo_1001" not in output


def test_google_live_sync_readiness_reports_missing_credentials_safely(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(google_selection(), config_path)

    readiness = inspect_live_sync_readiness(
        platform="google_ads",
        config_path=config_path,
        local_sync_enabled=True,
        meta_access_token_configured=False,
        google_ads_developer_token_configured=False,
        google_ads_client_id_configured=False,
        google_ads_client_secret_configured=False,
        google_ads_refresh_token_configured=False,
        gcp_project_id=None,
        bigquery_dataset=None,
        sync_enabled_platforms="google_ads",
        refresh_reporting_marts="false",
    ).as_dict()
    output = json.dumps(readiness)

    assert readiness["ready"] is False
    assert readiness["summary"]["platform"] == "google_ads"
    assert readiness["summary"]["enabled_google_account_count"] == 1
    assert "google_ads_developer_token_missing" in readiness["warnings"]
    assert "google_ads_client_id_missing" in readiness["warnings"]
    assert "google_ads_client_secret_missing" in readiness["warnings"]
    assert "google_ads_refresh_token_missing" in readiness["warnings"]
    assert "1234567890" not in output
    assert "123-456-7890" not in output


def test_google_live_sync_readiness_accepts_valid_local_config_without_exposing_ids(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(google_selection(), config_path)

    readiness = inspect_live_sync_readiness(
        platform="google_ads",
        config_path=config_path,
        local_sync_enabled=True,
        meta_access_token_configured=False,
        google_ads_developer_token_configured=True,
        google_ads_client_id_configured=True,
        google_ads_client_secret_configured=True,
        google_ads_refresh_token_configured=True,
        gcp_project_id=None,
        bigquery_dataset=None,
        sync_enabled_platforms="google_ads",
        refresh_reporting_marts="false",
    ).as_dict()
    output = json.dumps(readiness)

    assert readiness["ready"] is True
    assert readiness["summary"]["enabled_google_account_count"] == 1
    assert readiness["summary"]["gcp_project_configured"] is True
    assert readiness["summary"]["bigquery_dataset_configured"] is True
    assert "live_sync_writes_bigquery" in readiness["warnings"]
    assert "1234567890" in config_path.read_text(encoding="utf-8")
    assert "1234567890" not in output


def test_live_sync_readiness_from_env_prefers_onboarding_export_path(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(sample_selection(), config_path)
    env = {
        "ONBOARDING_LOCAL_CONFIG_EXPORT_PATH": str(config_path),
        "CLIENTS_CONFIG_PATH": str(tmp_path / "ignored.yaml"),
        "ONBOARDING_ENABLE_LOCAL_SYNC_RUN": "true",
        "META_ACCESS_TOKEN": "fake-token",
        "SYNC_ENABLED_PLATFORMS": "meta_ads",
        "REFRESH_REPORTING_MARTS": "false",
    }

    readiness = build_live_sync_readiness_from_env(env)

    assert readiness["ready"] is True
    assert readiness["config_path"] == str(config_path)
    assert readiness["summary"]["sync_platform_filter"] == "meta_ads"


def test_live_sync_readiness_from_env_accepts_readiness_only_enable(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(sample_selection(), config_path)
    env = {
        "ONBOARDING_LOCAL_CONFIG_EXPORT_PATH": str(config_path),
        "ONBOARDING_ENABLE_LOCAL_SYNC_READINESS": "true",
        "META_ACCESS_TOKEN": "fake-token",
        "SYNC_ENABLED_PLATFORMS": "meta_ads",
        "REFRESH_REPORTING_MARTS": "false",
    }

    readiness = build_live_sync_readiness_from_env(env)

    assert readiness["ready"] is True
    assert "local_sync_runner_disabled" not in readiness["warnings"]


def test_google_live_sync_readiness_from_env_uses_google_platform(tmp_path) -> None:
    config_path = tmp_path / "clients.generated.yaml"
    export_local_clients_config(google_selection(), config_path)
    env = {
        "ONBOARDING_LIVE_SYNC_PLATFORM": "google_ads",
        "ONBOARDING_LOCAL_CONFIG_EXPORT_PATH": str(config_path),
        "ONBOARDING_ENABLE_LOCAL_SYNC_RUN": "true",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "fake-developer-token",
        "GOOGLE_ADS_CLIENT_ID": "fake-client-id",
        "GOOGLE_ADS_CLIENT_SECRET": "fake-client-secret",
        "GOOGLE_ADS_REFRESH_TOKEN": "fake-refresh-token",
        "SYNC_ENABLED_PLATFORMS": "google_ads",
        "REFRESH_REPORTING_MARTS": "false",
    }

    readiness = build_live_sync_readiness_from_env(env)

    assert readiness["ready"] is True
    assert readiness["summary"]["platform"] == "google_ads"
    assert readiness["summary"]["sync_platform_filter"] == "google_ads"
