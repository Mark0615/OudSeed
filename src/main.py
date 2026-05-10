"""Entry point for the OudSeed Meta Ads sync pipeline."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.connectors.google_ads import GoogleAdsConnector
from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination
from src.transforms.normalize_google import normalize_google_ads_rows
from src.transforms.normalize_meta import normalize_meta_ads_rows
from src.utils.config_loader import load_config, load_config_from_yaml
from src.utils.date_utils import get_default_sync_range


DEFAULT_CONFIG_PATH = "config/clients.yaml"
RAW_META_TABLE = "raw_meta_ads_daily"
RAW_GOOGLE_TABLE = "raw_google_ads_daily"
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

    bigquery_config = config.get("bigquery", {})
    project_id = os.getenv("GCP_PROJECT_ID") or bigquery_config.get("project_id")
    dataset_id = os.getenv("BIGQUERY_DATASET") or bigquery_config.get("dataset")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID or config.bigquery.project_id.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET or config.bigquery.dataset.")

    meta_api_timeout_seconds = _positive_int_env("META_API_TIMEOUT_SECONDS", 60)
    _log(
        "starting_meta_sync",
        project_id=project_id,
        dataset_id=dataset_id,
        meta_api_timeout_seconds=meta_api_timeout_seconds,
    )

    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    if _has_enabled_platform(config, "meta_ads"):
        connector = MetaAdsConnector(
            access_token=_required_env("META_ACCESS_TOKEN"),
            timeout_seconds=meta_api_timeout_seconds,
        )
        run_meta_sync(config=config, connector=connector, destination=destination)
    if _has_enabled_platform(config, "google_ads"):
        google_connector = GoogleAdsConnector(
            developer_token=_required_env("GOOGLE_ADS_DEVELOPER_TOKEN"),
            client_id=_required_env("GOOGLE_ADS_CLIENT_ID"),
            client_secret=_required_env("GOOGLE_ADS_CLIENT_SECRET"),
            refresh_token=_required_env("GOOGLE_ADS_REFRESH_TOKEN"),
            login_customer_id=os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
        )
        run_google_ads_sync(
            config=config,
            connector=google_connector,
            destination=destination,
        )
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
    _log(
        "meta_sync_range_resolved",
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        scheduler_timezone=timezone_name,
    )
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
        _log("refresh_reporting_sql_started", sql_path=str(sql_path))
        destination.execute_sql(sql_path.read_text(encoding="utf-8"))
        _log("refresh_reporting_sql_finished", sql_path=str(sql_path))


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
        _log(
            "meta_account_fetch_started",
            client_id=client_id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        raw_rows = connector.fetch_daily_report(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        rows_fetched = len(raw_rows)
        _log(
            "meta_account_fetch_finished",
            client_id=client_id,
            account_id=account_id,
            rows_fetched=rows_fetched,
        )

        raw_table_rows = _build_raw_rows(
            raw_rows=raw_rows,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            platform="meta_ads",
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
        _log(
            "meta_account_raw_replaced",
            client_id=client_id,
            account_id=account_id,
            rows=len(raw_table_rows),
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
        _log(
            "meta_account_unified_replaced",
            client_id=client_id,
            account_id=account_id,
            rows_inserted=rows_inserted,
        )
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        _log(
            "meta_account_sync_failed",
            client_id=client_id,
            account_id=account_id,
            error_message=error_message,
        )

    sync_log = _build_sync_log(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        platform="meta_ads",
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
    _log(
        "meta_account_sync_log_insert_started",
        client_id=client_id,
        account_id=account_id,
        status=status,
    )
    destination.insert_rows(SYNC_LOGS_TABLE, [sync_log])
    _log(
        "meta_account_sync_logged",
        client_id=client_id,
        account_id=account_id,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
    )
    return status


def run_google_ads_sync(
    config: dict[str, Any],
    connector: GoogleAdsConnector,
    destination: BigQueryDestination,
) -> None:
    """Run Google Ads sync for every enabled client/account in config."""
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
    _log(
        "google_ads_sync_range_resolved",
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        scheduler_timezone=timezone_name,
    )
    for client in config["clients"]:
        if not client.get("enabled", True):
            continue

        client_id = client["client_id"]
        google_config = client.get("platforms", {}).get("google_ads", {})
        if not google_config.get("enabled", False):
            continue

        for account in google_config.get("accounts", []):
            if account.get("enabled", True) is False:
                continue

            status = _sync_google_ads_account(
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
                failed_accounts.append(f"{client_id}/{account['customer_id']}")

    if failed_accounts:
        raise RuntimeError(
            f"Google Ads sync failed for {len(failed_accounts)} account(s)."
        )


def _sync_google_ads_account(
    workspace_id: str,
    client_id: str,
    account: dict[str, Any],
    defaults: dict[str, Any],
    scheduler_timezone: str,
    start_date: str,
    end_date: str,
    connector: GoogleAdsConnector,
    destination: BigQueryDestination,
) -> str:
    """Sync one Google Ads account and always write a sync log."""
    account_id = str(account["customer_id"]).replace("-", "")
    started_at = _utc_now()
    rows_fetched = 0
    rows_inserted = 0
    status = "success"
    error_message = None

    try:
        _log(
            "google_ads_account_fetch_started",
            client_id=client_id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        raw_rows = connector.fetch_daily_report(
            customer_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        rows_fetched = len(raw_rows)
        _log(
            "google_ads_account_fetch_finished",
            client_id=client_id,
            account_id=account_id,
            rows_fetched=rows_fetched,
        )
        raw_table_rows = _build_raw_rows(
            raw_rows=raw_rows,
            workspace_id=workspace_id,
            client_id=client_id,
            account_id=account_id,
            platform="google_ads",
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
            table_name=RAW_GOOGLE_TABLE,
            rows=raw_table_rows,
            start_date=start_date,
            end_date=end_date,
            filters={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "platform": "google_ads",
                "account_id": account_id,
            },
        )
        _log(
            "google_ads_account_raw_replaced",
            client_id=client_id,
            account_id=account_id,
            rows=len(raw_table_rows),
        )

        normalized_rows = normalize_google_ads_rows(
            raw_rows,
            context={
                "workspace_id": workspace_id,
                "client_id": client_id,
                "account_id": account_id,
                "account_name": account.get("account_name"),
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
                "platform": "google_ads",
                "account_id": account_id,
            },
        )
        _log(
            "google_ads_account_unified_replaced",
            client_id=client_id,
            account_id=account_id,
            rows_inserted=rows_inserted,
        )
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        _log(
            "google_ads_account_sync_failed",
            client_id=client_id,
            account_id=account_id,
            error_message=error_message,
        )

    sync_log = _build_sync_log(
        workspace_id=workspace_id,
        client_id=client_id,
        account_id=account_id,
        platform="google_ads",
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
    _log(
        "google_ads_account_sync_log_insert_started",
        client_id=client_id,
        account_id=account_id,
        status=status,
    )
    destination.insert_rows(SYNC_LOGS_TABLE, [sync_log])
    _log(
        "google_ads_account_sync_logged",
        client_id=client_id,
        account_id=account_id,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
    )
    return status


def _build_raw_rows(
    raw_rows: list[dict],
    workspace_id: str,
    client_id: str,
    account_id: str,
    platform: str,
    report_level: str,
    attribution_setting: str,
    timezone_setting: str,
) -> list[dict]:
    """Wrap raw API rows for a platform raw daily table."""
    now = _utc_now()
    return [
        {
            "date": row.get("date_start") or row.get("date"),
            "workspace_id": workspace_id,
            "client_id": client_id,
            "platform": platform,
            "account_id": account_id,
            "report_level": row.get("report_level") or report_level,
            "attribution_setting": attribution_setting,
            "timezone_setting": timezone_setting,
            "raw_payload": row,
            "created_at": now,
            "updated_at": now,
        }
        for row in raw_rows
    ]


def _build_sync_log(
    workspace_id: str,
    client_id: str,
    account_id: str,
    platform: str,
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
        "platform": platform,
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


def _has_enabled_platform(config: dict[str, Any], platform_name: str) -> bool:
    """Return whether any enabled client has an enabled platform config."""
    for client in config.get("clients", []):
        if not client.get("enabled", True):
            continue
        platform_config = client.get("platforms", {}).get(platform_name, {})
        if platform_config.get("enabled", False):
            return True
    return False


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc

    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")

    return value


def _log(event: str, **fields: Any) -> None:
    """Print structured runtime progress for local runs and Cloud Logging."""
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"event={event} {payload}".strip(), flush=True)


def _utc_now() -> str:
    """Return current UTC timestamp as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
