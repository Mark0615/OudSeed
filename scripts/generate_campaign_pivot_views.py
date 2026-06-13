"""Generate a per-account "campaign pivot" view: spend + a column per conversion action.

The normal wide views keep spend and the per-conversion-action breakdown at
different grains (mixing them would duplicate spend). This builds the Windsor-style
**single table**: one row per (date, campaign) with the additive delivery metrics
*and* one column per conversion action — by pivoting the conversion actions into
columns at the campaign grain.

For each Google account that has data it creates:

  vw_acct_google_campaign_pivot_<account_id>

columns: date, campaign, spend, clicks, impressions, total_conversions,
         total_conversion_value, conv_<action> (one per conversion action).

The conversion-action names are read at RUNTIME from BigQuery (per account), so no
client-specific names are committed to git. Re-running is idempotent
(CREATE OR REPLACE) and picks up new conversion actions automatically.

Safety:
  * DRY-RUN by default — prints what would be created. Pass --apply to create.
  * Prints redacted account ids only.

Usage:
  .venv/bin/python scripts/generate_campaign_pivot_views.py            # dry-run
  .venv/bin/python scripts/generate_campaign_pivot_views.py --apply    # create views
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

AD_VIEW = "vw_looker_google_ads_wide"
CONV_VIEW = "vw_looker_google_ads_conversion_action_wide"
VIEW_PREFIX = "vw_acct_google_campaign_pivot"


def _safe_id(account_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "_", str(account_id))


def _redact(account_id: str) -> str:
    text = str(account_id)
    return "REDACTED" if len(text) <= 4 else f"…{text[-4:]}"


def _sql_str(value: str) -> str:
    """Escape a Python string for a single-quoted BigQuery string literal."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _col_alias(name: str, index: int) -> str:
    """Turn a conversion-action name into a column alias.

    Keeps letters (incl. CJK) and digits — BigQuery flexible column names allow
    them — and falls back to an index when nothing usable remains.
    """
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", str(name)).strip("_")
    if not cleaned:
        cleaned = f"action_{index}"
    return f"conv_{cleaned}"


def _aliased_actions(names: list[str]) -> list[tuple[str, str]]:
    """Pair each conversion-action name with a unique column alias."""
    out: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for index, name in enumerate(names, start=1):
        alias = _col_alias(name, index)
        if alias in seen:
            seen[alias] += 1
            alias = f"{alias}_{seen[alias]}"
        else:
            seen[alias] = 1
        out.append((name, alias))
    return out


def build_pivot_ddl(
    *, project_id: str, dataset_id: str, account_id: str, action_names: list[str]
) -> tuple[str, str]:
    """Return (view_name, ddl) for one account's campaign-pivot view."""
    ds = f"{project_id}.{dataset_id}"
    view_name = f"{VIEW_PREFIX}_{_safe_id(account_id)}"
    fq_view = f"{ds}.{view_name}"
    acct = _sql_str(account_id)

    ad_cte = (
        f"  SELECT date, account_id, campaign_id,\n"
        f"         ANY_VALUE(campaign_name) AS campaign_name,\n"
        f"         ANY_VALUE(campaign_status) AS campaign_status,\n"
        f"         SUM(spend) AS spend,\n"
        f"         SUM(clicks) AS clicks,\n"
        f"         SUM(impressions) AS impressions,\n"
        f"         SUM(conversions) AS total_conversions,\n"
        f"         SUM(conversion_value) AS total_conversion_value\n"
        f"  FROM `{ds}.{AD_VIEW}`\n"
        f"  WHERE account_id = '{acct}'\n"
        f"  GROUP BY date, account_id, campaign_id"
    )

    if action_names:
        # Per-action columns use all_conversions (the action's own total count) so
        # micro-actions like Page view show their real volume — Google's primary
        # "conversions" count is 0 for actions not flagged as conversions. The
        # campaign summary keeps total_conversions/value (the primary metric that
        # spend / ROAS tie to).
        conv_cols = ",\n         ".join(
            f"SUM(IF(conversion_action_name = '{_sql_str(name)}', all_conversions, 0)) AS `{alias}`"
            for name, alias in _aliased_actions(action_names)
        )
        ddl = (
            f"CREATE OR REPLACE VIEW `{fq_view}` AS\n"
            f"WITH ad AS (\n{ad_cte}\n),\n"
            f"conv AS (\n"
            f"  SELECT date, account_id, campaign_id,\n         {conv_cols}\n"
            f"  FROM `{ds}.{CONV_VIEW}`\n"
            f"  WHERE account_id = '{acct}'\n"
            f"  GROUP BY date, account_id, campaign_id\n"
            f")\n"
            f"SELECT ad.date, ad.account_id, ad.campaign_id, ad.campaign_name, ad.campaign_status,\n"
            f"       ad.spend, ad.clicks, ad.impressions, ad.total_conversions, ad.total_conversion_value,\n"
            f"       conv.* EXCEPT (date, account_id, campaign_id)\n"
            f"FROM ad\n"
            f"LEFT JOIN conv USING (date, account_id, campaign_id)"
        )
    else:
        # No conversion actions for this account yet: still expose the additive
        # delivery metrics per campaign so the view is valid and useful.
        ddl = f"CREATE OR REPLACE VIEW `{fq_view}` AS\nWITH ad AS (\n{ad_cte}\n)\nSELECT * FROM ad"

    return view_name, ddl


def _distinct(client: object, sql: str, attr: str) -> list[str]:
    rows = client.query(sql).result()  # type: ignore[attr-defined]
    return [getattr(row, attr) for row in rows]


def plan_pivot_views(
    client: object,
    *,
    project_id: str,
    dataset_id: str,
    log: Callable[[str], None] = print,
) -> list[tuple[str, str, str]]:
    """Build (account_id, view_name, ddl) for every Google account."""
    ds = f"{project_id}.{dataset_id}"
    try:
        account_ids = _distinct(
            client,
            f"SELECT DISTINCT account_id FROM `{ds}.{AD_VIEW}` "
            "WHERE account_id IS NOT NULL ORDER BY account_id",
            "account_id",
        )
    except Exception as exc:  # noqa: BLE001 — missing view: nothing to do
        log(f"  skip {AD_VIEW}: {exc.__class__.__name__}")
        return []

    plans: list[tuple[str, str, str]] = []
    for account_id in account_ids:
        try:
            actions = _distinct(
                client,
                f"SELECT DISTINCT conversion_action_name FROM `{ds}.{CONV_VIEW}` "
                f"WHERE account_id = '{_sql_str(account_id)}' "
                "AND conversion_action_name IS NOT NULL ORDER BY conversion_action_name",
                "conversion_action_name",
            )
        except Exception:  # noqa: BLE001 — no conversion view yet: pivot with no action columns
            actions = []
        view_name, ddl = build_pivot_ddl(
            project_id=project_id,
            dataset_id=dataset_id,
            account_id=account_id,
            action_names=actions,
        )
        log(f"  {_redact(account_id)}: {len(actions)} conversion action(s)")
        plans.append((account_id, view_name, ddl))
    return plans


def generate(
    client: object,
    *,
    project_id: str,
    dataset_id: str,
    apply: bool = False,
    log: Callable[[str], None] = print,
) -> list[tuple[str, str, str]]:
    """Plan (and, when ``apply``, create) the campaign-pivot views."""
    plans = plan_pivot_views(client, project_id=project_id, dataset_id=dataset_id, log=log)
    verb = "created" if apply else "would create"
    for account_id, _view_name, ddl in plans:
        if apply:
            client.query(ddl).result()  # type: ignore[attr-defined]
        log(f"  {verb} {VIEW_PREFIX}_{_redact(account_id)}")

    if not apply:
        log(f"\nDRY-RUN: {len(plans)} campaign-pivot view(s) would be created. Re-run with --apply.")
    else:
        log(f"\nDone. Created/refreshed {len(plans)} campaign-pivot view(s).")
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually create views (default dry-run)")
    args = parser.parse_args()

    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset_id = os.getenv("BIGQUERY_DATASET")
    if not project_id or not dataset_id:
        print("Missing GCP_PROJECT_ID / BIGQUERY_DATASET.", file=sys.stderr)
        return 2

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    generate(client, project_id=project_id, dataset_id=dataset_id, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
