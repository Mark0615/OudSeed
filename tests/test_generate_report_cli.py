"""Tests for AI report CLI helpers."""

import pytest

from src.ai.generate_report import _load_runtime_config, _positive_int_env, _report_depth


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


def test_positive_int_env_uses_default_for_missing_or_empty(monkeypatch) -> None:
    """Positive integer env helper supports scheduled job defaults."""
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)
    assert _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60) == 60

    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "")
    assert _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60) == 60


def test_positive_int_env_reads_valid_value(monkeypatch) -> None:
    """Positive integer env helper reads configured values."""
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "120")
    assert _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60) == 120


def test_positive_int_env_rejects_invalid_values(monkeypatch) -> None:
    """Invalid integer env values fail clearly."""
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="positive integer"):
        _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60)

    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "slow")
    with pytest.raises(ValueError, match="positive integer"):
        _positive_int_env("OPENAI_TIMEOUT_SECONDS", 60)


def test_report_depth_rejects_invalid_value() -> None:
    """AI report depth is constrained to product-supported modes."""
    assert _report_depth("standard") == "standard"

    with pytest.raises(ValueError, match="AI_REPORT_DEPTH"):
        _report_depth("verbose")
