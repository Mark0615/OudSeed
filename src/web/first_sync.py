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

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from src.destinations.bigquery import BigQueryDestination
from src.storage.models import PlatformConnection
from src.storage.repository import read_connection_token
from src.transforms.normalize_google import normalize_google_ads_rows
from src.transforms.normalize_meta import normalize_meta_ads_rows

UNIFIED_TABLE = "unified_ads_daily"

# token -> a connector exposing fetch_daily_report(...).
ConnectorFactory = Callable[[str], object]

# Meta's ad-level Insights API often can't serve a full 30-day window
# synchronously for large accounts and returns transient "Service temporarily
# unavailable" errors. Pull the range in smaller windows and retry transient
# failures per window so big accounts still sync.
DEFAULT_CHUNK_DAYS = 7
DEFAULT_MAX_ATTEMPTS = 3
# Substrings that mark a retryable ad-API error (vs. a permanent permission/data
# error, which should fail fast). Matched case-insensitively against the message.
_TRANSIENT_MARKERS = (
    "temporarily unavailable",
    "is_transient",
    "an unknown error occurred",
    "please reduce the amount of data",
    "internal error",
    "status 500",
    "status 503",
)


def _looks_transient(message: str) -> bool:
    """Return True when an ad-API error message looks worth retrying."""
    low = message.lower()
    return any(marker in low for marker in _TRANSIENT_MARKERS)


def _date_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    """Split an inclusive YYYY-MM-DD range into <=chunk_days inclusive sub-ranges."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if chunk_days < 1 or start > end:
        return [(start_date, end_date)]
    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _fetch_with_retry(
    fetch: Callable[[str, str], list[dict]],
    start_date: str,
    end_date: str,
    *,
    max_attempts: int,
    sleep: Callable[[float], None],
) -> list[dict]:
    """Call fetch(start, end), retrying transient failures with linear backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch(start_date, end_date)
        except Exception as exc:
            if attempt >= max_attempts or not _looks_transient(str(exc)):
                raise
            sleep(float(attempt))
    return []  # unreachable: the loop always returns or raises


def _fetch_chunked(
    fetch: Callable[[str, str], list[dict]],
    start_date: str,
    end_date: str,
    *,
    chunk_days: int,
    max_attempts: int,
    sleep: Callable[[float], None],
) -> list[dict]:
    """Fetch a date range in chunks, retrying transient failures per chunk."""
    rows: list[dict] = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, chunk_days):
        rows.extend(
            _fetch_with_retry(
                fetch, chunk_start, chunk_end, max_attempts=max_attempts, sleep=sleep
            )
        )
    return rows


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
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
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
            chunk_days=chunk_days,
            max_attempts=max_attempts,
            sleep=sleep,
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
    chunk_days: int,
    max_attempts: int,
    sleep: Callable[[float], None],
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
            raw_rows = _fetch_chunked(
                lambda s, e: connector.fetch_daily_report(
                    account_id=account_id, start_date=s, end_date=e
                ),
                start_date,
                end_date,
                chunk_days=chunk_days,
                max_attempts=max_attempts,
                sleep=sleep,
            )
            normalized = normalize_meta_ads_rows(raw_rows, context=context)
        elif platform == "google_ads":
            connector = google_connector_factory(token)
            raw_rows = _fetch_chunked(
                lambda s, e: connector.fetch_daily_report(
                    customer_id=account_id, start_date=s, end_date=e
                ),
                start_date,
                end_date,
                chunk_days=chunk_days,
                max_attempts=max_attempts,
                sleep=sleep,
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
