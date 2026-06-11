"""Tests for developer Makefile targets."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_makefile_includes_account_report_ops_targets() -> None:
    """Productized account-report operations are available as make targets."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "ai-report-deploy-dry-run:" in makefile
    assert "ai-report-status:" in makefile
    assert "ai-report-ready:" in makefile
    assert "ai-report-preflight:" in makefile
    assert "ai-report-logs:" in makefile
    assert "ai-report-post-run:" in makefile
    assert "ai-report-verify:" in makefile
    assert "deploy/check_account_ai_report_ready.sh" in makefile
    assert "deploy/check_account_ai_report_status.sh" in makefile
    assert "deploy/check_account_ai_report_logs.sh" in makefile
    assert "deploy/verify_account_ai_report_post_run.sh" in makefile
    assert "deploy/verify_account_ai_report_ops.sh" in makefile


def test_makefile_includes_sync_targets() -> None:
    """The cloud sync/backfill lifecycle is available as make targets."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "refresh-marts:" in makefile
    assert "backfill:" in makefile
    assert "daily-sync:" in makefile
    assert "daily-sync-deploy:" in makefile
    assert "dispatch-reports:" in makefile
