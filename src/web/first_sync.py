"""On-demand "first sync" for a workspace's selected ad accounts.

Powers the onboarding "Run first sync" button. For each active connection it
pulls a recent window of data and writes it to BigQuery under the **web tenant**
ids (``workspace_id`` + the onboarding client + the connected account id), so the
Preview step reads real numbers back.

Connector construction is injected so this orchestrator is unit-testable offline;
the web route supplies real connectors built from settings. Each account is
isolated: one account failing does not abort the others.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.destinations.bigquery import BigQueryDestination
from src.storage.models import PlatformConnection
from src.storage.repository import read_connection_token
from src.transforms.normalize_google import normalize_google_ads_rows
from src.transforms.normalize_meta import normalize_meta_ads_rows

UNIFIED_TABLE = "unified_ads_daily"

# token -> a connector exposing fetch_daily_report(...).
ConnectorFactory = Callable[[str], object]


@dataclass(frozen=True)
class AccountSyncResult:
    """Outcome of syncing one account."""

    platform: str
    account_id: str
    status: str  # "success" | "failed" | "skipped"
    rows: int = 0
    error: str | None = None


@dataclass(frozen=True)
class FirstSyncResult:
    """Aggregate outcome across all attempted accounts."""

    results: tuple[AccountSyncResult, ...] = ()

    @property
    def attempted(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> tuple[AccountSyncResult, ...]:
        return tuple(r for r in self.results if r.status == "success")

    @property
    def failed(self) -> tuple[AccountSyncResult, ...]:
        return tuple(r for r in self.results if r.status == "failed")

    @property
    def total_rows(self) -> int:
        return sum(r.rows for r in self.results)

    @property
    def has_failures(self) -> bool:
        return bool(self.failed)


def run_first_sync(
    *,
    connections: list[PlatformConnection],
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    start_date: str,
    end_date: str,
    meta_connector_factory: ConnectorFactory,
    google_connector_factory: ConnectorFactory,
    token_key: str | None = None,
) -> FirstSyncResult:
    """Sync each connection for the date window, writing unified rows to BigQuery."""
    results = [
        _sync_one(
            connection,
            destination=destination,
            workspace_id=workspace_id,
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            meta_connector_factory=meta_connector_factory,
            google_connector_factory=google_connector_factory,
            token_key=token_key,
        )
        for connection in connections
    ]
    return FirstSyncResult(results=tuple(results))


def _sync_one(
    connection: PlatformConnection,
    *,
    destination: BigQueryDestination,
    workspace_id: str,
    client_id: str,
    start_date: str,
    end_date: str,
    meta_connector_factory: ConnectorFactory,
    google_connector_factory: ConnectorFactory,
    token_key: str | None,
) -> AccountSyncResult:
    account_id = connection.external_account_id
    platform = connection.platform
    try:
        token = read_connection_token(connection, key=token_key)
        if not token:
            return AccountSyncResult(platform, account_id, "failed", error="No stored token.")

        context = {
            "workspace_id": workspace_id,
            "client_id": client_id,
            "account_id": account_id,
            "account_name": connection.account_name,
        }
        if platform == "meta_ads":
            connector = meta_connector_factory(token)
            raw_rows = connector.fetch_daily_report(
                account_id=account_id, start_date=start_date, end_date=end_date
            )
            normalized = normalize_meta_ads_rows(raw_rows, context=context)
        elif platform == "google_ads":
            connector = google_connector_factory(token)
            raw_rows = connector.fetch_daily_report(
                customer_id=account_id, start_date=start_date, end_date=end_date
            )
            normalized = normalize_google_ads_rows(raw_rows, context=context)
        else:
            return AccountSyncResult(platform, account_id, "skipped")

        rows = destination.replace_date_range(
            table_name=UNIFIED_TABLE,
            rows=normalized,
            start_date=start_date,
            end_date=end_date,
            filters={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": platform,
                "account_id": account_id,
            },
        )
        return AccountSyncResult(platform, account_id, "success", rows=rows)
    except Exception as exc:
        # Isolate failures so one bad account does not abort the rest.
        return AccountSyncResult(platform, account_id, "failed", error=str(exc))
