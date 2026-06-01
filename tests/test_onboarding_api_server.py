"""Tests for the local onboarding prototype API contract."""

from __future__ import annotations

import json
from unittest.mock import Mock

from src.onboarding.api_server import OnboardingPrototypeState
from src.onboarding.state_store import InMemoryOnboardingStateStore


def sample_connection_payload() -> dict:
    """Return a fake connection payload matching the frontend handoff."""
    return {
        "workspace_id": "workspace_demo",
        "connector_id": "meta_ads",
        "authorization_id": "auth_meta_ads_demo",
        "client_name": "Demo Shop Taiwan",
        "accounts": [
            {
                "external_account_id": "act_demo_1001",
                "account_name": "Demo Shop Taiwan",
            }
        ],
        "destinations": ["looker_studio", "ai_report_email", "bigquery"],
        "report_schedule": {
            "report_type": "weekly",
            "delivery_day": "monday",
            "timezone": "Asia/Taipei",
            "depth": "standard",
        },
    }


def test_onboarding_state_lists_connectors_and_destinations() -> None:
    state = OnboardingPrototypeState()

    connectors = state.list_connectors()["connectors"]
    destinations = state.list_destinations()["destinations"]

    assert connectors[0]["id"] == "meta_ads"
    assert connectors[0]["status"] == "available"
    assert any(destination["id"] == "ai_report_email" for destination in destinations)


def test_onboarding_state_oauth_flow_exposes_accounts() -> None:
    state = OnboardingPrototypeState()

    before = state.list_accounts("meta_ads", authorization_id="auth_meta_ads_demo")
    oauth = state.complete_oauth("meta_ads")
    after = state.list_accounts("meta_ads", authorization_id="auth_meta_ads_demo")

    assert before == {"accounts": []}
    assert oauth["status"] == "connected"
    assert after["accounts"][0]["id"] == "act_demo_1001"


def test_onboarding_state_connection_returns_sanitized_config_preview() -> None:
    state = OnboardingPrototypeState()

    response = state.create_connection(sample_connection_payload())
    output = json.dumps(response)

    assert response["ok"] is True
    assert response["draft_id"] == "draft_demo_0001"
    assert response["next_sync_status"] == "queued"
    assert response["connection_ids"] == ["conn_demo_1"]
    assert response["first_sync_job"]["sync_job_id"] == "sync_demo_0001"
    assert response["first_sync_job"]["status"] == "queued"
    assert response["config_preview"]["summary"]["report_schedule_count"] == 1
    assert response["destination_handoff"]["destinations"]["looker_studio"]["status"] == "handoff_required"
    assert response["apply_plan"]["writes_config"] is False
    assert response["apply_plan"]["sensitive_payload_persisted"] is False
    assert "act_demo_1001" not in response["config_preview"]["yaml_text"]
    assert "recipient@example.com" in response["config_preview"]["yaml_text"]
    assert "act_demo_1001" not in output


def test_onboarding_state_accepts_injected_state_store() -> None:
    store = InMemoryOnboardingStateStore()
    state = OnboardingPrototypeState(state_store=store)

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]

    assert store.get_connection_draft(created["draft_id"]) is not None
    assert store.get_sync_job(sync_job_id) is not None
    assert state.get_sync_job(sync_job_id)["sync_job"]["status"] == "running"


def test_onboarding_state_lists_created_account_connections_without_sensitive_ids() -> None:
    state = OnboardingPrototypeState()

    state.create_connection(sample_connection_payload())
    response = state.list_account_connections()
    output = json.dumps(response)

    assert response["ok"] is True
    assert len(response["connections"]) == 1
    connection = response["connections"][0]
    assert connection["draft_id"] == "draft_demo_0001"
    assert connection["first_sync_job_id"] == "sync_demo_0001"
    assert connection["account_count"] == 1
    assert connection["connection_count"] == 1
    assert connection["destinations"] == ["looker_studio", "ai_report_email", "bigquery"]
    assert connection["destination_statuses"]["ai_report_email"] == "config_preview_ready"
    assert connection["report_schedule"]["report_type"] == "weekly"
    assert connection["local_draft_only"] is True
    assert connection["writes_config"] is False
    assert connection["writes_secrets"] is False
    assert "act_demo_1001" not in output


def test_onboarding_state_first_sync_job_advances_without_sensitive_ids() -> None:
    state = OnboardingPrototypeState()

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    running = state.get_sync_job(sync_job_id)
    completed = state.get_sync_job(sync_job_id)
    output = json.dumps(completed)

    assert running["sync_job"]["status"] == "running"
    assert completed["sync_job"]["status"] == "completed"
    assert completed["sync_job"]["progress_percent"] == 100
    assert completed["sync_job"]["summary"]["account_count"] == 1
    assert [step["id"] for step in completed["sync_job"]["steps"]] == [
        "source_connected",
        "warehouse_sync",
        "dashboard_refresh",
        "report_schedule",
    ]
    assert "act_demo_1001" not in output


def test_onboarding_state_attaches_backend_data_check_after_sync_completion() -> None:
    state = OnboardingPrototypeState(
        backend_status_reader=lambda sync_job: {
            "status": "healthy",
            "source": "bigquery",
            "checked_at": "2026-05-31T00:00:00+00:00",
            "message": "Latest Meta sync data is visible.",
            "latest_sync": {
                "status": "success",
                "rows_fetched": 3,
                "rows_inserted": 3,
                "sync_start_date": "2026-05-30",
                "sync_end_date": "2026-05-30",
            },
            "destinations": {
                "bigquery": {"status": "verified", "raw_rows": 3, "unified_rows": 3},
                "looker_studio": {"status": "verified", "ad_daily_rows": 3, "campaign_daily_rows": 2},
            },
            "scope": {
                "selected_account_count": len(sync_job["selected_account_ids"]),
                "selected_accounts_scoped": True,
            },
            "warnings": [],
        }
    )

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    state.get_sync_job(sync_job_id)
    completed = state.get_sync_job(sync_job_id)
    output = json.dumps(completed)

    assert completed["sync_job"]["backend_data_check"]["status"] == "healthy"
    assert completed["sync_job"]["backend_data_check"]["latest_sync"]["rows_inserted"] == 3
    assert completed["sync_job"]["backend_data_check"]["scope"]["selected_account_count"] == 1
    assert "act_demo_1001" not in output


def test_onboarding_state_backend_data_check_failures_do_not_break_sync_status() -> None:
    def failing_reader(sync_job: dict) -> dict:
        raise RuntimeError("boom")

    state = OnboardingPrototypeState(backend_status_reader=failing_reader)

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    state.get_sync_job(sync_job_id)
    completed = state.get_sync_job(sync_job_id)

    assert completed["sync_job"]["status"] == "completed"
    assert completed["sync_job"]["backend_data_check"]["status"] == "unavailable"
    assert completed["sync_job"]["backend_data_check"]["warnings"] == ["backend_status_check_failed"]


def test_onboarding_state_sends_report_email_for_completed_sync_job() -> None:
    sent_jobs: list[dict] = []

    def fake_email_sender(sync_job: dict) -> dict:
        sent_jobs.append(sync_job)
        return {
            "status": "sent",
            "message": "Report email sent.",
            "report_id": "report_demo",
            "report_type": "monthly",
            "period_start_date": "2026-05-01",
            "recipient_configured": True,
        }

    state = OnboardingPrototypeState(email_report_sender=fake_email_sender)

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    state.get_sync_job(sync_job_id)
    state.get_sync_job(sync_job_id)
    response = state.send_report_email(sync_job_id)
    second_response = state.send_report_email(sync_job_id)
    output = json.dumps(response)

    assert response["ok"] is True
    assert response["email_delivery"]["status"] == "sent"
    assert second_response["email_delivery"]["report_id"] == "report_demo"
    assert len(sent_jobs) == 1
    assert sent_jobs[0]["selected_account_ids"] == ["act_demo_1001"]
    assert "act_demo_1001" not in output


def test_onboarding_state_blocks_duplicate_report_email_while_sending() -> None:
    duplicate_response: dict | None = None

    def fake_email_sender(sync_job: dict) -> dict:
        nonlocal duplicate_response
        duplicate_response = state.send_report_email(sync_job["sync_job_id"])
        return {
            "status": "sent",
            "message": "Report email sent.",
            "report_id": "report_demo",
            "report_type": "monthly",
            "period_start_date": "2026-05-01",
            "recipient_configured": True,
        }

    state = OnboardingPrototypeState(email_report_sender=fake_email_sender)

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    state.get_sync_job(sync_job_id)
    state.get_sync_job(sync_job_id)
    response = state.send_report_email(sync_job_id)

    assert duplicate_response is not None
    assert duplicate_response["ok"] is False
    assert duplicate_response["email_delivery"]["status"] == "sending"
    assert response["email_delivery"]["status"] == "sent"


def test_onboarding_state_requires_completed_sync_before_report_email() -> None:
    state = OnboardingPrototypeState(email_report_sender=lambda sync_job: {"status": "sent"})

    created = state.create_connection(sample_connection_payload())

    try:
        state.send_report_email(created["first_sync_job"]["sync_job_id"])
    except ValueError as exc:
        assert str(exc) == "First sync must complete before sending report email."
    else:
        raise AssertionError("Expected incomplete sync to block report email.")


def test_onboarding_state_persists_unavailable_report_email_status() -> None:
    state = OnboardingPrototypeState()

    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    state.get_sync_job(sync_job_id)
    state.get_sync_job(sync_job_id)
    response = state.send_report_email(sync_job_id)
    status = state.get_sync_job(sync_job_id)

    assert response["ok"] is False
    assert response["email_delivery"]["status"] == "unavailable"
    assert status["sync_job"]["email_delivery"]["status"] == "unavailable"


def test_onboarding_state_exposes_sanitized_connection_draft_and_apply_plan() -> None:
    state = OnboardingPrototypeState()

    created = state.create_connection(sample_connection_payload())
    draft = state.get_connection_draft(created["draft_id"])
    apply_plan = state.get_apply_plan(created["draft_id"])
    draft_output = json.dumps(draft)
    plan_output = json.dumps(apply_plan)

    assert draft["ok"] is True
    assert draft["draft"]["local_draft_only"] is True
    assert draft["draft"]["destination_handoff"]["writes_config"] is False
    assert apply_plan["apply_plan"]["draft_id"] == created["draft_id"]
    assert "run_ai_report_preflight" in {
        step["id"] for step in apply_plan["apply_plan"]["steps"]
    }
    assert "act_demo_1001" not in draft_output
    assert "act_demo_1001" not in plan_output


def test_onboarding_state_can_use_real_meta_connector_for_accounts() -> None:
    connector = Mock()
    connector.fetch_ad_accounts.return_value = [
        {
            "id": "act_000000000000001",
            "name": "Real Meta Sample",
            "currency": "TWD",
            "timezone": "Asia/Taipei",
            "status": "Active",
        }
    ]
    state = OnboardingPrototypeState(meta_connector=connector, use_real_meta=True)

    oauth = state.complete_oauth("meta_ads")
    accounts = state.list_accounts("meta_ads", authorization_id="auth_meta_ads_demo")
    connectors = state.list_connectors()["connectors"]

    assert oauth["status"] == "connected"
    assert accounts["accounts"][0]["name"] == "Real Meta Sample"
    assert connectors[0]["data_mode"] == "real_meta_api"
    connector.fetch_ad_accounts.assert_called_once_with()


def test_onboarding_state_reset_clears_real_meta_cache_and_local_drafts() -> None:
    connector = Mock()
    connector.fetch_ad_accounts.return_value = [
        {
            "id": "act_000000000000001",
            "name": "Real Meta Sample",
            "currency": "TWD",
            "timezone": "Asia/Taipei",
            "status": "Active",
        }
    ]
    state = OnboardingPrototypeState(meta_connector=connector, use_real_meta=True)

    state.complete_oauth("meta_ads")
    created = state.create_connection(sample_connection_payload())
    sync_job_id = created["first_sync_job"]["sync_job_id"]
    reset = state.reset()

    assert reset == {"ok": True}
    assert state.list_accounts("meta_ads", authorization_id="auth_meta_ads_demo") == {"accounts": []}
    try:
        state.get_sync_job(sync_job_id)
    except ValueError as exc:
        assert str(exc) == "Unknown sync job."
    else:
        raise AssertionError("Expected reset to clear local sync jobs.")
    try:
        state.get_connection_draft(created["draft_id"])
    except ValueError as exc:
        assert str(exc) == "Unknown connection draft."
    else:
        raise AssertionError("Expected reset to clear local connection drafts.")
