"""Tests for onboarding first-sync runners."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from src.onboarding.sync_runner import LocalMetaSyncRunner


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
