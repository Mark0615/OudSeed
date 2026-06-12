"""Generate one Looker / Data Studio view per ad account ("one source per account").

Goal: let each Data Studio data source point at exactly **one** ad account. For
every account that already has data in the WIDE views, this creates a dedicated
BigQuery view filtered to that single ``account_id``:

  vw_acct_meta_<account_id>     <- over vw_looker_meta_ads_wide
  vw_acct_google_<account_id>   <- over vw_looker_google_ads_wide

These are thin ``CREATE OR REPLACE VIEW`` filters over the existing wide views,
so:
  * No re-sync of ad data is needed — the data is already in BigQuery.
  * Re-running is safe and idempotent: it just refreshes the per-account views
    (and picks up any newly-onboarded accounts).

The account list is read at runtime from the wide views (after the orphan purge,
only your live workspace's accounts remain), so **no account ids are committed to
git** — this script discovers them in BigQuery when you run it.

Safety:
  * DRY-RUN by default — prints how many views *would* be created. Pass
    ``--apply`` to actually create them.
  * Prints counts + redacted account ids only — never full ids. (The real ids
    are in the view *names* inside your own BigQuery project, where you pick them
    in Data Studio.)

Usage:
  .venv/bin/python scripts/generate_per_account_views.py            # dry-run
  .venv/bin/python scripts/generate_per_account_views.py --apply    # create views
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

# Allow running as a plain script: put the repo root on sys.path so imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

# platform short name -> the wide view each per-account view is built over.
SOURCE_VIEWS: dict[str, str] = {
    "meta": "vw_looker_meta_ads_wide",
    "google": "vw_looker_google_ads_wide",
}

VIEW_PREFIX = "vw_acct"


def _safe_id(account_id: str) -> str:
    """Make an account id safe to embed in a BigQuery identifier."""
    return re.sub(r"[^0-9A-Za-z]", "_", str(account_id))


def _view_name(platform_short: str, account_id: str) -> str:
    """Deterministic per-account view name, e.g. vw_acct_meta_act_123."""
    return f"{VIEW_PREFIX}_{platform_short}_{_safe_id(account_id)}"


def _redact(account_id: str) -> str:
    """Redact an account id for terminal/log output (keep last 4 chars)."""
    text = str(account_id)
    return "REDACTED" if len(text) <= 4 else f"…{text[-4:]}"


def _list_account_ids(client: object, fq_source_view: str) -> list[str]:
    """Return the distinct, non-null account ids present in a wide view."""
    sql = (
        f"SELECT DISTINCT account_id FROM `{fq_source_view}` "
        "WHERE account_id IS NOT NULL ORDER BY account_id"
    )
    rows = client.query(sql).result()  # type: ignore[attr-defined]
    return [row.account_id for row in rows]


def plan_per_account_views(
    client: object,
    *,
    project_id: str,
    dataset_id: str,
    source_views: dict[str, str] = SOURCE_VIEWS,
    log: Callable[[str], None] = print,
) -> list[tuple[str, str, str, str]]:
    """Build the (platform, account_id, view_name, ddl) plan for every account.

    Reads the distinct account ids from each wide view. A missing source view
    (e.g. no Google data yet) is skipped rather than fatal.
    """
    plans: list[tuple[str, str, str, str]] = []
    for platform_short, source_view in source_views.items():
        fq_source = f"{project_id}.{dataset_id}.{source_view}"
        try:
            account_ids = _list_account_ids(client, fq_source)
        except Exception as exc:  # noqa: BLE001 — missing view / transient: skip, don't crash
            log(f"  skip {source_view}: {exc.__class__.__name__}")
            continue

        log(f"  {source_view}: {len(account_ids)} account(s)")
        for account_id in account_ids:
            view_name = _view_name(platform_short, account_id)
            fq_view = f"{project_id}.{dataset_id}.{view_name}"
            # account ids are alphanumeric; strip quotes defensively before inlining.
            escaped = str(account_id).replace("'", "")
            ddl = (
                f"CREATE OR REPLACE VIEW `{fq_view}` AS\n"
                f"SELECT * FROM `{fq_source}`\n"
                f"WHERE account_id = '{escaped}'"
            )
            plans.append((platform_short, account_id, view_name, ddl))
    return plans


def generate(
    client: object,
    *,
    project_id: str,
    dataset_id: str,
    apply: bool = False,
    source_views: dict[str, str] = SOURCE_VIEWS,
    log: Callable[[str], None] = print,
) -> list[tuple[str, str, str, str]]:
    """Plan (and, when ``apply``, create) one view per account. Returns the plan."""
    plans = plan_per_account_views(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        source_views=source_views,
        log=log,
    )
    verb = "created" if apply else "would create"
    for platform_short, account_id, view_name, ddl in plans:
        if apply:
            client.query(ddl).result()  # type: ignore[attr-defined]
        log(f"  {verb} {VIEW_PREFIX}_{platform_short}_{_redact(account_id)}")

    if not apply:
        log(f"\nDRY-RUN: {len(plans)} per-account view(s) would be created. Re-run with --apply.")
    else:
        log(f"\nDone. Created/refreshed {len(plans)} per-account view(s).")
    return plans


def _iter_log(messages: Iterable[str]) -> None:  # pragma: no cover - convenience only
    for message in messages:
        print(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually create views (default is dry-run)"
    )
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
