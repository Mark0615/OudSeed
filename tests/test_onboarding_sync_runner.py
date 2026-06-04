"""Tests for onboarding first-sync runners."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from src.onboarding.sync_runner import LocalGoogleAdsSyncRunner, LocalMetaSyncRunner, LocalPlatformSyncRunner


def sample_selection() -> dict[str, Any]:
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
        "destinations": ["bigquery"],
    }


def sample_google_selection() -> dict[str, Any]:
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
        "destinations": ["bigquery"],
    }


def test_local_meta_sync_runner_exports_config_and_runs_subprocess(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess signature is intentionally loose.
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="event=ok", stderr="")

    monkeypatch.setenv("META_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(subprocess, "run", fake_run)
    config_path = tmp_path / "clients.generated.yaml"
    runner = LocalMetaSyncRunner(
        config_path=config_path,
        repo_root=Path("/tmp/repo"),
        python_bin="python-bin",
        timeout_seconds=123,
    )

    result = runner({"sync_job_id": "sync_demo_0001"}, sample_selection())

    assert result["status"] == "success"
    assert result["runner"] == "local_meta_sync"
    assert result["account_count"] == 1
    assert result["writes_bigquery"] is True
    assert result["readiness"]["ready"] is True
    assert calls[0]["command"] == ["python-bin", "-m", "src.main"]
    assert calls[0]["cwd"] == "/tmp/repo"
    assert calls[0]["timeout"] == 123
    assert calls[0]["env"]["CLIENTS_CONFIG_PATH"] == str(config_path)
    assert calls[0]["env"]["ONBOARDING_LIVE_SYNC_PLATFORM"] == "meta_ads"
    assert calls[0]["env"]["SYNC_ENABLED_PLATFORMS"] == "meta_ads"
    assert "act_demo_1001" in config_path.read_text(encoding="utf-8")


def test_local_meta_sync_runner_raises_safe_error_on_subprocess_failure(monkeypatch, tmp_path) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess signature is intentionally loose.
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="sensitive details")

    monkeypatch.setenv("META_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = LocalMetaSyncRunner(
        config_path=tmp_path / "clients.generated.yaml",
        repo_root=Path("/tmp/repo"),
    )

    try:
        runner({"sync_job_id": "sync_demo_0001"}, sample_selection())
    except RuntimeError as exc:
        assert str(exc) == "local_meta_sync_failed"
    else:
        raise AssertionError("Expected local sync failure to raise a safe error.")


def test_local_meta_sync_runner_blocks_when_readiness_fails(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess signature is intentionally loose.
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="event=ok", stderr="")

    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    config_path = tmp_path / "clients.generated.yaml"
    runner = LocalMetaSyncRunner(
        config_path=config_path,
        repo_root=Path("/tmp/repo"),
    )

    try:
        runner({"sync_job_id": "sync_demo_0001"}, sample_selection())
    except RuntimeError as exc:
        assert str(exc) == "local_meta_sync_not_ready"
    else:
        raise AssertionError("Expected local sync readiness gate to block execution.")

    assert calls == []
    assert "act_demo_1001" in config_path.read_text(encoding="utf-8")


def test_local_google_ads_sync_runner_exports_config_and_runs_subprocess(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess signature is intentionally loose.
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="event=ok", stderr="")

    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "fake-developer-token")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "fake-refresh-token")
    monkeypatch.setattr(subprocess, "run", fake_run)
    config_path = tmp_path / "clients.generated.yaml"
    runner = LocalGoogleAdsSyncRunner(
        config_path=config_path,
        repo_root=Path("/tmp/repo"),
        python_bin="python-bin",
        timeout_seconds=123,
    )

    result = runner({"sync_job_id": "sync_demo_0001"}, sample_google_selection())

    assert result["status"] == "success"
    assert result["runner"] == "local_google_ads_sync"
    assert result["platform"] == "google_ads"
    assert result["account_count"] == 1
    assert result["writes_bigquery"] is True
    assert result["readiness"]["ready"] is True
    assert calls[0]["command"] == ["python-bin", "-m", "src.main"]
    assert calls[0]["cwd"] == "/tmp/repo"
    assert calls[0]["timeout"] == 123
    assert calls[0]["env"]["CLIENTS_CONFIG_PATH"] == str(config_path)
    assert calls[0]["env"]["ONBOARDING_LIVE_SYNC_PLATFORM"] == "google_ads"
    assert calls[0]["env"]["SYNC_ENABLED_PLATFORMS"] == "google_ads"
    assert "1234567890" in config_path.read_text(encoding="utf-8")


def test_local_google_ads_sync_runner_blocks_when_readiness_fails(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess signature is intentionally loose.
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="event=ok", stderr="")

    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    config_path = tmp_path / "clients.generated.yaml"
    runner = LocalGoogleAdsSyncRunner(
        config_path=config_path,
        repo_root=Path("/tmp/repo"),
    )

    try:
        runner({"sync_job_id": "sync_demo_0001"}, sample_google_selection())
    except RuntimeError as exc:
        assert str(exc) == "local_google_ads_sync_not_ready"
    else:
        raise AssertionError("Expected local Google Ads sync readiness gate to block execution.")

    assert calls == []
    assert "1234567890" in config_path.read_text(encoding="utf-8")


def test_local_platform_sync_runner_rejects_unknown_platform(tmp_path) -> None:
    try:
        LocalPlatformSyncRunner(
            platform="line_ads",
            config_path=tmp_path / "clients.generated.yaml",
            repo_root=Path("/tmp/repo"),
        )
    except ValueError as exc:
        assert "platform must be" in str(exc)
    else:
        raise AssertionError("Expected unknown local sync platform to be rejected.")
