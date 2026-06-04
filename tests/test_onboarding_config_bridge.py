"""Tests for onboarding config preview generation."""

import json

import pytest

from src.onboarding.config_bridge import (
    build_config_preview,
    build_config_preview_response,
    export_local_clients_config,
    format_local_export_summary,
    format_preview_summary,
)
from src.utils.config_loader import load_config_from_yaml


def sample_selection() -> dict:
    return {
        "workspace_id": "Workspace Demo",
        "connector_id": "meta_ads",
        "accounts": [
            {
                "external_account_id": "act_real_should_not_print",
                "account_name": "Demo Shop Taiwan",
            },
            {
                "external_account_id": "act_another_real_should_not_print",
                "account_name": "Demo Shop USA",
            },
        ],
        "destinations": ["looker_studio", "ai_report_email", "bigquery"],
        "report_schedule": {
            "report_type": "monthly",
            "delivery_day": 1,
            "depth": "standard",
            "email_to": "real-recipient@example.test",
        },
    }


def google_selection() -> dict:
    return {
        "workspace_id": "Workspace Demo",
        "connector_id": "google_ads",
        "accounts": [
            {
                "external_account_id": "123-456-7890",
                "account_name": "Demo Google Ads",
            }
        ],
        "destinations": ["bigquery", "looker_studio"],
    }


def test_build_config_preview_outputs_valid_sanitized_clients_yaml() -> None:
    preview = build_config_preview(sample_selection())
    config = load_config_from_yaml(preview.yaml_text, source="preview")

    assert config["workspace_id"] == "workspace_demo"
    assert config["clients"][0]["client_name"] == "Demo Shop Taiwan"
    assert config["clients"][0]["platforms"]["meta_ads"]["enabled"] is True
    assert config["clients"][0]["platforms"]["meta_ads"]["accounts"][0]["ad_account_id"] == "act_preview_0001"
    assert config["clients"][0]["destinations"]["looker_studio"]["enabled"] is True
    assert config["clients"][0]["report_schedules"][0]["email_to"] == "recipient@example.com"
    assert "act_real_should_not_print" not in preview.yaml_text
    assert "real-recipient@example.test" not in preview.yaml_text


def test_build_config_preview_outputs_valid_sanitized_google_ads_yaml() -> None:
    preview = build_config_preview(google_selection())
    config = load_config_from_yaml(preview.yaml_text, source="preview")

    account = config["clients"][0]["platforms"]["google_ads"]["accounts"][0]
    assert config["clients"][0]["platforms"]["google_ads"]["enabled"] is True
    assert account["customer_id"] == "0000000001"
    assert account["account_name"] == "Demo Google Ads"
    assert "123-456-7890" not in preview.yaml_text
    assert "1234567890" not in preview.yaml_text


def test_build_config_preview_skips_report_schedule_without_ai_email() -> None:
    selection = sample_selection()
    selection["destinations"] = ["bigquery"]

    preview = build_config_preview(selection)
    config = load_config_from_yaml(preview.yaml_text, source="preview")

    assert "report_schedules" not in config["clients"][0]
    assert preview.report_schedule_count == 0


def test_build_config_preview_accepts_weekly_email_schedule() -> None:
    selection = sample_selection()
    selection["report_schedule"] = {
        "report_type": "weekly",
        "delivery_day": "monday",
        "depth": "brief",
    }

    preview = build_config_preview(selection)
    config = load_config_from_yaml(preview.yaml_text, source="preview")

    schedule = config["clients"][0]["report_schedules"][0]
    assert schedule["report_type"] == "weekly"
    assert schedule["delivery_day"] == "monday"
    assert schedule["depth"] == "brief"


def test_build_config_preview_accepts_initial_sync_days_back() -> None:
    selection = sample_selection()
    selection["initial_sync"] = {"sync_days_back": 30}

    preview = build_config_preview(selection)
    config = load_config_from_yaml(preview.yaml_text, source="preview")
    response = build_config_preview_response(selection)

    assert config["defaults"]["sync_days_back"] == 30
    assert response["config_preview"]["summary"]["sync_days_back"] == 30


def test_build_config_preview_rejects_invalid_initial_sync_days_back() -> None:
    selection = sample_selection()
    selection["initial_sync"] = {"sync_days_back": 366}

    with pytest.raises(ValueError, match="sync_days_back"):
        build_config_preview(selection)


def test_build_config_preview_warns_when_looker_uses_bigquery_views() -> None:
    selection = sample_selection()
    selection["destinations"] = ["looker_studio"]

    preview = build_config_preview(selection)

    assert "looker_studio_uses_bigquery_views" in preview.warnings
    assert "bigquery:" in preview.yaml_text
    assert "enabled: true" in preview.yaml_text


def test_build_config_preview_rejects_unsupported_connector() -> None:
    selection = sample_selection()
    selection["connector_id"] = "line_ads"

    with pytest.raises(ValueError, match="Unsupported connector_id"):
        build_config_preview(selection)


def test_format_preview_summary_is_non_sensitive() -> None:
    preview = build_config_preview(sample_selection())
    output = "\n".join(format_preview_summary(preview))

    assert "onboarding_config_preview=true" in output
    assert "account_count=2" in output
    assert "sync_days_back=7" in output
    assert "act_real_should_not_print" not in output
    assert "real-recipient@example.test" not in output


def test_build_config_preview_response_matches_api_shape() -> None:
    response = build_config_preview_response(sample_selection())
    output = json.dumps(response)

    assert response["ok"] is True
    assert response["config_preview"]["summary"]["account_count"] == 2
    assert response["config_preview"]["summary"]["report_schedule_count"] == 1
    assert "yaml_text" in response["config_preview"]
    assert "act_real_should_not_print" not in output
    assert "real-recipient@example.test" not in output


def test_export_local_clients_config_writes_real_account_ids_to_ignored_artifact(tmp_path) -> None:
    output_path = tmp_path / "clients.generated.yaml"
    selection = sample_selection()
    selection["initial_sync"] = {"sync_days_back": 30}

    export = export_local_clients_config(selection, output_path)
    config = load_config_from_yaml(output_path.read_text(encoding="utf-8"), source="local export")

    assert config["defaults"]["sync_days_back"] == 30
    accounts = config["clients"][0]["platforms"]["meta_ads"]["accounts"]
    assert accounts[0]["ad_account_id"] == "act_real_should_not_print"
    assert accounts[1]["ad_account_id"] == "act_another_real_should_not_print"
    assert export.account_count == 2
    assert export.sync_days_back == 30
    assert export.report_schedule_count == 1


def test_export_local_clients_config_writes_google_customer_ids_to_ignored_artifact(tmp_path) -> None:
    output_path = tmp_path / "clients.generated.yaml"

    export = export_local_clients_config(google_selection(), output_path)
    config = load_config_from_yaml(output_path.read_text(encoding="utf-8"), source="local export")

    accounts = config["clients"][0]["platforms"]["google_ads"]["accounts"]
    assert accounts[0]["customer_id"] == "1234567890"
    assert export.account_count == 1
    assert export.destinations == ["bigquery", "looker_studio"]


def test_format_local_export_summary_is_safe_for_api_response(tmp_path) -> None:
    export = export_local_clients_config(sample_selection(), tmp_path / "clients.generated.yaml")
    response = format_local_export_summary(export)
    output = json.dumps(response)

    assert response["account_count"] == 2
    assert response["sync_days_back"] == 7
    assert response["local_artifact_only"] is True
    assert response["writes_config"] is False
    assert response["writes_secrets"] is False
    assert "act_real_should_not_print" not in output
    assert "real-recipient@example.test" not in output
