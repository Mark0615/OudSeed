"""Build sanitized config previews from connector onboarding selections."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.utils.config_loader import load_config_from_yaml


SUPPORTED_CONNECTORS = {"meta_ads"}
SUPPORTED_DESTINATIONS = {
    "bigquery",
    "looker_studio",
    "ai_report_email",
    "google_sheets",
}
DEFAULT_WORKSPACE_ID = "workspace_preview"
DEFAULT_PROJECT_ID = "oudseed"
DEFAULT_DATASET = "ads_pipeline"
DEFAULT_TIMEZONE = "Asia/Taipei"


@dataclass(frozen=True)
class ConfigPreview:
    """Sanitized config preview and non-sensitive validation metadata."""

    yaml_text: str
    client_count: int
    account_count: int
    destinations: list[str]
    report_schedule_count: int
    warnings: list[str]


def build_config_preview(selection: dict[str, Any]) -> ConfigPreview:
    """Convert an onboarding selection payload into sanitized clients YAML."""
    _require_mapping(selection, "selection")
    connector_id = _required_str(selection, "connector_id", "selection")
    if connector_id not in SUPPORTED_CONNECTORS:
        raise ValueError(f"Unsupported connector_id: {connector_id}")

    accounts = _required_list(selection, "accounts", "selection")
    destinations = _normalize_destinations(_required_list(selection, "destinations", "selection"))
    workspace_id = _optional_str(selection.get("workspace_id")) or DEFAULT_WORKSPACE_ID
    report_schedule = _build_report_schedule(selection, destinations)
    platform_config = _build_platform_config(connector_id, accounts)
    destination_config = _build_destination_config(destinations)
    client_name = _client_name(selection, accounts)

    client: dict[str, Any] = {
        "client_id": _slug(_optional_str(selection.get("client_id")) or client_name or "onboarding_preview_client"),
        "client_name": client_name,
        "enabled": True,
        "platforms": {
            connector_id: platform_config,
        },
        "destinations": destination_config,
    }
    if report_schedule:
        client["report_schedules"] = [report_schedule]

    config = {
        "workspace_id": _slug(workspace_id),
        "defaults": {
            "timezone": DEFAULT_TIMEZONE,
            "sync_days_back": 7,
            "attribution_setting": "platform_default",
            "timezone_setting": "platform_account_default",
            "conversion_action_type": "purchase",
        },
        "bigquery": {
            "project_id": DEFAULT_PROJECT_ID,
            "dataset": DEFAULT_DATASET,
        },
        "clients": [client],
    }
    yaml_text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    load_config_from_yaml(yaml_text, source="onboarding config preview")

    warnings = _warnings(destinations)
    return ConfigPreview(
        yaml_text=yaml_text,
        client_count=1,
        account_count=len(accounts),
        destinations=destinations,
        report_schedule_count=1 if report_schedule else 0,
        warnings=warnings,
    )


def format_preview_summary(preview: ConfigPreview) -> list[str]:
    """Return non-sensitive summary lines for CLI output."""
    lines = [
        "onboarding_config_preview=true",
        f"client_count={preview.client_count}",
        f"account_count={preview.account_count}",
        f"destinations={','.join(preview.destinations)}",
        f"report_schedule_count={preview.report_schedule_count}",
    ]
    lines.extend(f"warning={warning}" for warning in preview.warnings)
    return lines


def build_config_preview_response(selection: dict[str, Any], *, include_yaml: bool = True) -> dict[str, Any]:
    """Return an API-shaped, sanitized config preview response."""
    preview = build_config_preview(selection)
    response: dict[str, Any] = {
        "ok": True,
        "config_preview": {
            "summary": {
                "client_count": preview.client_count,
                "account_count": preview.account_count,
                "destinations": preview.destinations,
                "report_schedule_count": preview.report_schedule_count,
            },
            "summary_lines": format_preview_summary(preview),
            "warnings": preview.warnings,
        },
    }
    if include_yaml:
        response["config_preview"]["yaml_text"] = preview.yaml_text
    return response


def main() -> None:
    """CLI entrypoint for generating a sanitized onboarding config preview."""
    args = _parse_args()
    selection = _load_selection(args.selection_json)
    if args.json:
        response = build_config_preview_response(selection, include_yaml=not args.summary_only)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    preview = build_config_preview(selection)
    for line in format_preview_summary(preview):
        print(line)
    if not args.summary_only:
        print("---")
        print(preview.yaml_text, end="")


def _build_platform_config(connector_id: str, accounts: list[Any]) -> dict[str, Any]:
    if connector_id != "meta_ads":
        raise ValueError(f"Unsupported connector_id: {connector_id}")

    return {
        "enabled": True,
        "accounts": [
            {
                "ad_account_id": f"act_preview_{index:04d}",
                "account_name": _account_name(account, index),
                "report_level": "ad",
                "attribution_setting": "platform_default",
                "timezone_setting": "platform_account_default",
                "conversion_action_type": "purchase",
            }
            for index, account in enumerate(accounts, start=1)
        ],
    }


def _build_destination_config(destinations: list[str]) -> dict[str, Any]:
    return {
        "bigquery": {
            "enabled": "bigquery" in destinations or "looker_studio" in destinations,
            "project_id": DEFAULT_PROJECT_ID,
            "dataset": DEFAULT_DATASET,
        },
        "looker_studio": {
            "enabled": "looker_studio" in destinations,
        },
        "ai_report_email": {
            "enabled": "ai_report_email" in destinations,
        },
        "google_sheets": {
            "enabled": "google_sheets" in destinations,
            "spreadsheet_id": "preview_spreadsheet_id",
        },
    }


def _build_report_schedule(selection: dict[str, Any], destinations: list[str]) -> dict[str, Any] | None:
    if "ai_report_email" not in destinations:
        return None

    raw_schedule = selection.get("report_schedule") or {}
    if raw_schedule is not None and not isinstance(raw_schedule, dict):
        raise ValueError("selection.report_schedule must be a mapping/object.")

    report_type = _optional_str(raw_schedule.get("report_type")) or "monthly"
    if report_type not in {"weekly", "monthly"}:
        raise ValueError("selection.report_schedule.report_type must be 'weekly' or 'monthly'.")

    return {
        "schedule_id": _optional_str(raw_schedule.get("schedule_id")) or f"{report_type}_email_default",
        "enabled": bool(raw_schedule.get("enabled", True)),
        "report_type": report_type,
        "delivery_day": raw_schedule.get("delivery_day", 1 if report_type == "monthly" else "monday"),
        "timezone": _optional_str(raw_schedule.get("timezone")) or DEFAULT_TIMEZONE,
        "channel": "email",
        "email_to": "recipient@example.com",
        "depth": _optional_str(raw_schedule.get("depth")) or "standard",
    }


def _normalize_destinations(raw_destinations: list[Any]) -> list[str]:
    destinations: list[str] = []
    for index, destination in enumerate(raw_destinations):
        if not isinstance(destination, str) or not destination.strip():
            raise ValueError(f"selection.destinations[{index}] must be a non-empty string.")
        normalized = destination.strip()
        if normalized not in SUPPORTED_DESTINATIONS:
            raise ValueError(f"Unsupported destination: {normalized}")
        if normalized not in destinations:
            destinations.append(normalized)
    if not destinations:
        raise ValueError("selection.destinations must include at least one destination.")
    return destinations


def _warnings(destinations: list[str]) -> list[str]:
    warnings: list[str] = []
    if "google_sheets" in destinations:
        warnings.append("google_sheets_destination_not_productized")
    if "looker_studio" in destinations and "bigquery" not in destinations:
        warnings.append("looker_studio_uses_bigquery_views")
    return warnings


def _client_name(selection: dict[str, Any], accounts: list[Any]) -> str:
    explicit_name = _optional_str(selection.get("client_name"))
    if explicit_name:
        return explicit_name
    first_account = accounts[0]
    if isinstance(first_account, dict):
        account_name = _optional_str(first_account.get("account_name") or first_account.get("name"))
        if account_name:
            return account_name
    return "Onboarding Preview Client"


def _account_name(account: Any, index: int) -> str:
    if not isinstance(account, dict):
        raise ValueError(f"selection.accounts[{index - 1}] must be a mapping/object.")
    external_account_id = _optional_str(account.get("external_account_id") or account.get("id"))
    if not external_account_id:
        raise ValueError(f"selection.accounts[{index - 1}].external_account_id is required.")
    return _optional_str(account.get("account_name") or account.get("name")) or f"Preview Account {index}"


def _load_selection(selection_json: str) -> dict[str, Any]:
    path = Path(selection_json)
    raw_text = path.read_text(encoding="utf-8") if path.exists() else selection_json
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid selection JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Selection JSON root must be an object.")
    return parsed


def _required_str(mapping: dict[str, Any], key: str, location: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} must be a non-empty string.")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _required_list(mapping: dict[str, Any], key: str, location: str) -> list[Any]:
    value = mapping.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location}.{key} must be a non-empty list.")
    return value


def _require_mapping(value: Any, location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be a mapping/object.")


def _slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "onboarding_preview"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a sanitized clients.yaml-compatible preview from onboarding selection JSON.",
    )
    parser.add_argument(
        "selection_json",
        help="Path to a selection JSON file, or an inline JSON object.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only sanitized summary lines, without YAML.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print an API-shaped JSON response instead of text/YAML output.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
