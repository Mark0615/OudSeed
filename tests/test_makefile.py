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
    assert "onboarding-prototype-persistent:" in makefile
    assert "onboarding-prototype-live-sync:" in makefile
    assert "onboarding-live-sync-ready:" in makefile
    assert "onboarding-sync-local-config:" in makefile
    assert "ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json" in makefile
    assert "ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml" in makefile
    assert "ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true" in makefile
    assert "src.onboarding.live_sync_readiness" in makefile
    assert "CLIENTS_CONFIG_PATH=.local/clients.generated.yaml" in makefile
    assert "SYNC_ENABLED_PLATFORMS=meta_ads" in makefile
    assert "deploy/check_account_ai_report_ready.sh" in makefile
    assert "deploy/check_account_ai_report_status.sh" in makefile
    assert "deploy/check_account_ai_report_logs.sh" in makefile
    assert "deploy/verify_account_ai_report_post_run.sh" in makefile
    assert "deploy/verify_account_ai_report_ops.sh" in makefile


def test_productization_status_doc_tracks_operational_commands() -> None:
    """Productization status doc captures the account-report ops flow."""
    doc = (ROOT / "docs" / "productization_status.md").read_text(encoding="utf-8")

    assert "oudseed-account-ai-report" in doc
    assert "make ai-report-ready" in doc
    assert "make ai-report-post-run" in doc
    assert "make ai-report-verify" in doc
    assert "gpt-5.2" in doc
    assert "2026-05-31T21:00:00Z" in doc
    assert "AI_REPORT_PERIOD_START_DATE=2026-05-01" in doc
    assert "preflight_enabled=false" in doc
