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


def _require_mapping_key(mapping: dict[str, Any], key: str, location: str) -> Any:
    """Return a required value or raise a clear validation error."""
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"Missing required field: {location}.{key}")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"Required field cannot be empty: {location}.{key}")
    return value
