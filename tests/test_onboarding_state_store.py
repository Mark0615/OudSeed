"""Tests for onboarding prototype state storage."""

from __future__ import annotations

from src.onboarding.state_store import InMemoryOnboardingStateStore


def test_in_memory_onboarding_state_store_generates_local_ids() -> None:
    store = InMemoryOnboardingStateStore()

    assert store.next_draft_id() == "draft_demo_0001"
    assert store.next_draft_id() == "draft_demo_0002"
    assert store.next_sync_job_id() == "sync_demo_0001"
    assert store.next_sync_job_id() == "sync_demo_0002"


def test_in_memory_onboarding_state_store_uses_defensive_copies() -> None:
    store = InMemoryOnboardingStateStore()
    draft_id = store.next_draft_id()
    sync_job_id = store.next_sync_job_id()

    draft = {"safe_detail": {"status": "draft"}}
    sync_job = {"status": "queued", "nested": {"checks": 0}}
    store.save_connection_draft(draft_id, draft)
    store.save_sync_job(sync_job_id, sync_job)

    draft["safe_detail"]["status"] = "mutated_after_save"
    sync_job["nested"]["checks"] = 99
    loaded_draft = store.get_connection_draft(draft_id)
    loaded_sync_job = store.get_sync_job(sync_job_id)
    assert loaded_draft is not None
    assert loaded_sync_job is not None
    loaded_draft["safe_detail"]["status"] = "mutated_after_load"
    loaded_sync_job["nested"]["checks"] = 10

    assert store.get_connection_draft(draft_id) == {"safe_detail": {"status": "draft"}}
    assert store.get_sync_job(sync_job_id) == {"status": "queued", "nested": {"checks": 0}}


def test_in_memory_onboarding_state_store_lists_connection_drafts_safely() -> None:
    store = InMemoryOnboardingStateStore()
    first_draft_id = store.next_draft_id()
    second_draft_id = store.next_draft_id()
    store.save_connection_draft(first_draft_id, {"safe_detail": {"draft_id": first_draft_id}})
    store.save_connection_draft(second_draft_id, {"safe_detail": {"draft_id": second_draft_id}})

    drafts = store.list_connection_drafts()
    drafts[0]["safe_detail"]["draft_id"] = "mutated"

    assert [draft["safe_detail"]["draft_id"] for draft in store.list_connection_drafts()] == [
        first_draft_id,
        second_draft_id,
    ]


def test_in_memory_onboarding_state_store_reset_clears_state_and_counters() -> None:
    store = InMemoryOnboardingStateStore()
    draft_id = store.next_draft_id()
    sync_job_id = store.next_sync_job_id()
    store.save_connection_draft(draft_id, {"safe_detail": {}})
    store.save_sync_job(sync_job_id, {"status": "queued"})

    store.reset()

    assert store.get_connection_draft(draft_id) is None
    assert store.get_sync_job(sync_job_id) is None
    assert store.next_draft_id() == "draft_demo_0001"
    assert store.next_sync_job_id() == "sync_demo_0001"
