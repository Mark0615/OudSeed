"""Local prototype API server for connector onboarding."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from google.cloud import bigquery

from src.connectors.google_ads import GoogleAdsConnector
from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination
from src.onboarding.config_bridge import (
    build_config_preview_response,
    export_local_clients_config,
    export_local_clients_config_from_selections,
    format_local_export_summary,
)
from src.onboarding.live_sync_readiness import build_live_sync_readiness_from_env
from src.onboarding.state_store import (
    InMemoryOnboardingStateStore,
    JsonFileOnboardingStateStore,
    OnboardingStateStore,
)
from src.onboarding.sync_runner import (
    LocalPlatformSyncRunner,
    OnboardingFirstSyncRunner,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "prototype"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class OnboardingPrototypeState:
    """In-memory state for the local onboarding prototype."""

    def __init__(
        self,
        *,
        google_connector: GoogleAdsConnector | None = None,
        meta_connector: MetaAdsConnector | None = None,
        use_real_google_ads: bool = False,
        use_real_meta: bool = False,
        backend_status_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        email_report_sender: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        local_config_exporter: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        first_sync_runner: OnboardingFirstSyncRunner | None = None,
        state_store: OnboardingStateStore | None = None,
    ) -> None:
        self._connectors = _default_connectors()
        self._accounts_by_connector = _default_accounts_by_connector()
        self._destinations = _default_destinations()
        self._google_connector = google_connector
        self._meta_connector = meta_connector
        self._use_real_google_ads = use_real_google_ads
        self._use_real_meta = use_real_meta
        self._backend_status_reader = backend_status_reader
        self._email_report_sender = email_report_sender
        self._local_config_exporter = local_config_exporter
        self._first_sync_runner = first_sync_runner
        self._state_store = state_store or InMemoryOnboardingStateStore()
        self._account_id_aliases_by_connector: dict[str, dict[str, str]] = {}
        self._real_meta_loaded = False
        self._real_google_ads_loaded = False
        self._email_delivery_lock = threading.Lock()
        self._first_sync_lock = threading.Lock()
        if use_real_meta:
            self._mark_real_meta_mode()
        if use_real_google_ads:
            self._mark_real_google_ads_mode()

    def reset(self) -> dict[str, Any]:
        """Reset prototype authorization state."""
        for connector in self._connectors:
            connector["connected"] = False
        if self._use_real_meta:
            self._accounts_by_connector["meta_ads"] = []
            self._account_id_aliases_by_connector["meta_ads"] = {}
            self._real_meta_loaded = False
        if self._use_real_google_ads:
            self._accounts_by_connector["google_ads"] = []
            self._account_id_aliases_by_connector["google_ads"] = {}
            self._real_google_ads_loaded = False
        self._state_store.reset()
        return {"ok": True}

    def list_connectors(self) -> dict[str, Any]:
        """Return available connectors with connection status."""
        return {
            "connectors": [
                {
                    **connector,
                    "connected_account_count": (
                        len(self._accounts_by_connector.get(str(connector["id"]), []))
                        if connector.get("connected")
                        else 0
                    ),
                }
                for connector in self._connectors
            ]
        }

    def list_destinations(self) -> dict[str, Any]:
        """Return available destinations."""
        return {"destinations": self._destinations}

    def start_oauth(self, connector_id: str) -> dict[str, Any]:
        """Return a simulated OAuth start response."""
        connector = self._require_available_connector(connector_id)
        return {
            "authorization_url": f"https://auth.example.test/{connector['id']}/authorize",
            "state": "prototype_state",
        }

    def complete_oauth(self, connector_id: str) -> dict[str, Any]:
        """Mark a connector as connected for the local prototype."""
        connector = self._require_available_connector(connector_id)
        connector["connected"] = True
        if connector_id == "meta_ads" and self._use_real_meta:
            self._load_real_meta_accounts()
        if connector_id == "google_ads" and self._use_real_google_ads:
            self._load_real_google_ads_accounts()
        return {
            "authorization_id": f"auth_{connector_id}_demo",
            "connector_id": connector_id,
            "status": "connected",
        }

    def list_accounts(self, connector_id: str, authorization_id: str | None = None) -> dict[str, Any]:
        """Return ad accounts for a connected connector."""
        connector = self._find_connector(connector_id)
        if not connector or not connector.get("connected"):
            return {"accounts": []}
        if authorization_id and authorization_id != f"auth_{connector_id}_demo":
            raise ValueError("Unknown authorization_id.")
        if connector_id == "meta_ads" and self._use_real_meta:
            self._load_real_meta_accounts()
        if connector_id == "google_ads" and self._use_real_google_ads:
            self._load_real_google_ads_accounts()
        return {"accounts": self._accounts_by_connector.get(connector_id, [])}

    def create_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate a selection payload and return a local draft handoff."""
        resolved_payload = self._resolve_selection_account_ids(payload)
        response = build_config_preview_response(resolved_payload)
        account_count = response["config_preview"]["summary"]["account_count"]
        draft_id = self._state_store.next_draft_id()
        draft = {
            "draft_id": draft_id,
            "status": "draft",
            "created_at": _utc_now(),
            "account_group_name": str(resolved_payload.get("client_name") or "Selected account"),
            "connector_id": _selection_platform(resolved_payload),
            "initial_sync": _selection_initial_sync(resolved_payload),
            "local_draft_only": True,
            "writes_config": False,
            "writes_secrets": False,
            "connection_ids": [f"conn_demo_{index + 1}" for index in range(account_count)],
            "config_preview": response["config_preview"],
            "destination_handoff": _build_destination_handoff(resolved_payload),
            "apply_plan": _build_apply_plan(resolved_payload, draft_id),
        }
        sync_job = self._create_first_sync_job(draft_id, resolved_payload, account_count)
        draft["first_sync_job_id"] = sync_job["sync_job_id"]
        self._state_store.save_connection_draft(
            draft_id,
            {
                "raw_selection": resolved_payload,
                "safe_detail": draft,
            },
        )
        local_config_export = self._export_local_config_from_current_drafts()
        if local_config_export:
            draft["local_config_export"] = local_config_export
            self._attach_local_config_export_to_drafts(local_config_export)
        return {
            "ok": True,
            "draft_id": draft_id,
            "connection_ids": draft["connection_ids"],
            "next_sync_status": "queued",
            "first_sync_job": sync_job,
            "config_preview": response["config_preview"],
            "destination_handoff": draft["destination_handoff"],
            "apply_plan": draft["apply_plan"],
            **({"local_config_export": local_config_export} if local_config_export else {}),
        }

    def config_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return only the sanitized config preview response."""
        return build_config_preview_response(payload)

    def get_connection_draft(self, draft_id: str) -> dict[str, Any]:
        """Return a sanitized local draft detail without sensitive source IDs."""
        draft = self._state_store.get_connection_draft(draft_id)
        if not draft:
            raise ValueError("Unknown connection draft.")
        return {"ok": True, "draft": draft["safe_detail"]}

    def list_account_connections(self) -> dict[str, Any]:
        """Return safe summaries for locally created account connections."""
        connections = [
            _public_connection_summary(draft["safe_detail"])
            for draft in self._state_store.list_connection_drafts()
            if isinstance(draft.get("safe_detail"), dict)
        ]
        return {
            "ok": True,
            "connections": connections,
            "connection_groups": _public_connection_group_summaries(connections),
        }

    def live_sync_readiness(self) -> dict[str, Any]:
        """Return safe local live-sync readiness metadata."""
        return {
            "ok": True,
            "live_sync_readiness": build_live_sync_readiness_from_env(),
            "platform_readiness": _build_platform_live_sync_readiness(),
        }

    def get_apply_plan(self, draft_id: str) -> dict[str, Any]:
        """Return the sanitized apply plan for a local draft."""
        draft = self.get_connection_draft(draft_id)["draft"]
        return {"ok": True, "draft_id": draft_id, "apply_plan": draft["apply_plan"]}

    def export_local_config(self, draft_id: str) -> dict[str, Any]:
        """Write a local clients config artifact for a connection draft."""
        draft = self._state_store.get_connection_draft(draft_id)
        if not draft:
            raise ValueError("Unknown connection draft.")
        if not self._local_config_exporter:
            return {
                "ok": False,
                "local_config_export": {
                    "status": "unavailable",
                    "message": "Local config export is not enabled for this prototype run.",
                    "writes_config": False,
                    "writes_secrets": False,
                },
            }
        local_config_export = self._export_local_config_from_current_drafts()
        if not local_config_export:
            return {
                "ok": False,
                "local_config_export": {
                    "status": "unavailable",
                    "message": "Local config export is not enabled for this prototype run.",
                    "writes_config": False,
                    "writes_secrets": False,
                },
            }
        self._attach_local_config_export_to_drafts(local_config_export)
        return {
            "ok": True,
            "local_config_export": local_config_export,
        }

    def _export_local_config_from_current_drafts(self) -> dict[str, Any] | None:
        if not self._local_config_exporter:
            return None
        selections = [
            draft.get("raw_selection")
            for draft in self._state_store.list_connection_drafts()
            if isinstance(draft.get("raw_selection"), dict)
        ]
        if not selections:
            return None
        try:
            export_payload = selections[0] if len(selections) == 1 else {"selections": selections}
            export_summary = self._local_config_exporter(export_payload)
            return {
                "status": "exported",
                **export_summary,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "message": f"Local config export failed: {exc.__class__.__name__}",
                "writes_config": False,
                "writes_secrets": False,
                "local_artifact_only": True,
            }

    def _attach_local_config_export_to_drafts(self, local_config_export: dict[str, Any]) -> None:
        for stored_draft in self._state_store.list_connection_drafts():
            safe_detail = stored_draft.get("safe_detail")
            if not isinstance(safe_detail, dict):
                continue
            draft_id = str(safe_detail.get("draft_id") or "")
            if not draft_id:
                continue
            safe_detail["local_config_export"] = local_config_export
            self._state_store.save_connection_draft(draft_id, stored_draft)

    def get_sync_job(self, sync_job_id: str) -> dict[str, Any]:
        """Return a sanitized first-sync job status for the local prototype."""
        job = self._state_store.get_sync_job(sync_job_id)
        if not job:
            raise ValueError("Unknown sync job.")
        self._advance_sync_job(job)
        self._state_store.save_sync_job(sync_job_id, job)
        return {"ok": True, "sync_job": _public_sync_job(job)}

    def send_report_email(self, sync_job_id: str) -> dict[str, Any]:
        """Send a report email for a completed local sync job."""
        job = self._state_store.get_sync_job(sync_job_id)
        if not job:
            raise ValueError("Unknown sync job.")
        if job.get("status") != "completed":
            raise ValueError("First sync must complete before sending report email.")
        if "ai_report_email" not in job.get("destinations", []):
            raise ValueError("AI Report Email is not enabled for this connection.")
        with self._email_delivery_lock:
            job = self._state_store.get_sync_job(sync_job_id)
            if not job:
                raise ValueError("Unknown sync job.")
            if job.get("status") != "completed":
                raise ValueError("First sync must complete before sending report email.")
            delivery_status = job.get("email_delivery", {}).get("status")
            if delivery_status == "sent":
                return {"ok": True, "email_delivery": job["email_delivery"]}
            if delivery_status == "sending":
                return {"ok": False, "email_delivery": job["email_delivery"]}
            if not self._email_report_sender:
                job["email_delivery"] = {
                    "status": "unavailable",
                    "message": "Email sending is not enabled for this prototype run.",
                    "recipient_configured": False,
                }
                self._state_store.save_sync_job(sync_job_id, job)
                return {"ok": False, "email_delivery": job["email_delivery"]}
            job["email_delivery"] = {
                "status": "sending",
                "message": "Report email is sending.",
                "recipient_configured": True,
            }
            self._state_store.save_sync_job(sync_job_id, job)

        try:
            email_delivery = self._email_report_sender(job)
            with self._email_delivery_lock:
                job = self._state_store.get_sync_job(sync_job_id) or job
                job["email_delivery"] = email_delivery
                self._state_store.save_sync_job(sync_job_id, job)
            return {"ok": True, "email_delivery": email_delivery}
        except Exception as exc:
            email_delivery = {
                "status": "failed",
                "message": f"Report email failed: {exc.__class__.__name__}",
                "recipient_configured": True,
            }
            with self._email_delivery_lock:
                job = self._state_store.get_sync_job(sync_job_id) or job
                job["email_delivery"] = email_delivery
                self._state_store.save_sync_job(sync_job_id, job)
            return {"ok": False, "email_delivery": email_delivery}

    def _find_connector(self, connector_id: str) -> dict[str, Any] | None:
        return next((connector for connector in self._connectors if connector["id"] == connector_id), None)

    def _require_available_connector(self, connector_id: str) -> dict[str, Any]:
        connector = self._find_connector(connector_id)
        if not connector or connector.get("status") != "available":
            raise ValueError("Connector is not available.")
        return connector

    def _mark_real_meta_mode(self) -> None:
        connector = self._find_connector("meta_ads")
        if connector:
            connector["note"] = "Real Meta API via local token"
            connector["data_mode"] = "real_meta_api"

    def _mark_real_google_ads_mode(self) -> None:
        connector = self._find_connector("google_ads")
        if connector:
            connector["note"] = "Real Google Ads API via local credentials"
            connector["data_mode"] = "real_google_ads_api"

    def _load_real_meta_accounts(self) -> None:
        if self._real_meta_loaded:
            return
        if not self._meta_connector:
            raise ValueError("Real Meta API mode requires META_ACCESS_TOKEN.")
        raw_accounts = self._meta_connector.fetch_ad_accounts()
        public_accounts, aliases = _public_accounts_with_aliases(raw_accounts, prefix="meta_account")
        self._accounts_by_connector["meta_ads"] = public_accounts
        self._account_id_aliases_by_connector["meta_ads"] = aliases
        self._real_meta_loaded = True

    def _load_real_google_ads_accounts(self) -> None:
        if self._real_google_ads_loaded:
            return
        if not self._google_connector:
            raise ValueError("Real Google Ads API mode requires Google Ads credentials.")
        raw_accounts = self._google_connector.fetch_customer_accounts()
        public_accounts, aliases = _public_accounts_with_aliases(raw_accounts, prefix="google_account")
        self._accounts_by_connector["google_ads"] = public_accounts
        self._account_id_aliases_by_connector["google_ads"] = aliases
        self._real_google_ads_loaded = True

    def _resolve_selection_account_ids(self, selection: dict[str, Any]) -> dict[str, Any]:
        connector_id = _selection_platform(selection)
        aliases = self._account_id_aliases_by_connector.get(connector_id, {})
        if not aliases:
            return selection
        accounts = selection.get("accounts")
        if not isinstance(accounts, list):
            return selection
        resolved_accounts: list[Any] = []
        for account in accounts:
            if not isinstance(account, dict):
                resolved_accounts.append(account)
                continue
            public_id = account.get("external_account_id") or account.get("id")
            if isinstance(public_id, str) and public_id in aliases:
                resolved_accounts.append({**account, "external_account_id": aliases[public_id]})
            else:
                resolved_accounts.append(account)
        return {**selection, "accounts": resolved_accounts}

    def _create_first_sync_job(self, draft_id: str, payload: dict[str, Any], account_count: int) -> dict[str, Any]:
        sync_job_id = self._state_store.next_sync_job_id()
        job = {
            "sync_job_id": sync_job_id,
            "draft_id": draft_id,
            "status": "queued",
            "progress_percent": 10,
            "checks": 0,
            "account_count": account_count,
            "platform": _selection_platform(payload),
            "destinations": _selection_destinations(payload),
            "message": "First sync is queued.",
            "selected_account_ids": _selection_account_ids(payload),
            "account_group_name": str(payload.get("client_name") or "Selected account"),
            "initial_sync": _selection_initial_sync(payload),
            "report_schedule": payload.get("report_schedule") if isinstance(payload.get("report_schedule"), dict) else {},
        }
        self._state_store.save_sync_job(sync_job_id, job)
        return _public_sync_job(job)

    def _advance_sync_job(self, job: dict[str, Any]) -> None:
        job["checks"] = int(job.get("checks", 0)) + 1
        if job["checks"] == 1:
            job["status"] = "running"
            job["progress_percent"] = 55
            job["message"] = "Syncing selected ad account data."
        elif job["checks"] >= 2:
            if not self._first_sync_runner:
                job["status"] = "ready_for_sync"
                job["progress_percent"] = 100
                job["message"] = "Setup is ready. Run live sync readiness before writing BigQuery."
                if self._backend_status_reader:
                    job["backend_data_check"] = self._read_backend_status(job)
                return
            if not self._maybe_run_first_sync(job):
                return
            if job.get("status") != "failed":
                job["status"] = "completed"
                job["progress_percent"] = 100
                job["message"] = "First sync completed. Destinations are ready."
                if self._backend_status_reader:
                    job["backend_data_check"] = self._read_backend_status(job)

    def _maybe_run_first_sync(self, job: dict[str, Any]) -> bool:
        if not self._first_sync_runner or "sync_execution" in job:
            return True
        with self._first_sync_lock:
            latest_job = self._state_store.get_sync_job(str(job["sync_job_id"]))
            if isinstance(latest_job, dict) and "sync_execution" in latest_job:
                job.update(latest_job)
                return job.get("status") != "failed"
            if "sync_execution" in job:
                return True
            try:
                draft = self._state_store.get_connection_draft(str(job["draft_id"]))
                selection = draft.get("raw_selection") if isinstance(draft, dict) else None
                if not isinstance(selection, dict):
                    raise ValueError("Missing raw selection for first sync.")
                job["message"] = "Running selected ad account sync."
                job["progress_percent"] = 75
                result = self._first_sync_runner(job, selection)
                job["sync_execution"] = {
                    "status": "success",
                    **result,
                }
                return True
            except Exception as exc:
                job["status"] = "failed"
                job["progress_percent"] = 100
                job["message"] = "First sync failed."
                job["sync_execution"] = {
                    "status": "failed",
                    "message": f"First sync failed: {exc.__class__.__name__}",
                    "writes_bigquery": True,
                }
                return False

    def _read_backend_status(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            if not self._backend_status_reader:
                return _backend_status_disabled()
            return self._backend_status_reader(job)
        except Exception as exc:
            return {
                "status": "unavailable",
                "source": "bigquery",
                "checked_at": _utc_now(),
                "message": f"Backend data check unavailable: {exc.__class__.__name__}",
                "latest_sync": None,
                "destinations": {},
                "warnings": ["backend_status_check_failed"],
            }


def create_handler(
    *,
    state: OnboardingPrototypeState | None = None,
    static_dir: Path = DEFAULT_STATIC_DIR,
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to prototype state and static files."""
    app_state = state or OnboardingPrototypeState()
    static_root = static_dir.resolve()

    class OnboardingRequestHandler(BaseHTTPRequestHandler):
        server_version = "OudSeedOnboardingPrototype/0.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            try:
                if path == "/healthz":
                    self._send_json({"ok": True})
                elif path == "/api/connectors":
                    self._send_json(app_state.list_connectors())
                elif path == "/api/destinations":
                    self._send_json(app_state.list_destinations())
                elif path == "/api/account-connections":
                    self._send_json(app_state.list_account_connections())
                elif path == "/api/onboarding/live-sync-readiness":
                    self._send_json(app_state.live_sync_readiness())
                elif path.startswith("/api/sync-jobs/"):
                    self._send_json(self._handle_get_sync_job(path))
                elif path.startswith("/api/account-connections/"):
                    self._send_json(self._handle_get_connection_draft(path))
                elif path.startswith("/api/connectors/") and path.endswith("/accounts"):
                    self._send_json(self._handle_list_accounts(path))
                else:
                    self._serve_static(path)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            try:
                if path == "/api/reset":
                    self._send_json(app_state.reset())
                elif path == "/api/account-connections":
                    self._send_json(app_state.create_connection(self._read_json_body()))
                elif path.startswith("/api/sync-jobs/") and path.endswith("/report-email"):
                    self._send_json(self._handle_send_report_email(path))
                elif path.startswith("/api/account-connections/") and path.endswith("/local-config-export"):
                    self._send_json(self._handle_local_config_export(path))
                elif path == "/api/config-preview":
                    self._send_json(app_state.config_preview(self._read_json_body()))
                elif path.startswith("/api/connectors/") and path.endswith("/oauth/start"):
                    connector_id = _connector_from_oauth_path(path, "start")
                    self._send_json(app_state.start_oauth(connector_id))
                elif path.startswith("/api/connectors/") and path.endswith("/oauth/complete"):
                    connector_id = _connector_from_oauth_path(path, "complete")
                    self._send_json(app_state.complete_oauth(connector_id))
                else:
                    self._send_json({"ok": False, "error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: Any) -> None:
            """Silence noisy request logs for local prototype use."""

        def _handle_list_accounts(self, path: str) -> dict[str, Any]:
            parts = [part for part in path.split("/") if part]
            if len(parts) != 6 or parts[:2] != ["api", "connectors"] or parts[3] != "authorizations":
                raise ValueError("Invalid accounts path.")
            return app_state.list_accounts(parts[2], authorization_id=parts[4])

        def _handle_get_connection_draft(self, path: str) -> dict[str, Any]:
            parts = [part for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "account-connections"]:
                return app_state.get_connection_draft(parts[2])
            if len(parts) == 4 and parts[:2] == ["api", "account-connections"] and parts[3] == "apply-plan":
                return app_state.get_apply_plan(parts[2])
            raise ValueError("Invalid account connection path.")

        def _handle_get_sync_job(self, path: str) -> dict[str, Any]:
            parts = [part for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "sync-jobs"]:
                return app_state.get_sync_job(parts[2])
            raise ValueError("Invalid sync job path.")

        def _handle_send_report_email(self, path: str) -> dict[str, Any]:
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "sync-jobs"] and parts[3] == "report-email":
                return app_state.send_report_email(parts[2])
            raise ValueError("Invalid report email path.")

        def _handle_local_config_export(self, path: str) -> dict[str, Any]:
            parts = [part for part in path.split("/") if part]
            if (
                len(parts) == 4
                and parts[:2] == ["api", "account-connections"]
                and parts[3] == "local-config-export"
            ):
                return app_state.export_local_config(parts[2])
            raise ValueError("Invalid local config export path.")

        def _serve_static(self, path: str) -> None:
            relative_path = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
            target = (static_root / relative_path).resolve()
            if not _is_relative_to(target, static_root) or not target.exists() or not target.is_file():
                self._send_json({"ok": False, "error": "Not found."}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object.")
            return parsed

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return OnboardingRequestHandler


def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    static_dir: Path = DEFAULT_STATIC_DIR,
    *,
    state: OnboardingPrototypeState | None = None,
) -> None:
    """Run the local onboarding prototype server."""
    server = ThreadingHTTPServer((host, port), create_handler(state=state, static_dir=static_dir))
    print(f"OudSeed onboarding prototype: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping OudSeed onboarding prototype.")
    finally:
        server.server_close()


def main() -> None:
    """CLI entrypoint for the local onboarding prototype server."""
    load_dotenv()
    args = _parse_args()
    state = _state_from_env()
    run_server(host=args.host, port=args.port, static_dir=Path(args.static_dir), state=state)


def _connector_from_oauth_path(path: str, action: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 5 or parts[:2] != ["api", "connectors"] or parts[3:] != ["oauth", action]:
        raise ValueError("Invalid OAuth path.")
    return parts[2]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _build_destination_handoff(selection: dict[str, Any]) -> dict[str, Any]:
    destinations = _selection_destinations(selection)
    report_schedule = selection.get("report_schedule") if isinstance(selection.get("report_schedule"), dict) else {}
    handoff: dict[str, Any] = {
        "writes_config": False,
        "writes_secrets": False,
        "local_draft_only": True,
        "destinations": {},
    }

    if "bigquery" in destinations or "looker_studio" in destinations:
        handoff["destinations"]["bigquery"] = {
            "status": "available",
            "project_id": "oudseed",
            "dataset": "ads_pipeline",
            "uses_existing_pipeline": True,
            "next_step": "Map the approved account selection into clients.yaml or Secret Manager-backed config.",
        }

    if "looker_studio" in destinations:
        handoff["destinations"]["looker_studio"] = {
            "status": "handoff_required",
            "handoff_type": "template_linking_url",
            "depends_on": ["bigquery"],
            "template_report_required": True,
            "next_step": (
                "Create or copy a Looker Studio template connected to the existing BigQuery views, "
                "then attach the template/linking URL to this account group."
            ),
        }

    if "ai_report_email" in destinations:
        handoff["destinations"]["ai_report_email"] = {
            "status": "config_preview_ready",
            "report_type": report_schedule.get("report_type", "monthly"),
            "delivery_day": report_schedule.get("delivery_day", 1),
            "timezone": report_schedule.get("timezone", "Asia/Taipei"),
            "depth": report_schedule.get("depth", "standard"),
            "next_step": "Review the sanitized report schedule and promote it into managed client config.",
        }

    if "google_sheets" in destinations:
        handoff["destinations"]["google_sheets"] = {
            "status": "not_productized",
            "next_step": "Keep disabled until Google Sheets export is implemented.",
        }

    return handoff


def _build_apply_plan(selection: dict[str, Any], draft_id: str) -> dict[str, Any]:
    destinations = _selection_destinations(selection)
    platform = _selection_platform(selection)
    platform_label = _platform_label(platform)
    steps = [
        {
            "id": "review_config_preview",
            "status": "ready",
            "label": "Review sanitized clients.yaml-compatible preview.",
        },
        {
            "id": "promote_account_config",
            "status": "manual_gate",
            "label": "Promote selected accounts into managed config after review.",
        },
        {
            "id": f"run_{platform}_sync_preflight",
            "status": "ready_after_config",
            "label": f"Run {platform_label} sync readiness against the selected account group.",
        },
    ]
    if "looker_studio" in destinations:
        steps.append(
            {
                "id": "prepare_looker_template",
                "status": "handoff_required",
                "label": "Attach a Looker Studio template or linking URL backed by BigQuery views.",
            }
        )
    if "ai_report_email" in destinations:
        steps.append(
            {
                "id": "run_ai_report_preflight",
                "status": "ready_after_config",
                "label": "Run AI report preflight before enabling recurring delivery.",
            }
        )

    return {
        "draft_id": draft_id,
        "safe_to_display": True,
        "local_draft_only": True,
        "sensitive_payload_persisted": False,
        "writes_config": False,
        "writes_secrets": False,
        "steps": steps,
        "recommended_checks": [
            "make ai-report-ready",
            "make ai-report-preflight",
        ],
    }


def _public_sync_job(job: dict[str, Any]) -> dict[str, Any]:
    destinations = job.get("destinations", [])
    sync_job = {
        "sync_job_id": job["sync_job_id"],
        "draft_id": job["draft_id"],
        "status": job["status"],
        "progress_percent": job["progress_percent"],
        "message": job["message"],
        "summary": {
            "account_count": job["account_count"],
            "destinations": destinations,
            "sync_days_back": job.get("initial_sync", {}).get("sync_days_back", 7),
            "writes_config": False,
            "local_prototype": True,
        },
        "steps": _sync_job_steps(str(job["status"]), destinations),
    }
    if "backend_data_check" in job:
        sync_job["backend_data_check"] = job["backend_data_check"]
    if "email_delivery" in job:
        sync_job["email_delivery"] = job["email_delivery"]
    if "sync_execution" in job:
        sync_job["sync_execution"] = job["sync_execution"]
    return sync_job


def _public_connection_summary(draft: dict[str, Any]) -> dict[str, Any]:
    config_summary = draft.get("config_preview", {}).get("summary", {})
    destinations = config_summary.get("destinations") if isinstance(config_summary, dict) else []
    destination_handoff = (
        draft.get("destination_handoff")
        if isinstance(draft.get("destination_handoff"), dict)
        else {}
    )
    handoff_destinations = destination_handoff.get("destinations", {})
    if not isinstance(handoff_destinations, dict):
        handoff_destinations = {}
    destination_statuses = {
        destination_id: detail.get("status", "unknown")
        for destination_id, detail in handoff_destinations.items()
        if isinstance(destination_id, str) and isinstance(detail, dict)
    }
    report_handoff = handoff_destinations.get("ai_report_email", {})
    report_schedule: dict[str, Any] | None = None
    if isinstance(report_handoff, dict) and report_handoff:
        report_schedule = {
            "report_type": report_handoff.get("report_type", "monthly"),
            "delivery_day": report_handoff.get("delivery_day", 1),
            "timezone": report_handoff.get("timezone", "Asia/Taipei"),
            "depth": report_handoff.get("depth", "standard"),
        }

    return {
        "draft_id": draft["draft_id"],
        "status": draft.get("status", "draft"),
        "created_at": draft.get("created_at"),
        "first_sync_job_id": draft.get("first_sync_job_id"),
        "connector_id": str(draft.get("connector_id") or "unknown"),
        "account_group_name": str(draft.get("account_group_name") or "Selected account"),
        "initial_sync": draft.get("initial_sync") if isinstance(draft.get("initial_sync"), dict) else {"sync_days_back": 7},
        "connection_count": len(draft.get("connection_ids", [])),
        "account_count": config_summary.get("account_count", 0),
        "destinations": destinations if isinstance(destinations, list) else [],
        "destination_statuses": destination_statuses,
        "report_schedule": report_schedule,
        "local_draft_only": bool(draft.get("local_draft_only", True)),
        "writes_config": bool(draft.get("writes_config", False)),
        "writes_secrets": bool(draft.get("writes_secrets", False)),
        **({"local_config_export": draft["local_config_export"]} if "local_config_export" in draft else {}),
    }


def _public_connection_group_summaries(connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for connection in connections:
        group_name = str(connection.get("account_group_name") or "Selected account")
        group = groups.setdefault(
            group_name,
            {
                "account_group_name": group_name,
                "connection_count": 0,
                "account_count": 0,
                "platforms": [],
                "destinations": [],
                "first_sync_job_ids": [],
                "initial_sync": {"sync_days_back": 7},
                "destination_statuses": {},
                "report_schedule": None,
                "local_draft_only": True,
                "writes_config": False,
                "writes_secrets": False,
            },
        )
        group["connection_count"] += int(connection.get("connection_count") or 0)
        group["account_count"] += int(connection.get("account_count") or 0)
        _append_unique(group["platforms"], str(connection.get("connector_id") or "unknown"))
        for destination in connection.get("destinations", []) or []:
            if isinstance(destination, str):
                _append_unique(group["destinations"], destination)
        sync_days_back = _safe_int(
            connection.get("initial_sync", {}).get("sync_days_back")
            if isinstance(connection.get("initial_sync"), dict)
            else None,
            default=7,
        )
        group["initial_sync"]["sync_days_back"] = max(group["initial_sync"]["sync_days_back"], sync_days_back)
        first_sync_job_id = connection.get("first_sync_job_id")
        if isinstance(first_sync_job_id, str) and first_sync_job_id:
            group["first_sync_job_ids"].append(first_sync_job_id)
        if connection.get("report_schedule") and not group.get("report_schedule"):
            group["report_schedule"] = connection["report_schedule"]
        group["local_draft_only"] = group["local_draft_only"] and bool(connection.get("local_draft_only", True))
        group["writes_config"] = group["writes_config"] or bool(connection.get("writes_config", False))
        group["writes_secrets"] = group["writes_secrets"] or bool(connection.get("writes_secrets", False))
        _merge_destination_statuses(group["destination_statuses"], connection.get("destination_statuses", {}))
        if connection.get("local_config_export"):
            group["local_config_export"] = connection["local_config_export"]
    return list(groups.values())


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _merge_destination_statuses(target: dict[str, str], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for destination_id, status in source.items():
        if isinstance(destination_id, str) and isinstance(status, str):
            target[destination_id] = status


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _backend_status_disabled() -> dict[str, Any]:
    return {
        "status": "disabled",
        "source": "local_prototype",
        "checked_at": _utc_now(),
        "message": "Backend data check is disabled for this prototype run.",
        "latest_sync": None,
        "destinations": {},
        "warnings": [],
    }


def _build_bigquery_status_reader(project_id: str, dataset_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)

    def read_status(sync_job: dict[str, Any]) -> dict[str, Any]:
        platform = str(sync_job.get("platform") or "meta_ads")
        if platform not in {"meta_ads", "google_ads"}:
            platform = "meta_ads"
        platform_label = _platform_label(platform)
        raw_table = "raw_google_ads_daily" if platform == "google_ads" else "raw_meta_ads_daily"
        selected_account_ids = [
            str(account_id)
            for account_id in sync_job.get("selected_account_ids", [])
            if isinstance(account_id, str) and account_id.strip()
        ]
        sync_account_clause = ""
        row_count_account_clause = ""
        base_parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = [
            bigquery.ScalarQueryParameter("platform", "STRING", platform),
        ]
        if selected_account_ids:
            sync_account_clause = "AND account_id IN UNNEST(@account_ids)"
            row_count_account_clause = "AND account_id IN UNNEST(@account_ids)"
            base_parameters.append(bigquery.ArrayQueryParameter("account_ids", "STRING", selected_account_ids))

        latest_sync_rows = destination.query_rows(
            f"""
            SELECT
              status,
              rows_fetched,
              rows_inserted,
              CAST(sync_start_date AS STRING) AS sync_start_date,
              CAST(sync_end_date AS STRING) AS sync_end_date
            FROM `{destination._table_id("sync_logs")}`
            WHERE platform = @platform
              {sync_account_clause}
            ORDER BY finished_at DESC
            LIMIT 1
            """,
            query_parameters=base_parameters,
        )
        if not latest_sync_rows:
            return {
                "status": "no_data",
                "source": "bigquery",
                "checked_at": _utc_now(),
                "message": f"No {platform_label} sync logs found yet for the selected accounts.",
                "latest_sync": None,
                "destinations": {},
                "warnings": [f"no_selected_account_{platform}_sync_logs"],
            }

        latest_sync = latest_sync_rows[0]
        start_date = str(latest_sync["sync_start_date"])
        end_date = str(latest_sync["sync_end_date"])
        parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = [
            *base_parameters,
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
        raw_count = _single_count(
            destination,
            f"""
            SELECT COUNT(*) AS row_count
            FROM `{destination._table_id(raw_table)}`
            WHERE platform = @platform
              AND date BETWEEN @start_date AND @end_date
              {row_count_account_clause}
            """,
            parameters,
        )
        unified_count = _single_count(
            destination,
            f"""
            SELECT COUNT(*) AS row_count
            FROM `{destination._table_id("unified_ads_daily")}`
            WHERE platform = @platform
              AND date BETWEEN @start_date AND @end_date
              {row_count_account_clause}
            """,
            parameters,
        )
        ad_daily_count = _single_count(
            destination,
            f"""
            SELECT COUNT(*) AS row_count
            FROM `{destination._table_id("vw_looker_ads_ad_daily")}`
            WHERE platform = @platform
              AND date BETWEEN @start_date AND @end_date
              {row_count_account_clause}
            """,
            parameters,
        )
        campaign_daily_count = _single_count(
            destination,
            f"""
            SELECT COUNT(*) AS row_count
            FROM `{destination._table_id("vw_looker_ads_campaign_daily")}`
            WHERE platform = @platform
              AND date BETWEEN @start_date AND @end_date
              {row_count_account_clause}
            """,
            parameters,
        )
        healthy = (
            latest_sync["status"] == "success"
            and int(latest_sync["rows_fetched"] or 0) >= 0
            and raw_count >= 0
            and unified_count >= 0
            and ad_daily_count >= 0
            and campaign_daily_count >= 0
        )
        return {
            "status": "healthy" if healthy else "needs_attention",
            "source": "bigquery",
            "checked_at": _utc_now(),
            "message": f"Latest {platform_label} sync data is visible in BigQuery and Looker-facing views.",
            "scope": {
                "platform": platform,
                "selected_account_count": len(selected_account_ids),
                "selected_accounts_scoped": bool(selected_account_ids),
            },
            "latest_sync": {
                "status": latest_sync["status"],
                "rows_fetched": latest_sync["rows_fetched"],
                "rows_inserted": latest_sync["rows_inserted"],
                "sync_start_date": start_date,
                "sync_end_date": end_date,
            },
            "destinations": {
                "bigquery": {
                    "status": "verified" if raw_count >= 0 and unified_count >= 0 else "needs_attention",
                    "raw_rows": raw_count,
                    "unified_rows": unified_count,
                },
                "looker_studio": {
                    "status": "verified" if ad_daily_count >= 0 and campaign_daily_count >= 0 else "needs_attention",
                    "ad_daily_rows": ad_daily_count,
                    "campaign_daily_rows": campaign_daily_count,
                },
            },
            "warnings": [] if healthy else [f"latest_{platform}_sync_not_healthy"],
        }

    return read_status


def _single_count(
    destination: BigQueryDestination,
    sql: str,
    parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter],
) -> int:
    rows = destination.query_rows(sql, query_parameters=parameters)
    if not rows:
        return 0
    return int(rows[0]["row_count"])


def _sync_job_steps(status: str, destinations: list[str]) -> list[dict[str, str]]:
    if status == "failed":
        warehouse_status = "failed"
        output_status = "queued"
    elif status == "ready_for_sync":
        warehouse_status = "queued"
        output_status = "queued"
    else:
        warehouse_status = "completed" if status == "completed" else "running" if status == "running" else "queued"
        output_status = "completed" if status == "completed" else "queued"
    steps = [
        {
            "id": "source_connected",
            "label": "Source connected",
            "status": "completed",
        },
        {
            "id": "warehouse_sync",
            "label": "Data warehouse sync",
            "status": warehouse_status,
        },
    ]
    if "looker_studio" in destinations:
        steps.append(
            {
                "id": "dashboard_refresh",
                "label": "Dashboard data refresh",
                "status": output_status,
            }
        )
    if "ai_report_email" in destinations:
        steps.append(
            {
                "id": "report_schedule",
                "label": "Report schedule setup",
                "status": output_status,
            }
        )
    return steps


def _selection_destinations(selection: dict[str, Any]) -> list[str]:
    destinations = selection.get("destinations")
    if not isinstance(destinations, list):
        return []
    return [destination for destination in destinations if isinstance(destination, str)]


def _selection_platform(selection: dict[str, Any]) -> str:
    connector_id = selection.get("connector_id")
    if connector_id in {"meta_ads", "google_ads"}:
        return str(connector_id)
    return "meta_ads"


def _selection_account_ids(selection: dict[str, Any]) -> list[str]:
    accounts = selection.get("accounts")
    if not isinstance(accounts, list):
        return []
    platform = _selection_platform(selection)
    account_ids: list[str] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = account.get("external_account_id") or account.get("id")
        if isinstance(account_id, str) and account_id.strip():
            value = account_id.strip()
            if platform == "google_ads":
                value = value.replace("-", "")
            account_ids.append(value)
    return account_ids


def _selection_initial_sync(selection: dict[str, Any]) -> dict[str, int]:
    initial_sync = selection.get("initial_sync")
    raw_value: Any = None
    if isinstance(initial_sync, dict):
        raw_value = initial_sync.get("sync_days_back")
    if raw_value is None:
        raw_value = selection.get("sync_days_back")
    try:
        days_back = int(raw_value) if raw_value is not None else 7
    except (TypeError, ValueError):
        days_back = 7
    days_back = min(max(days_back, 0), 365)
    return {"sync_days_back": days_back}


def _public_accounts_with_aliases(
    accounts: list[dict[str, Any]],
    *,
    prefix: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    public_accounts: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    for index, account in enumerate(accounts, start=1):
        if not isinstance(account, dict):
            continue
        raw_id = account.get("id")
        public_id = f"{prefix}_{index:04d}"
        public_accounts.append({**account, "id": public_id})
        if isinstance(raw_id, str) and raw_id.strip():
            aliases[public_id] = raw_id.strip()
    return public_accounts, aliases


def _platform_label(platform: str) -> str:
    return {"meta_ads": "Meta", "google_ads": "Google Ads"}.get(platform, platform)


def _default_connectors() -> list[dict[str, Any]]:
    return [
        {
            "id": "meta_ads",
            "name": "Meta Ads",
            "label": "Facebook Ads",
            "logo": "f",
            "color": "blue",
            "status": "available",
            "connected": False,
            "note": "Live sync ready",
        },
        {
            "id": "google_ads",
            "name": "Google Ads",
            "label": "Google Ads",
            "logo": "G",
            "color": "google",
            "status": "available",
            "connected": False,
            "note": "Ready for gated sync",
        },
        {
            "id": "ga4",
            "name": "Google Analytics 4",
            "label": "Google Analytics 4",
            "logo": "A",
            "color": "amber",
            "status": "coming_soon",
            "connected": False,
            "note": "Later destination context",
        },
        {
            "id": "line_ads",
            "name": "LINE Ads",
            "label": "LINE Ads",
            "logo": "L",
            "color": "green",
            "status": "coming_soon",
            "connected": False,
            "note": "Not enabled yet",
        },
        {
            "id": "instagram_insights",
            "name": "Instagram Insights",
            "label": "Instagram Insights",
            "logo": "IG",
            "color": "pink",
            "status": "coming_soon",
            "connected": False,
            "note": "Via Meta later",
        },
    ]


def _default_accounts_by_connector() -> dict[str, list[dict[str, Any]]]:
    return {
        "meta_ads": [
            {
                "id": "act_demo_1001",
                "name": "Demo Shop Taiwan",
                "currency": "TWD",
                "timezone": "Asia/Taipei",
                "status": "Ready",
            },
            {
                "id": "act_demo_1002",
                "name": "Demo Shop USA",
                "currency": "USD",
                "timezone": "America/Los_Angeles",
                "status": "Ready",
            },
            {
                "id": "act_demo_1003",
                "name": "Pet Brand Sample",
                "currency": "TWD",
                "timezone": "Asia/Taipei",
                "status": "Ready",
            },
            {
                "id": "act_demo_1004",
                "name": "Lifestyle Sample EU",
                "currency": "EUR",
                "timezone": "Europe/Berlin",
                "status": "Ready",
            },
            {
                "id": "act_demo_1005",
                "name": "Agency Sandbox",
                "currency": "TWD",
                "timezone": "Asia/Taipei",
                "status": "Ready",
            },
        ],
        "google_ads": [
            {
                "id": "1234567890",
                "name": "Demo Search Account",
                "currency": "TWD",
                "timezone": "Asia/Taipei",
                "status": "Preview",
            },
            {
                "id": "2345678901",
                "name": "Demo Shopping Account",
                "currency": "TWD",
                "timezone": "Asia/Taipei",
                "status": "Preview",
            },
        ],
    }


def _default_destinations() -> list[dict[str, Any]]:
    return [
        {
            "id": "looker_studio",
            "name": "Looker Studio",
            "subtitle": "Dashboard reporting",
            "category": "dashboard",
            "status": "available",
            "icon": "LS",
        },
        {
            "id": "ai_report_email",
            "name": "AI Report Email",
            "subtitle": "Weekly or monthly insights",
            "category": "ai",
            "status": "available",
            "icon": "AI",
        },
        {
            "id": "bigquery",
            "name": "BigQuery",
            "subtitle": "Warehouse tables",
            "category": "warehouse",
            "status": "available",
            "icon": "BQ",
        },
        {
            "id": "google_sheets",
            "name": "Google Sheets",
            "subtitle": "Coming soon",
            "category": "spreadsheet",
            "status": "coming_soon",
            "icon": "GS",
        },
        {
            "id": "power_bi",
            "name": "Power BI",
            "subtitle": "Later",
            "category": "dashboard",
            "status": "coming_soon",
            "icon": "BI",
        },
        {
            "id": "cloud_storage",
            "name": "Cloud Storage",
            "subtitle": "Later",
            "category": "warehouse",
            "status": "coming_soon",
            "icon": "CS",
        },
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local OudSeed onboarding prototype server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR))
    return parser.parse_args()


def _state_from_env() -> OnboardingPrototypeState:
    use_real_meta = _truthy(os.getenv("ONBOARDING_USE_REAL_META"))
    use_real_google_ads = _truthy(os.getenv("ONBOARDING_USE_REAL_GOOGLE_ADS"))
    backend_status_reader = _backend_status_reader_from_env()
    email_report_sender = _email_report_sender_from_env()
    local_config_exporter = _local_config_exporter_from_env()
    first_sync_runner = _first_sync_runner_from_env()
    state_store = _state_store_from_env()
    google_connector = _google_connector_from_env() if use_real_google_ads else None
    if not use_real_meta:
        return OnboardingPrototypeState(
            google_connector=google_connector,
            use_real_google_ads=use_real_google_ads,
            backend_status_reader=backend_status_reader,
            email_report_sender=email_report_sender,
            local_config_exporter=local_config_exporter,
            first_sync_runner=first_sync_runner,
            state_store=state_store,
        )

    access_token = os.getenv("META_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise ValueError("ONBOARDING_USE_REAL_META=true requires META_ACCESS_TOKEN.")
    timeout_seconds = _positive_int_env("META_API_TIMEOUT_SECONDS", 60)
    api_version = os.getenv("META_API_VERSION", "v24.0")
    connector = MetaAdsConnector(
        access_token=access_token,
        api_version=api_version,
        timeout_seconds=timeout_seconds,
    )
    return OnboardingPrototypeState(
        google_connector=google_connector,
        meta_connector=connector,
        use_real_google_ads=use_real_google_ads,
        use_real_meta=True,
        backend_status_reader=backend_status_reader,
        email_report_sender=email_report_sender,
        local_config_exporter=local_config_exporter,
        first_sync_runner=first_sync_runner,
        state_store=state_store,
    )


def _google_connector_from_env() -> GoogleAdsConnector:
    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_ADS_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
    missing = [
        name
        for name, value in [
            ("GOOGLE_ADS_DEVELOPER_TOKEN", developer_token),
            ("GOOGLE_ADS_CLIENT_ID", client_id),
            ("GOOGLE_ADS_CLIENT_SECRET", client_secret),
            ("GOOGLE_ADS_REFRESH_TOKEN", refresh_token),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"ONBOARDING_USE_REAL_GOOGLE_ADS=true requires {', '.join(missing)}.")
    return GoogleAdsConnector(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        login_customer_id=os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip() or None,
    )


def _state_store_from_env() -> OnboardingStateStore:
    state_store_path = os.getenv("ONBOARDING_STATE_STORE_PATH", "").strip()
    if not state_store_path:
        return InMemoryOnboardingStateStore()
    return JsonFileOnboardingStateStore(Path(state_store_path))


def _local_config_exporter_from_env() -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    export_path = os.getenv("ONBOARDING_LOCAL_CONFIG_EXPORT_PATH", "").strip()
    if not export_path:
        return None

    def export(selection: dict[str, Any]) -> dict[str, Any]:
        raw_selections = selection.get("selections")
        if isinstance(raw_selections, list):
            selections = [item for item in raw_selections if isinstance(item, dict)]
            return format_local_export_summary(
                export_local_clients_config_from_selections(selections, Path(export_path))
            )
        return format_local_export_summary(export_local_clients_config(selection, Path(export_path)))

    return export


def _build_platform_live_sync_readiness() -> dict[str, Any]:
    platform_readiness: dict[str, Any] = {}
    for platform in ("meta_ads", "google_ads"):
        platform_env = dict(os.environ)
        platform_env["ONBOARDING_LIVE_SYNC_PLATFORM"] = platform
        platform_readiness[platform] = build_live_sync_readiness_from_env(platform_env)
    return platform_readiness


def _first_sync_runner_from_env() -> OnboardingFirstSyncRunner | None:
    if not _truthy(os.getenv("ONBOARDING_ENABLE_LOCAL_SYNC_RUN")):
        return None
    config_path = os.getenv("ONBOARDING_LOCAL_CONFIG_EXPORT_PATH", "").strip()
    if not config_path:
        raise ValueError("ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true requires ONBOARDING_LOCAL_CONFIG_EXPORT_PATH.")
    platform = os.getenv("ONBOARDING_LIVE_SYNC_PLATFORM", "").strip() or "meta_ads"
    return LocalPlatformSyncRunner(
        platform=platform,
        config_path=Path(config_path),
        repo_root=REPO_ROOT,
        python_bin=os.getenv("ONBOARDING_LOCAL_SYNC_PYTHON", sys.executable),
        timeout_seconds=_positive_int_env("ONBOARDING_LOCAL_SYNC_TIMEOUT_SECONDS", 900),
    )


def _backend_status_reader_from_env() -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if not _truthy(os.getenv("ONBOARDING_USE_BIGQUERY_STATUS")):
        return None
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    dataset_id = os.getenv("BIGQUERY_DATASET", "").strip()
    if not project_id or not dataset_id:
        return lambda sync_job: {
            "status": "unavailable",
            "source": "bigquery",
            "checked_at": _utc_now(),
            "message": "GCP_PROJECT_ID and BIGQUERY_DATASET are required for backend data checks.",
            "latest_sync": None,
            "destinations": {},
            "warnings": ["bigquery_status_env_missing"],
        }
    return _build_bigquery_status_reader(project_id=project_id, dataset_id=dataset_id)


def _email_report_sender_from_env() -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if not _truthy(os.getenv("ONBOARDING_ENABLE_EMAIL_SEND")):
        return None

    def send_email(sync_job: dict[str, Any]) -> dict[str, Any]:
        # Import lazily so prototype UI can run without OpenAI/SMTP setup unless email send is used.
        from src.ai.generate_report import (
            _first_enabled_client_id,
            _load_runtime_config,
            _report_type,
        )
        from src.ai.openai_client import OpenAITextClient
        from src.ai.report_generator import generate_and_log_report
        from src.ai.send_account_reports import (
            _default_subject,
            _destination_from_config,
            _format_text_email,
            _send_account_report_email,
            format_html_email,
        )
        from src.notifications.email_delivery import (
            SMTPEmailSender,
            load_smtp_email_config_from_env,
        )

        config = _load_runtime_config()
        destination = _destination_from_config(config)
        selected_account_ids = sync_job.get("selected_account_ids")
        if not isinstance(selected_account_ids, list) or not selected_account_ids:
            raise ValueError("No selected account ids available for report email.")

        report_schedule = sync_job.get("report_schedule") if isinstance(sync_job.get("report_schedule"), dict) else {}
        report_type = _report_type(str(report_schedule.get("report_type") or os.getenv("AI_REPORT_TYPE") or "monthly"))
        period_start_date = (
            os.getenv("AI_REPORT_PERIOD_START_DATE")
            or _report_period_start_from_sync(sync_job, report_type)
        )
        client_id = os.getenv("AI_REPORT_CLIENT_ID") or _first_enabled_client_id(config)
        limit = _positive_int_env("AI_REPORT_LIMIT", 10)
        max_output_tokens = _positive_int_env("OPENAI_MAX_OUTPUT_TOKENS", 5000)
        report_depth = str(report_schedule.get("depth") or os.getenv("AI_REPORT_DEPTH") or "standard")
        recipient = os.getenv("AI_REPORT_EMAIL_TO") or _report_schedule_email_to(config)
        if not recipient:
            raise ValueError("AI_REPORT_EMAIL_TO or report schedule email_to is required.")

        openai_client = OpenAITextClient(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
            reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
            timeout_seconds=_positive_int_env("OPENAI_TIMEOUT_SECONDS", 120),
        )
        sender = SMTPEmailSender(load_smtp_email_config_from_env())
        result = generate_and_log_report(
            destination=destination,
            openai_client=openai_client,
            report_type=report_type,
            workspace_id=config["workspace_id"],
            client_id=client_id,
            period_start_date=period_start_date,
            account_ids=[str(account_id) for account_id in selected_account_ids],
            limit=limit,
            max_output_tokens=max_output_tokens,
            report_depth=report_depth,
        )
        account_group_name = str(sync_job.get("account_group_name") or "Selected account")
        subject = _default_subject(
            report_type=report_type,
            account_group_name=account_group_name,
            period_start_date=period_start_date,
        )
        body = _format_text_email(
            report_id=result["report_id"],
            client_id=client_id,
            context=result["context"],
            report_text=result["report_text"],
        )
        html_body = format_html_email(
            report_id=result["report_id"],
            client_id=client_id,
            context=result["context"],
            report_text=result["report_text"],
            account_group_name=account_group_name,
        )
        _send_account_report_email(
            sender=sender,
            destination=destination,
            report_id=result["report_id"],
            workspace_id=config["workspace_id"],
            client_id=client_id,
            report_type=report_type,
            context=result["context"],
            report_text=result["report_text"],
            model_name=openai_client.model,
            recipient=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
        )
        return {
            "status": "sent",
            "message": "Report email sent.",
            "report_id": result["report_id"],
            "report_type": report_type,
            "period_start_date": period_start_date,
            "recipient_configured": True,
        }

    return send_email


def _report_period_start_from_sync(sync_job: dict[str, Any], report_type: str) -> str:
    backend_check = sync_job.get("backend_data_check") if isinstance(sync_job.get("backend_data_check"), dict) else {}
    latest_sync = backend_check.get("latest_sync") if isinstance(backend_check.get("latest_sync"), dict) else {}
    sync_start_date = str(latest_sync.get("sync_start_date") or "")
    if len(sync_start_date) >= 10:
        date_value = datetime.fromisoformat(sync_start_date[:10])
        if report_type == "monthly":
            return date_value.replace(day=1).date().isoformat()
        weekday = date_value.weekday()
        return (date_value.date()).fromordinal(date_value.date().toordinal() - weekday).isoformat()
    return os.getenv("AI_REPORT_PERIOD_START_DATE") or datetime.now(UTC).date().replace(day=1).isoformat()


def _report_schedule_email_to(config: dict[str, Any]) -> str | None:
    for client in config.get("clients", []):
        if not isinstance(client, dict):
            continue
        for schedule in client.get("report_schedules", []) or []:
            if isinstance(schedule, dict) and schedule.get("enabled", True) is not False and schedule.get("email_to"):
                return str(schedule["email_to"])
    return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    main()
