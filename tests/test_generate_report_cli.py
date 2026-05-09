"""Tests for AI report CLI helpers."""

from src.ai.generate_report import _load_runtime_config


def test_load_runtime_config_prefers_yaml_env(monkeypatch) -> None:
    """Cloud Run can provide AI report config through Secret Manager env vars."""
    monkeypatch.setenv(
        "CLIENTS_CONFIG_YAML",
        """
        workspace_id: mark_internal
        clients:
          - client_id: demo_client_001
            platforms: {}
            destinations: {}
        """,
    )

    config = _load_runtime_config()

    assert config["workspace_id"] == "mark_internal"
    assert config["clients"][0]["client_id"] == "demo_client_001"
