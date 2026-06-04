"""Build sanitized config previews from connector onboarding selections."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.utils.config_loader import load_config_from_yaml


SUPPORTED_CONNECTORS = {"meta_ads", "google_ads"}
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
DEFAULT_SYNC_DAYS_BACK = 7
MAX_INITIAL_SYNC_DAYS_BACK = 365


@dataclass(frozen=True)
class ConfigPreview:
    """Sanitized config preview and non-sensitive validation metadata."""

    yaml_text: str
    client_count: int
    account_count: int
    destinations: list[str]
    report_schedule_count: int
    sync_days_back: int
    warnings: list[str]


@dataclass(frozen=True)
class LocalConfigExport:
    """Local config export metadata, without exposing rendered YAML."""

    output_path: Path
    client_count: int
    account_count: int
    destinations: list[str]
    report_schedule_count: int
    sync_days_back: int
    warnings: list[str]


def build_config_preview(selection: dict[str, Any]) -> ConfigPreview:
    """Convert an onboarding selection payload into sanitized clients YAML."""
    yaml_text, account_count, destinations, report_schedule_count = _build_clients_yaml(
        selection,
        redact_account_ids=True,
    )
    warnings = _warnings(destinations)
    return ConfigPreview(
        yaml_text=yaml_text,
        client_count=1,
        account_count=account_count,
        destinations=destinations,
        report_schedule_count=report_schedule_count,
        sync_days_back=_sync_days_back(selection),
        warnings=warnings,
    )


def export_local_clients_config(selection: dict[str, Any], output_path: Path | str) -> LocalConfigExport:
    """Write selected accounts to a local clients.yaml-compatible artifact.

    The artifact may contain real ad account IDs. Use only ignored local paths.
    """
    return export_local_clients_config_from_selections([selection], output_path)


def export_local_clients_config_from_selections(
    selections: list[dict[str, Any]],
    output_path: Path | str,
) -> LocalConfigExport:
    """Write all local onboarding selections into one clients config artifact.

    Selections with the same client name are merged into one client entry so
    Meta and Google accounts can feed the same account-grouped report.
    """
    path = Path(output_path)
    yaml_text, account_count, destinations, report_schedule_count, sync_days_back, client_count = (
        _build_clients_yaml_from_selections(
            selections,
            redact_account_ids=False,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    return LocalConfigExport(
        output_path=path,
        client_count=client_count,
        account_count=account_count,
        destinations=destinations,
        report_schedule_count=report_schedule_count,
        sync_days_back=sync_days_back,
        warnings=_warnings(destinations),
    )


def build_merged_config_preview(selections: list[dict[str, Any]]) -> ConfigPreview:
    """Build a sanitized preview for all current local onboarding selections."""
    yaml_text, account_count, destinations, report_schedule_count, sync_days_back, client_count = (
        _build_clients_yaml_from_selections(
            selections,
            redact_account_ids=True,
        )
    )
    return ConfigPreview(
        yaml_text=yaml_text,
        client_count=client_count,
        account_count=account_count,
        destinations=destinations,
        report_schedule_count=report_schedule_count,
        sync_days_back=sync_days_back,
        warnings=_warnings(destinations),
    )


def _build_clients_yaml_from_selections(
    selections: list[dict[str, Any]],
    *,
    redact_account_ids: bool,
) -> tuple[str, int, list[str], int, int, int]:
    if not selections:
        raise ValueError("At least one onboarding selection is required.")

    workspace_id = _optional_str(selections[0].get("workspace_id")) or DEFAULT_WORKSPACE_ID
    clients_by_id: dict[str, dict[str, Any]] = {}
    destinations: list[str] = []
    sync_days_back = DEFAULT_SYNC_DAYS_BACK

    for selection in selections:
        _require_mapping(selection, "selection")
        connector_id = _required_str(selection, "connector_id", "selection")
        if connector_id not in SUPPORTED_CONNECTORS:
            raise ValueError(f"Unsupported connector_id: {connector_id}")

        accounts = _required_list(selection, "accounts", "selection")
        selection_destinations = _normalize_destinations(_required_list(selection, "destinations", "selection"))
        destinations = _ordered_union(destinations, selection_destinations)
        sync_days_back = max(sync_days_back, _sync_days_back(selection))

        client_name = _client_name(selection, accounts)
        client_id = _slug(_optional_str(selection.get("client_id")) or client_name or "onboarding_preview_client")
        client = clients_by_id.setdefault(
            client_id,
            {
                "client_id": client_id,
                "client_name": client_name,
                "enabled": True,
                "platforms": {},
                "destinations": _build_destination_config([]),
            },
        )
        client["client_name"] = client_name
        client["destinations"] = _build_destination_config(
            _ordered_union(_enabled_destination_ids(client["destinations"]), selection_destinations)
        )

        platform_config = _build_platform_config(
            connector_id,
            accounts,
            redact_account_ids=redact_account_ids,
        )
        _merge_platform_config(client["platforms"], connector_id, platform_config)

        report_schedule = _build_report_schedule(selection, selection_destinations)
        if report_schedule:
            client["report_schedules"] = [report_schedule]

    clients = list(clients_by_id.values())
    _dedupe_default_schedule_ids(clients)
    config = {
        "workspace_id": _slug(workspace_id),
        "defaults": {
            "timezone": DEFAULT_TIMEZONE,
            "sync_days_back": sync_days_back,
            "attribution_setting": "platform_default",
            "timezone_setting": "platform_account_default",
            "conversion_action_type": "purchase",
        },
        "bigquery": {
            "project_id": DEFAULT_PROJECT_ID,
            "dataset": DEFAULT_DATASET,
        },
        "clients": clients,
    }
    yaml_text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    load_config_from_yaml(yaml_text, source="onboarding config preview")
    account_count = sum(_client_account_count(client) for client in clients)
    report_schedule_count = sum(
        len(client.get("report_schedules", []) or [])
        for client in clients
    )
    return yaml_text, account_count, destinations, report_schedule_count, sync_days_back, len(clients)


def _build_clients_yaml(
    selection: dict[str, Any],
    *,
    redact_account_ids: bool,
) -> tuple[str, int, list[str], int]:
    yaml_text, account_count, destinations, report_schedule_count, _sync_days, _client_count = (
        _build_clients_yaml_from_selections(
            [selection],
            redact_account_ids=redact_account_ids,
        )
    )
    return yaml_text, account_count, destinations, report_schedule_count


def _merge_platform_config(
    platforms: dict[str, Any],
    connector_id: str,
    platform_config: dict[str, Any],
) -> None:
    existing = platforms.get(connector_id)
    if not isinstance(existing, dict):
        platforms[connector_id] = platform_config
        return
    existing["enabled"] = True
    existing_accounts = existing.setdefault("accounts", [])
    if not isinstance(existing_accounts, list):
        existing["accounts"] = []
        existing_accounts = existing["accounts"]
    seen_ids = {
        _platform_account_key(connector_id, account)
        for account in existing_accounts
        if isinstance(account, dict)
    }
    for account in platform_config.get("accounts", []) or []:
        if not isinstance(account, dict):
            continue
        key = _platform_account_key(connector_id, account)
        if key in seen_ids:
            continue
        existing_accounts.append(account)
        seen_ids.add(key)


def _platform_account_key(connector_id: str, account: dict[str, Any]) -> str:
    if connector_id == "google_ads":
        return str(account.get("customer_id") or "")
    return str(account.get("ad_account_id") or "")


def _enabled_destination_ids(destination_config: dict[str, Any]) -> list[str]:
    return [
        destination_id
        for destination_id, config in destination_config.items()
        if isinstance(config, dict) and config.get("enabled")
    ]


def _ordered_union(first: list[str], second: list[str]) -> list[str]:
    values: list[str] = []
    for value in [*first, *second]:
        if value not in values:
            values.append(value)
    return values


def _client_account_count(client: dict[str, Any]) -> int:
    total = 0
    platforms = client.get("platforms")
    if not isinstance(platforms, dict):
        return 0
    for platform_config in platforms.values():
        if isinstance(platform_config, dict) and isinstance(platform_config.get("accounts"), list):
            total += len(platform_config["accounts"])
    return total


def _dedupe_default_schedule_ids(clients: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for client in clients:
        client_id = str(client.get("client_id") or "client")
        for schedule in client.get("report_schedules", []) or []:
            if not isinstance(schedule, dict):
                continue
            schedule_id = str(schedule.get("schedule_id") or "")
            if schedule_id and schedule_id not in seen:
                seen.add(schedule_id)
                continue
            report_type = str(schedule.get("report_type") or "monthly")
            schedule["schedule_id"] = f"{client_id}_{report_type}_email_default"
            seen.add(schedule["schedule_id"])


def format_local_export_summary(export: LocalConfigExport) -> dict[str, Any]:
    """Return safe local export metadata for API responses."""
    return {
        "output_path": str(export.output_path),
        "client_count": export.client_count,
        "account_count": export.account_count,
        "destinations": export.destinations,
        "report_schedule_count": export.report_schedule_count,
        "sync_days_back": export.sync_days_back,
        "warnings": export.warnings,
        "writes_config": False,
        "writes_secrets": False,
        "local_artifact_only": True,
    }


def format_preview_summary(preview: ConfigPreview) -> list[str]:
    """Return non-sensitive summary lines for CLI output."""
    lines = [
        "onboarding_config_preview=true",
        f"client_count={preview.client_count}",
        f"account_count={preview.account_count}",
        f"destinations={','.join(preview.destinations)}",
        f"report_schedule_count={preview.report_schedule_count}",
        f"sync_days_back={preview.sync_days_back}",
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
                "sync_days_back": preview.sync_days_back,
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


def _build_platform_config(
    connector_id: str,
    accounts: list[Any],
    *,
    redact_account_ids: bool,
) -> dict[str, Any]:
    if connector_id == "google_ads":
        return {
            "enabled": True,
            "accounts": [
                {
                    "customer_id": (
                        f"000000{index:04d}"
                        if redact_account_ids
                        else _account_external_id(account, index).replace("-", "")
                    ),
                    "account_name": _account_name(account, index),
                    "login_customer_id": _optional_str(account.get("login_customer_id")) if isinstance(account, dict) else None,
                    "report_level": "ad",
                    "attribution_setting": "platform_default",
                    "timezone_setting": "platform_account_default",
                }
                for index, account in enumerate(accounts, start=1)
            ],
        }

    if connector_id != "meta_ads":
        raise ValueError(f"Unsupported connector_id: {connector_id}")

    return {
        "enabled": True,
        "accounts": [
            {
                "ad_account_id": (
                    f"act_preview_{index:04d}"
                    if redact_account_ids
                    else _account_external_id(account, index)
                ),
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


def _build_report_schedule(
    selection: dict[str, Any],
    destinations: list[str],
) -> dict[str, Any] | None:
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


def _sync_days_back(selection: dict[str, Any]) -> int:
    initial_sync = selection.get("initial_sync")
    raw_value: Any = None
    if isinstance(initial_sync, dict):
        raw_value = initial_sync.get("sync_days_back")
    if raw_value is None:
        raw_value = selection.get("sync_days_back")
    if raw_value is None:
        return DEFAULT_SYNC_DAYS_BACK
    try:
        days_back = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("initial_sync.sync_days_back must be an integer.") from exc
    if days_back < 0:
        raise ValueError("initial_sync.sync_days_back must be greater than or equal to 0.")
    if days_back > MAX_INITIAL_SYNC_DAYS_BACK:
        raise ValueError(f"initial_sync.sync_days_back must be less than or equal to {MAX_INITIAL_SYNC_DAYS_BACK}.")
    return days_back


def _account_name(account: Any, index: int) -> str:
    if not isinstance(account, dict):
        raise ValueError(f"selection.accounts[{index - 1}] must be a mapping/object.")
    external_account_id = _optional_str(account.get("external_account_id") or account.get("id"))
    if not external_account_id:
        raise ValueError(f"selection.accounts[{index - 1}].external_account_id is required.")
    return _optional_str(account.get("account_name") or account.get("name")) or f"Preview Account {index}"


def _account_external_id(account: Any, index: int) -> str:
    if not isinstance(account, dict):
        raise ValueError(f"selection.accounts[{index - 1}] must be a mapping/object.")
    external_account_id = _optional_str(account.get("external_account_id") or account.get("id"))
    if not external_account_id:
        raise ValueError(f"selection.accounts[{index - 1}].external_account_id is required.")
    return external_account_id


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
