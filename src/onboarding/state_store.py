"""State storage boundary for the local onboarding prototype."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
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

    def list_connection_drafts(self) -> list[dict[str, Any]]:
        """Return stored connection drafts."""

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

    def list_connection_drafts(self) -> list[dict[str, Any]]:
        """Return defensive copies of connection drafts in creation order."""
        with self._lock:
            return [copy.deepcopy(draft) for draft in self._connection_drafts.values()]

    def save_sync_job(self, sync_job_id: str, sync_job: dict[str, Any]) -> None:
        """Save a defensive copy of a first-sync job."""
        with self._lock:
            self._sync_jobs[sync_job_id] = copy.deepcopy(sync_job)

    def get_sync_job(self, sync_job_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of a first-sync job."""
        with self._lock:
            sync_job = self._sync_jobs.get(sync_job_id)
            return copy.deepcopy(sync_job) if sync_job is not None else None


class JsonFileOnboardingStateStore:
    """Local JSON-backed state store for product-shaped prototype runs.

    The file can contain real account selections, so callers should point it at
    an ignored local path such as `.local/onboarding_state.json`.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._state = self._load_state()

    def reset(self) -> None:
        """Clear state and persist an empty store."""
        with self._lock:
            self._state = _empty_state()
            self._write_state()

    def next_draft_id(self) -> str:
        """Return the next persisted draft id."""
        with self._lock:
            self._state["draft_counter"] = int(self._state.get("draft_counter", 0)) + 1
            self._write_state()
            return f"draft_demo_{self._state['draft_counter']:04d}"

    def next_sync_job_id(self) -> str:
        """Return the next persisted first-sync job id."""
        with self._lock:
            self._state["sync_job_counter"] = int(self._state.get("sync_job_counter", 0)) + 1
            self._write_state()
            return f"sync_demo_{self._state['sync_job_counter']:04d}"

    def save_connection_draft(self, draft_id: str, draft: dict[str, Any]) -> None:
        """Persist a connection draft."""
        with self._lock:
            self._connection_drafts()[draft_id] = copy.deepcopy(draft)
            self._write_state()

    def get_connection_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Return a persisted connection draft."""
        with self._lock:
            draft = self._connection_drafts().get(draft_id)
            return copy.deepcopy(draft) if draft is not None else None

    def list_connection_drafts(self) -> list[dict[str, Any]]:
        """Return persisted connection drafts in creation order."""
        with self._lock:
            return [copy.deepcopy(draft) for draft in self._connection_drafts().values()]

    def save_sync_job(self, sync_job_id: str, sync_job: dict[str, Any]) -> None:
        """Persist a first-sync job."""
        with self._lock:
            self._sync_jobs()[sync_job_id] = copy.deepcopy(sync_job)
            self._write_state()

    def get_sync_job(self, sync_job_id: str) -> dict[str, Any] | None:
        """Return a persisted first-sync job."""
        with self._lock:
            sync_job = self._sync_jobs().get(sync_job_id)
            return copy.deepcopy(sync_job) if sync_job is not None else None

    def _connection_drafts(self) -> dict[str, dict[str, Any]]:
        drafts = self._state.setdefault("connection_drafts", {})
        if not isinstance(drafts, dict):
            self._state["connection_drafts"] = {}
            return self._state["connection_drafts"]
        return drafts

    def _sync_jobs(self) -> dict[str, dict[str, Any]]:
        jobs = self._state.setdefault("sync_jobs", {})
        if not isinstance(jobs, dict):
            self._state["sync_jobs"] = {}
            return self._state["sync_jobs"]
        return jobs

    def _load_state(self) -> dict[str, Any]:
        if not self._path.exists():
            return _empty_state()
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid onboarding state store: {exc.__class__.__name__}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Invalid onboarding state store: root must be an object.")
        return _normalize_state(parsed)

    def _write_state(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self._path.parent),
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.write("\n")
            temp_name = temp_file.name
        try:
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "draft_counter": 0,
        "sync_job_counter": 0,
        "connection_drafts": {},
        "sync_jobs": {},
    }


def _normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = _empty_state()
    normalized["version"] = 1
    normalized["draft_counter"] = _safe_non_negative_int(state.get("draft_counter"))
    normalized["sync_job_counter"] = _safe_non_negative_int(state.get("sync_job_counter"))
    if isinstance(state.get("connection_drafts"), dict):
        normalized["connection_drafts"] = copy.deepcopy(state["connection_drafts"])
    if isinstance(state.get("sync_jobs"), dict):
        normalized["sync_jobs"] = copy.deepcopy(state["sync_jobs"])
    return normalized


def _safe_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
