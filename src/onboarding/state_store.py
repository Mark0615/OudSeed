"""State storage boundary for the local onboarding prototype."""

from __future__ import annotations

import copy
import threading
from typing import Any, Protocol


class OnboardingStateStore(Protocol):
    """Storage contract for connection drafts and first-sync jobs."""

    def reset(self) -> None:
        """Clear all stored onboarding state."""

    def next_draft_id(self) -> str:
        """Return the next connection draft id."""

    def next_sync_job_id(self) -> str:
        """Return the next first-sync job id."""

    def save_connection_draft(self, draft_id: str, draft: dict[str, Any]) -> None:
        """Persist a connection draft."""

    def get_connection_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Return a connection draft, or None when it is unknown."""

    def save_sync_job(self, sync_job_id: str, sync_job: dict[str, Any]) -> None:
        """Persist a first-sync job."""

    def get_sync_job(self, sync_job_id: str) -> dict[str, Any] | None:
        """Return a first-sync job, or None when it is unknown."""


class InMemoryOnboardingStateStore:
    """Thread-safe local state store used by the prototype server.

    This keeps sensitive account selections process-local. Future durable
    implementations can replace this class without changing the HTTP contract.
    """

    def __init__(self) -> None:
        self._connection_drafts: dict[str, dict[str, Any]] = {}
        self._sync_jobs: dict[str, dict[str, Any]] = {}
        self._draft_counter = 0
        self._sync_job_counter = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Clear local state and reset prototype counters."""
        with self._lock:
            self._connection_drafts.clear()
            self._sync_jobs.clear()
            self._draft_counter = 0
            self._sync_job_counter = 0

    def next_draft_id(self) -> str:
        """Return the next local draft id."""
        with self._lock:
            self._draft_counter += 1
            return f"draft_demo_{self._draft_counter:04d}"

    def next_sync_job_id(self) -> str:
        """Return the next local first-sync job id."""
        with self._lock:
            self._sync_job_counter += 1
            return f"sync_demo_{self._sync_job_counter:04d}"

    def save_connection_draft(self, draft_id: str, draft: dict[str, Any]) -> None:
        """Save a defensive copy of a connection draft."""
        with self._lock:
            self._connection_drafts[draft_id] = copy.deepcopy(draft)

    def get_connection_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of a connection draft."""
        with self._lock:
            draft = self._connection_drafts.get(draft_id)
            return copy.deepcopy(draft) if draft is not None else None

    def save_sync_job(self, sync_job_id: str, sync_job: dict[str, Any]) -> None:
        """Save a defensive copy of a first-sync job."""
        with self._lock:
            self._sync_jobs[sync_job_id] = copy.deepcopy(sync_job)

    def get_sync_job(self, sync_job_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of a first-sync job."""
        with self._lock:
            sync_job = self._sync_jobs.get(sync_job_id)
            return copy.deepcopy(sync_job) if sync_job is not None else None
