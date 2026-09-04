"""Daily auto-sync of every workspace's selected ad accounts into BigQuery.

The automatic counterpart of the dashboard's "Run first sync" button: run this
once a day (Cloud Scheduler → Cloud Run Job) and it refreshes each workspace's
**active** connections (the accounts the user selected) for a recent window,
then refreshes the reporting marts/views once so Data Studio + the AI report see
the new data.

Run locally:  ``python -m src.sync.daily_sync``

It reuses :func:`src.web.first_sync.run_first_sync` (same raw + unified writes,
same chunking/retry), so the daily refresh is identical to the on-demand button.
Each workspace is isolated: one failing does not abort the others. Logs are
secret-free and never include workspace/account identifiers.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from src.connectors.google_ads import GoogleAdsConnector
from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination
from src.main import _redacted_identifier, refresh_reporting_marts
from src.storage.db import build_session_factory, create_db_engine, session_scope
from src.storage.repository import (
    bind_connections_to_client,
    get_or_create_default_client,
    list_all_workspaces,
    list_connections,
)
from src.utils.date_utils import get_default_sync_range
from src.web.config import WebSettings, load_web_settings
from src.web.first_sync import FirstSyncResult, run_first_sync

# Re-pull the last few days each run (not just yesterday) so late-attributed
# conversions and platform restatements get corrected — replace_date_range
# overwrites the whole window, so re-pulling is safe and self-healing.
DEFAULT_LOOKBACK_DAYS = 3

# Account errors are echoed to the log so a partial failure is visible; cap the
# provider message so a long API payload can't flood Cloud Logging.
MAX_LOGGED_ERROR_CHARS = 200

ConnectorFactory = Callable[[str], object]


@dataclass(frozen=True)
class AccountFailure:
    """One account that failed to sync, for logging and the run summary."""

    platform: str
    account_id: str
    error: str


@dataclass(frozen=True)
class WorkspaceSyncResult:
    """Outcome of syncing one workspace's active accounts."""

    workspace_id: str
    attempted: int
    succeeded: int
    failed: int
    status: str  # "synced" | "skipped" (no active accounts) | "error"
    detail: str = ""
    failures: tuple[AccountFailure, ...] = field(default_factory=tuple)


def make_meta_factory() -> ConnectorFactory:
    """Build a Meta connector factory (token -> connector)."""
    return lambda token: MetaAdsConnector(access_token=token)


def make_google_factory(settings: WebSettings) -> ConnectorFactory:
    """Build a Google Ads connector factory from app settings (token = refresh token)."""

    def factory(token: str) -> GoogleAdsConnector:
        return GoogleAdsConnector(
            developer_token=settings.google_ads_developer_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            refresh_token=token,
            login_customer_id=settings.google_ads_login_customer_id or None,
        )

    return factory


def sync_all_workspaces(
    session: Session,
    *,
    destination: BigQueryDestination,
    meta_connector_factory: ConnectorFactory,
    google_connector_factory: ConnectorFactory,
    start_date: str,
    end_date: str,
    encryption_key: str | None = None,
    run_sync: Callable[..., FirstSyncResult] = run_first_sync,
) -> list[WorkspaceSyncResult]:
    """Sync every workspace's active connections, isolating per-workspace failures."""
    results: list[WorkspaceSyncResult] = []
    for workspace in list_all_workspaces(session):
        try:
            active = [
                c for c in list_connections(session, workspace.id) if c.status == "active"
            ]
            if not active:
                results.append(
                    WorkspaceSyncResult(workspace.id, 0, 0, 0, "skipped")
                )
                continue

            client = get_or_create_default_client(session, workspace)
            bind_connections_to_client(session, client=client, connections=active)
            outcome = run_sync(
                connections=active,
                destination=destination,
                workspace_id=workspace.id,
                client_id=client.client_key,
                start_date=start_date,
                end_date=end_date,
                meta_connector_factory=meta_connector_factory,
                google_connector_factory=google_connector_factory,
                token_key=encryption_key,
            )
            failures = tuple(
                AccountFailure(r.platform, r.account_id, (r.error or "")[:MAX_LOGGED_ERROR_CHARS])
                for r in outcome.failed
            )
            # A failing account is the signal this job exists to surface — an
            # expired token here once went unnoticed for weeks because the run
            # still reported success. Log every failure individually.
            for failure in failures:
                print(
                    f"event=daily_sync_account_failed platform={failure.platform} "
                    f"account_id={_redacted_identifier(failure.account_id)} "
                    f"error={failure.error}",
                    flush=True,
                )
            results.append(
                WorkspaceSyncResult(
                    workspace.id,
                    outcome.attempted,
                    len(outcome.succeeded),
                    len(outcome.failed),
                    "synced",
                    failures=failures,
                )
            )
        except Exception as exc:
            # One workspace failing must not stop the rest.
            results.append(
                WorkspaceSyncResult(workspace.id, 0, 0, 0, "error", type(exc).__name__)
            )
    return results


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def main() -> None:
    """Sync all workspaces' active accounts, then refresh reporting marts once."""
    load_dotenv()
    project_id = _required_env("GCP_PROJECT_ID")
    dataset_id = _required_env("BIGQUERY_DATASET")
    lookback_days = _int_env("DAILY_SYNC_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS)

    settings = load_web_settings()
    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    start_date, end_date = get_default_sync_range(
        days_back=lookback_days, timezone="Asia/Taipei"
    )

    engine = create_db_engine()
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        results = sync_all_workspaces(
            session,
            destination=destination,
            meta_connector_factory=make_meta_factory(),
            google_connector_factory=make_google_factory(settings),
            start_date=start_date,
            end_date=end_date,
            encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
        )

    any_succeeded = any(r.succeeded for r in results)
    # Refresh the reporting marts/views once after data lands — best-effort so a
    # refresh failure doesn't mask an otherwise successful sync.
    refresh_status = "skipped"
    if any_succeeded:
        try:
            refresh_reporting_marts(destination=destination)
            refresh_status = "ok"
        except Exception as exc:  # noqa: BLE001 - log type only, never secrets
            refresh_status = f"failed:{type(exc).__name__}"

    synced = sum(1 for r in results if r.status == "synced")
    skipped = sum(1 for r in results if r.status == "skipped")
    errored = sum(1 for r in results if r.status == "error")
    accounts = sum(r.succeeded for r in results)
    accounts_failed = sum(r.failed for r in results)
    print(
        "daily_sync_done=true "
        f"workspaces={len(results)} synced={synced} skipped={skipped} "
        f"errored={errored} accounts_synced={accounts} "
        f"accounts_failed={accounts_failed} "
        f"window={start_date}..{end_date} marts_refresh={refresh_status}"
    )

    # Exit non-zero so Cloud Run marks the execution failed and the problem is
    # visible. Without this a run where every ad account failed still looked
    # green, which is how an expired Meta token stayed unnoticed for weeks.
    if accounts_failed or errored:
        sys.exit(1)


if __name__ == "__main__":
    main()
