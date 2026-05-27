"""Configuration loading helpers."""

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str) -> dict:
    """Load and validate pipeline YAML configuration."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if config is None:
        raise ValueError(f"Config file is empty: {config_path}")

    return load_config_from_yaml(yaml_text=None, parsed_config=config, source=str(config_path))


def load_config_from_yaml(
    yaml_text: str | None = None,
    *,
    parsed_config: object | None = None,
    source: str = "config yaml",
) -> dict:
    """Load and validate pipeline config from YAML text or parsed YAML."""
    config = yaml.safe_load(yaml_text) if yaml_text is not None else parsed_config

    if config is None:
        raise ValueError(f"Config is empty: {source}")
    if not isinstance(config, dict):
        raise ValueError("Config root must be a mapping/object.")

    _validate_config(config)
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """Validate top-level config fields used by the MVP sync flow."""
    _require_mapping_key(config, "workspace_id", "config")
    clients = _require_mapping_key(config, "clients", "config")

    if not isinstance(clients, list) or not clients:
        raise ValueError("config.clients must be a non-empty list.")

    for index, client in enumerate(clients):
        location = f"config.clients[{index}]"
        if not isinstance(client, dict):
            raise ValueError(f"{location} must be a mapping/object.")

        _require_mapping_key(client, "client_id", location)
        _require_mapping_key(client, "platforms", location)
        _require_mapping_key(client, "destinations", location)
        _validate_report_schedules(client, location)


def _validate_report_schedules(client: dict[str, Any], location: str) -> None:
    """Validate optional client-level AI report schedules."""
    schedules = client.get("report_schedules")
    if schedules is None:
        return
    if not isinstance(schedules, list):
        raise ValueError(f"{location}.report_schedules must be a list.")

    seen_schedule_ids: set[str] = set()
    for index, schedule in enumerate(schedules):
        schedule_location = f"{location}.report_schedules[{index}]"
        if not isinstance(schedule, dict):
            raise ValueError(f"{schedule_location} must be a mapping/object.")

        schedule_id = _require_mapping_key(schedule, "schedule_id", schedule_location)
        if schedule_id in seen_schedule_ids:
            raise ValueError(f"Duplicate report schedule id: {schedule_id}")
        seen_schedule_ids.add(schedule_id)

        report_type = _require_mapping_key(schedule, "report_type", schedule_location)
        if report_type not in {"weekly", "monthly"}:
            raise ValueError(f"{schedule_location}.report_type must be 'weekly' or 'monthly'.")

        _require_mapping_key(schedule, "delivery_day", schedule_location)
        channel = schedule.get("channel", "email")
        if channel != "email":
            raise ValueError(f"{schedule_location}.channel must be 'email'.")

        depth = schedule.get("depth", "standard")
        if depth not in {"brief", "standard", "deep"}:
            raise ValueError(f"{schedule_location}.depth must be 'brief', 'standard', or 'deep'.")

        if "email_to" in schedule:
            _require_mapping_key(schedule, "email_to", schedule_location)

        if "account_group_limit" in schedule:
            limit = schedule["account_group_limit"]
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise ValueError(f"{schedule_location}.account_group_limit must be a positive integer.")


def _require_mapping_key(mapping: dict[str, Any], key: str, location: str) -> Any:
    """Return a required value or raise a clear validation error."""
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"Missing required field: {location}.{key}")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"Required field cannot be empty: {location}.{key}")
    return value
