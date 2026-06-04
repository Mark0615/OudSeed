"""Tests for Cloud Run deployment shell wrappers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_deploy_dry_run(script_name: str, env_file: Path, clients_file: Path) -> str:
    env = {
        **os.environ,
        "DEPLOY_DRY_RUN": "true",
        "ENV_FILE": str(env_file),
        "CLIENTS_CONFIG_FILE": str(clients_file),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "deploy" / script_name)],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def test_account_report_deploy_wrapper_preserves_production_defaults(tmp_path: Path) -> None:
    """Account-report wrapper defaults win over older values from .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=fake-openai-key",
                "OPENAI_MAX_OUTPUT_TOKENS=1800",
                "OPENAI_TIMEOUT_SECONDS=60",
                "JOB_MAX_RETRIES=1",
                "SMTP_PASSWORD=fake-smtp-password",
            ]
        ),
        encoding="utf-8",
    )
    clients_file = tmp_path / "clients.yaml"
    clients_file.write_text("workspace_id: test_workspace\nclients: []\n", encoding="utf-8")

    output = _run_deploy_dry_run("deploy_account_ai_report_job.sh", env_file, clients_file)

    assert "deploy_dry_run=true" in output
    assert "job=oudseed-account-ai-report" in output
    assert "ai_report_module=src.ai.send_account_reports" in output
    assert "openai_max_output_tokens=5000" in output
    assert "openai_timeout_seconds=180" in output
    assert "job_max_retries=0" in output
    assert "ai_report_schedule_id_configured=true" in output
    assert "smtp_password_configured=true" in output
    assert "fake-openai-key" not in output
    assert "fake-smtp-password" not in output


def test_deploy_dry_run_prints_sanitized_config_without_gcloud(tmp_path: Path) -> None:
    """Dry run validates effective config without requiring gcloud side effects."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=fake-openai-key",
                "OPENAI_TIMEOUT_SECONDS=90",
                "AI_REPORT_EMAIL_TO=recipient@example.com",
                "SMTP_PASSWORD=fake-smtp-password",
            ]
        ),
        encoding="utf-8",
    )
    clients_file = tmp_path / "clients.yaml"
    clients_file.write_text("workspace_id: test_workspace\nclients: []\n", encoding="utf-8")

    output = _run_deploy_dry_run("deploy_ai_report_job.sh", env_file, clients_file)

    assert "deploy_dry_run=true" in output
    assert "job=oudseed-ai-report" in output
    assert "openai_timeout_seconds=90" in output
    assert "job_max_retries=1" in output
    assert "openai_api_key_configured=true" in output
    assert "clients_config_file_exists=true" in output
    assert "ai_report_email_to_configured=true" in output
    assert "smtp_password_configured=true" in output
    assert "recipient@example.com" not in output
    assert "fake-openai-key" not in output
    assert "fake-smtp-password" not in output


def test_deploy_dry_run_does_not_require_real_secrets(tmp_path: Path) -> None:
    """Dry-run previews config even when secrets or local clients config are absent."""
    missing_env_file = tmp_path / "missing.env"
    missing_clients_file = tmp_path / "missing-clients.yaml"

    output = _run_deploy_dry_run("deploy_account_ai_report_job.sh", missing_env_file, missing_clients_file)

    assert "deploy_dry_run=true" in output
    assert "openai_api_key_configured=false" in output
    assert "clients_config_file_exists=false" in output
    assert "openai_timeout_seconds=180" in output
    assert "job_max_retries=0" in output


def test_deploy_shell_scripts_have_valid_syntax() -> None:
    """Deployment helper scripts remain parseable by bash."""
    script_names = [
        "deploy_ai_report_job.sh",
        "deploy_account_ai_report_job.sh",
        "check_account_ai_report_ready.sh",
        "check_account_ai_report_status.sh",
        "check_account_ai_report_logs.sh",
        "verify_account_ai_report_post_run.sh",
        "verify_account_ai_report_ops.sh",
        "run_account_ai_report_preflight.sh",
    ]

    for script_name in script_names:
        subprocess.run(
            ["bash", "-n", str(ROOT / "deploy" / script_name)],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )


def test_status_script_uses_sanitized_output_labels() -> None:
    """Status helper reports configured flags instead of sensitive values."""
    script = (ROOT / "deploy" / "check_account_ai_report_status.sh").read_text(encoding="utf-8")

    assert "recipient_configured" in script
    assert "openai_secret_configured" in script
    assert "smtp_password_secret_configured" in script
    assert "plain_value('AI_REPORT_EMAIL_TO" not in script
    assert "plain_value('OPENAI_API_KEY" not in script
    assert "plain_value('SMTP_PASSWORD" not in script


def test_verify_ops_script_requires_batch_completeness_only_with_created_after() -> None:
    """Full verification avoids failing on older period-level test noise by default."""
    script = (ROOT / "deploy" / "verify_account_ai_report_ops.sh").read_text(encoding="utf-8")

    assert 'if [[ -n "${AI_REPORT_LOG_CREATED_AFTER:-}" ]]' in script
    assert 'require_complete="${AI_REPORT_LOG_REQUIRE_COMPLETE:-true}"' in script
    assert 'require_complete="${AI_REPORT_LOG_REQUIRE_COMPLETE:-false}"' in script
    assert "informational log check" in script


def test_ready_script_checks_production_account_report_settings() -> None:
    """Readiness gate covers settings that would make scheduled sends unsafe."""
    script = (ROOT / "deploy" / "check_account_ai_report_ready.sh").read_text(encoding="utf-8")

    assert "account_report_ready=" in script
    assert "preflight_disabled" in script
    assert "AI_REPORT_SCHEDULE_ID" in script
    assert "OPENAI_TIMEOUT_SECONDS" in script
    assert "OPENAI_MAX_OUTPUT_TOKENS" in script
    assert "scheduler_enabled" in script
    assert "scheduler_next_schedule_time" in script


def test_post_run_script_requires_batch_window_and_strict_logs() -> None:
    """Post-run verification requires a specific period and batch window."""
    script = (ROOT / "deploy" / "verify_account_ai_report_post_run.sh").read_text(encoding="utf-8")

    assert "Missing AI_REPORT_PERIOD_START_DATE" in script
    assert "Missing AI_REPORT_LOG_CREATED_AFTER" in script
    assert "AI_REPORT_LOG_REQUIRE_COMPLETE=true" in script
    assert 'AI_REPORT_LOG_SHOW_ROWS="${AI_REPORT_LOG_SHOW_ROWS:-false}"' in script
