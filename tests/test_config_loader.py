"""Tests for pipeline config loading."""

from pathlib import Path

import pytest
import yaml

from src.utils.config_loader import load_config


def write_yaml(path: Path, data: object) -> None:
    """Write YAML test data."""
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_config_reads_example_config() -> None:
    """The committed example config is valid."""
    config = load_config("config/clients.example.yaml")

    assert config["workspace_id"] == "mark_internal"
    assert config["clients"][0]["client_id"] == "demo_client_001"
    assert config["clients"][0]["platforms"]["meta_ads"]["enabled"] is True


def test_load_config_raises_for_missing_file(tmp_path: Path) -> None:
    """Missing config paths raise FileNotFoundError."""
    missing_path = tmp_path / "clients.yaml"

    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(str(missing_path))


def test_load_config_raises_for_empty_file(tmp_path: Path) -> None:
    """Empty YAML files are rejected."""
    config_path = tmp_path / "clients.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file is empty"):
        load_config(str(config_path))


def test_load_config_raises_for_missing_workspace_id(tmp_path: Path) -> None:
    """workspace_id is required."""
    config_path = tmp_path / "clients.yaml"
    write_yaml(
        config_path,
        {
            "clients": [
                {
                    "client_id": "demo_client_001",
                    "platforms": {},
                    "destinations": {},
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="config.workspace_id"):
        load_config(str(config_path))


def test_load_config_raises_for_missing_client_fields(tmp_path: Path) -> None:
    """Each client must include platforms and destinations."""
    config_path = tmp_path / "clients.yaml"
    write_yaml(
        config_path,
        {
            "workspace_id": "mark_internal",
            "clients": [{"client_id": "demo_client_001", "platforms": {}}],
        },
    )

    with pytest.raises(ValueError, match=r"config\.clients\[0\]\.destinations"):
        load_config(str(config_path))


def test_load_config_raises_for_empty_clients(tmp_path: Path) -> None:
    """clients must be a non-empty list."""
    config_path = tmp_path / "clients.yaml"
    write_yaml(config_path, {"workspace_id": "mark_internal", "clients": []})

    with pytest.raises(ValueError, match="config.clients must be a non-empty list"):
        load_config(str(config_path))
