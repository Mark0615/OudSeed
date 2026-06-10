"""One-time historical backfill of every workspace's selected ad accounts.

The "Run first sync" button only pulls a recent window (fast feedback). This
job pulls **as much history as each platform allows**, so an existing Data
Studio report shows the account's full history — the way Windsor.ai backfills.

Platform ceilings (these are the platforms' own limits, not ours):
  * Meta Ads Insights API keeps ~37 months of data; older data is simply not
    retrievable via the API. Default backfill is 36 months to stay safely inside.
  * Google Ads retains longer; default backfill is also ~36 months (raise via env
    if you want more).

How it stays safe on a long run:
  * Backfills **one ~30-day window at a time**, writing each window to BigQuery as
    it completes — so a failure late in the range doesn't lose the months already
    pulled.
  * ``replace_date_range`` overwrites per (date, account), so re-running is
    idempotent and never duplicates.
  * Each window is isolated: one failing window is logged and skipped, the rest
    continue. Each workspace is isolated from the others.

Run locally:  ``python -m src.sync.backfill``

Logs are secret-free and never include workspace/account identifiers.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from src.destinations.bigquery import BigQueryDestination
from src.main import refresh_reporting_marts
from src.storage.db import build_session_factory, create_db_engine, session_scope
from src.storage.repository import (
    bind_connections_to_client,
    get_or_create_default_client,
    list_all_workspaces,
    list_connections,
)
from src.sync.daily_sync import make_google_factory, make_meta_factory
from src.utils.date_utils import today_in_timezone
from src.web.config import load_web_settings
from src.web.first_sync import FirstSyncResult, _date_chunks, run_first_sync

# Per-platform default backfill depth (days). Meta is capped at ~37 months by the
# API; 36 months keeps the earliest day safely inside that window.
DEFAULT_BACKFILL_DAYS: dict[str, int] = {
    "meta_ads": 1095,   # ~36 months (Meta API ceiling is ~37 months)
    "google_ads": 1095,  # ~36 months (Google retains longer; raise via env)
}
# Write to BigQuery this many days at a time so progress persists mid-run.
DEFAULT_WINDOW_DAYS = 30

ConnectorFactory = Callable[[str], object]


@dataclass(frozen=True)
class WorkspaceBackfillResult:
    """Outcome of backfilling one workspace's active accounts."""

    workspace_id: str
    accounts: int
    windows_ok: int
    windows_failed: int
    rows: int
    status: str  # "backfilled" | "skipped" (no active accounts) | "error"
    detail: str = ""


def _start_for(end_date: str, days: int) -> str:
    """Return the inclusive start date `days` before `end_date`."""
    return (date.fromisoformat(end_date) - timedelta(days=days)).isoformat()


def _group_by_platform(connections: list) -> dict[str, list]:
    """Group connections by platform (preserving order)."""
    grouped: dict[str, list] = {}
    for connection in connections:
        grouped.setdefault(connection.platform, []).append(connection)
    return grouped


def backfill_all(
    session: Session,
    *,
    destination: BigQueryDestination,
    meta_connector_factory: ConnectorFactory,
    google_connector_factory: ConnectorFactory,
    end_date: str,
    platform_starts: dict[str, str],
    window_days: int = DEFAULT_WINDOW_DAYS,
    encryption_key: str | None = None,
    run_sync: Callable[..., FirstSyncResult] = run_first_sync,
) -> list[WorkspaceBackfillResult]:
    """Backfill every workspace's active accounts window-by-window.

    ``platform_starts`` maps a platform to its inclusive backfill start date; a
    platform missing from the map is backfilled only for ``end_date`` itself.
    """
    results: list[WorkspaceBackfillResult] = []
    for workspace in list_all_workspaces(session):
        try:
            active = [
                c for c in list_connections(session, workspace.id) if c.status == "active"
            ]
            if not active:
                results.append(
                    WorkspaceBackfillResult(workspace.id, 0, 0, 0, 0, "skipped")
                )
                continue

            client = get_or_create_default_client(session, workspace)
            bind_connections_to_client(session, client=client, connections=active)

            windows_ok = 0
            windows_failed = 0
            total_rows = 0
            last_error = ""
            for platform, conns in _group_by_platform(active).items():
                start = platform_starts.get(platform, end_date)
                for win_start, win_end in _date_chunks(start, end_date, window_days):
                    try:
                        outcome = run_sync(
                            connections=conns,
                            destination=destination,
                            workspace_id=workspace.id,
                            client_id=client.client_key,
                            start_date=win_start,
                            end_date=win_end,
                            meta_connector_factory=meta_connector_factory,
                            google_connector_factory=google_connector_factory,
                            token_key=encryption_key,
                        )
                        total_rows += outcome.total_rows
                        windows_ok += 1
                    except Exception as exc:  # noqa: BLE001 - keep going, log type only
                        windows_failed += 1
                        last_error = type(exc).__name__

            status = "backfilled" if windows_ok else "error"
            results.append(
                WorkspaceBackfillResult(
                    workspace.id,
                    len(active),
                    windows_ok,
                    windows_failed,
                    total_rows,
                    status,
                    last_error,
                )
            )
        except Exception as exc:
            # One workspace failing must not stop the rest.
            results.append(
                WorkspaceBackfillResult(
                    workspace.id, 0, 0, 0, 0, "error", type(exc).__name__
                )
            )
    return results


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    """Backfill all workspaces' active accounts to the platform limit, then refresh."""
    load_dotenv()
    project_id = _required_env("GCP_PROJECT_ID")
    dataset_id = _required_env("BIGQUERY_DATASET")
    window_days = _int_env("BACKFILL_WINDOW_DAYS", DEFAULT_WINDOW_DAYS)
    meta_days = _int_env("BACKFILL_META_DAYS", DEFAULT_BACKFILL_DAYS["meta_ads"])
    google_days = _int_env("BACKFILL_GOOGLE_DAYS", DEFAULT_BACKFILL_DAYS["google_ads"])

    settings = load_web_settings()
    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    end_date = (today_in_timezone("Asia/Taipei") - timedelta(days=1)).isoformat()
    platform_starts = {
        "meta_ads": _start_for(end_date, meta_days),
        "google_ads": _start_for(end_date, google_days),
    }

    engine = create_db_engine()
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        results = backfill_all(
            session,
            destination=destination,
            meta_connector_factory=make_meta_factory(),
            google_connector_factory=make_google_factory(settings),
            end_date=end_date,
            platform_starts=platform_starts,
            window_days=window_days,
            encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
        )

    any_ok = any(r.windows_ok for r in results)
    refresh_status = "skipped"
    if any_ok:
        try:
            refresh_reporting_marts(destination=destination)
            refresh_status = "ok"
        except Exception as exc:  # noqa: BLE001 - log type only, never secrets
            refresh_status = f"failed:{type(exc).__name__}"

    backfilled = sum(1 for r in results if r.status == "backfilled")
    errored = sum(1 for r in results if r.status == "error")
    rows = sum(r.rows for r in results)
    windows_failed = sum(r.windows_failed for r in results)
    print(
        "backfill_done=true "
        f"workspaces={len(results)} backfilled={backfilled} errored={errored} "
        f"rows={rows} windows_failed={windows_failed} "
        f"meta_from={platform_starts['meta_ads']} "
        f"google_from={platform_starts['google_ads']} to={end_date} "
        f"marts_refresh={refresh_status}"
    )


if __name__ == "__main__":
    main()
