"""Entry point for the OudSeed Meta Ads sync pipeline."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination
from src.transforms.normalize_meta import normalize_meta_ads_rows
from src.utils.config_loader import load_config, load_config_from_yaml
from src.utils.date_utils import get_default_sync_range


DEFAULT_CONFIG_PATH = "config/clients.yaml"
RAW_META_TABLE = "raw_meta_ads_daily"
UNIFIED_TABLE = "unified_ads_daily"
SYNC_LOGS_TABLE = "sync_logs"
SUMMARY_SQL_PATHS = (
    Path("sql/weekly_summary.sql"),
    Path("sql/monthly_summary.sql"),
    Path("sql/looker_studio_views.sql"),
)


def main() -> None:
    """Run the Meta Ads sync flow using local configuration."""
    load_dotenv()
    config = _load_runtime_config()
    access_token = _required_env("META_ACCESS_TOKEN")

    bigquery_config = config.get("bigquery", {})
    project_id = os.getenv("GCP_PROJECT_ID") or bigquery_config.get("project_id")
    dataset_id = os.getenv("BIGQUERY_DATASET") or bigquery_config.get("dataset")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID or config.bigquery.project_id.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET or config.bigquery.dataset.")

    connector = MetaAdsConnector(access_token=access_token)
    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    run_meta_sync(config=config, connector=connector, destination=destination)
    if _should_refresh_reporting_marts():
        refresh_reporting_marts(destination=destination)


def run_meta_sync(
    config: dict[str, Any],
    connector: MetaAdsConnector,
    destination: BigQueryDestination,
) -> None:
    """Run Meta Ads sync for every enabled client/account in config."""
    defaults = config.get("defaults", {})
    timezone_name = defaults.get("timezone", "Asia/Taipei")
    days_back = int(defaults.get("sync_days_back", 7))
    start_date = os.getenv("SYNC_START_DATE")
    end_date = os.getenv("SYNC_END_DATE")
    if not start_date or not end_date:
        start_date, end_date = get_default_sync_range(
            days_back=days_back,
            timezone=timezone_name,
        )

    workspace_id = config["workspace_id"]
    failed_accounts: list[str] = []
    for client in config["clients"]:
        if not client.get("enabled", True):
            continue

        client_id = client["client_id"]
        meta_config = client.get("platforms", {}).get("meta_ads", {})
        if not meta_config.get("enabled", False):
            continue

        for account in meta_config.get("accounts", []):
            if account.get("enabled", True) is False:
                continue

            status = _sync_meta_account(
                workspace_id=workspace_id,
                client_id=client_id,
                account=account,
                defaults=defaults,
                scheduler_timezone=timezone_name,
                start_date=start_date,
                end_date=end_date,
                connector=connector,
                destination=destination,
            )
            if status != "success":
                failed_accounts.append(f"{client_id}/{account['ad_account_id']}")

    if failed_accounts:
        raise RuntimeError(f"Meta sync failed for {len(failed_accounts)} account(s).")


def refresh_reporting_marts(
    destination: BigQueryDestination,
    sql_paths: tuple[Path, ...] = SUMMARY_SQL_PATHS,
) -> None:
    """Refresh BigQuery reporting marts and Looker Studio views."""
    for sql_path in sql_paths:
        destination.execute_sql(sql_path.read_text(encoding="utf-8"))


def _should_refresh_reporting_marts() -> bool:
    """Return whether reporting marts should refresh after a successful sync."""
    value = os.getenv("REFRESH_REPORTING_MARTS", "true").strip().lower()
    return value not in {"0", "false", "no"}


def _load_runtime_config() -> dict[str, Any]:
    """Load config from Secret Manager env content or a local file path."""
    config_yaml = os.getenv("CLIENTS_CONFIG_YAML")
    if config_yaml:
        return load_config_from_yaml(config_yaml, source="CLIENTS_CONFIG_YAML")

    config_path = os.getenv("CLIENTS_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    return load_config(config_path)


def _sync_meta_account(
    workspace_id: str,
    client_id: str,
    account: dict[str, Any],
    defaults: dict[str, Any],
    scheduler_timezone: str,
    start_date: str,
    end_date: str,
    connector: MetaAdsConnector,
    destination: BigQueryDestination,
) -> str:
    """Sync one Meta Ads account and always write a sync log."""
    account_id = account["ad_account_id"]
    started_at = _utc_now()
    rows_fetched = 0
    rows_inserted = 0
    status = "success"
    error_message = None

    try:
        raw_rows = connector.fetch_daily_report(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        rows_fetched = len(raw_rows)

        raw_table_rows = _build_raw_rows(
            raw_rows=raw_rows,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            report_level=account.get("report_level", "ad"),
            attribution_setting=account.get(
                "attribution_setting",
                defaults.get("attribution_setting", "platform_default"),
            ),
            timezone_setting=account.get(
                "timezone_setting",
                defaults.get("timezone_setting", "platform_account_default"),
            ),
        )
        destination.replace_date_range(
            table_name=RAW_META_TABLE,
            rows=raw_table_rows,
            start_date=start_date,
            end_date=end_date,
            filters={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": "meta_ads",
                "account_id": account_id,
            },
        )

        normalized_rows = normalize_meta_ads_rows(
            raw_rows,
            context={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "account_id": account_id,
                "account_name": account.get("account_name"),
                "conversion_action_type": account.get(
                    "conversion_action_type",
                    defaults.get("conversion_action_type", "purchase"),
                ),
                "attribution_setting": account.get(
                    "attribution_setting",
                    defaults.get("attribution_setting", "platform_default"),
                ),
                "timezone_setting": account.get(
                    "timezone_setting",
                    defaults.get("timezone_setting", "platform_account_default"),
                ),
            },
        )
        rows_inserted = destination.replace_date_range(
            table_name=UNIFIED_TABLE,
            rows=normalized_rows,
            start_date=start_date,
            end_date=end_date,
            filters={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": "meta_ads",
                "account_id": account_id,
            },
        )
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        print(f"Meta Ads sync failed for {client_id}/{account_id}: {error_message}")

    sync_log = _build_sync_log(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
        error_message=error_message,
        attribution_setting=account.get(
            "attribution_setting",
            defaults.get("attribution_setting", "platform_default"),
        ),
        timezone_setting=account.get(
            "timezone_setting",
            defaults.get("timezone_setting", "platform_account_default"),
        ),
        scheduler_timezone=scheduler_timezone,
        started_at=started_at,
    )
    destination.insert_rows(SYNC_LOGS_TABLE, [sync_log])
    return status


def _build_raw_rows(
    raw_rows: list[dict],
    workspace_id: str,
    client_id: str,
    account_id: str,
    report_level: str,
    attribution_setting: str,
    timezone_setting: str,
) -> list[dict]:
    """Wrap raw API rows for raw_meta_ads_daily."""
    now = _utc_now()
    return [
        {
            "date": row.get("date_start"),
            "workspace_id": workspace_id,
            "client_id": client_id,
            "platform": "meta_ads",
            "account_id": account_id,
            "report_level": report_level,
            "attribution_setting": attribution_setting,
            "timezone_setting": timezone_setting,
            "raw_payload": json.dumps(row, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        for row in raw_rows
    ]


def _build_sync_log(
    workspace_id: str,
    client_id: str,
    account_id: str,
    start_date: str,
    end_date: str,
    status: str,
    rows_fetched: int,
    rows_inserted: int,
    error_message: str | None,
    attribution_setting: str,
    timezone_setting: str,
    scheduler_timezone: str,
    started_at: str,
) -> dict:
    """Build one sync_logs row."""
    return {
        "sync_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "client_id": client_id,
        "platform": "meta_ads",
        "account_id": account_id,
        "sync_start_date": start_date,
        "sync_end_date": end_date,
        "status": status,
        "rows_fetched": rows_fetched,
        "rows_inserted": rows_inserted,
        "error_message": error_message,
        "attribution_setting": attribution_setting,
        "timezone_setting": timezone_setting,
        "scheduler_timezone": scheduler_timezone,
        "started_at": started_at,
        "finished_at": _utc_now(),
    }


def _required_env(name: str) -> str:
    """Return a required environment variable."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _utc_now() -> str:
    """Return current UTC timestamp as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
