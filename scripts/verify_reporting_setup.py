"""Read-only health check for the reporting layer (② per-account views + ④ conversion actions).

Confirms that the conversion-action backfill actually landed and that the
per-account views exist. **Read-only** — it only runs SELECT / INFORMATION_SCHEMA
queries and never writes. Output is aggregates + redacted account ids only.

Usage:
  .venv/bin/python scripts/verify_reporting_setup.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

CONV_VIEW = "vw_looker_google_ads_conversion_action_wide"
RAW_GOOGLE = "raw_google_ads_daily"


def _redact(value: object) -> str:
    text = str(value)
    return "REDACTED" if len(text) <= 4 else f"…{text[-4:]}"


def _fmt(n: object) -> str:
    try:
        return f"{float(n):,.0f}"
    except (TypeError, ValueError):
        return str(n)


def main() -> int:
    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset_id = os.getenv("BIGQUERY_DATASET")
    if not project_id or not dataset_id:
        print("Missing GCP_PROJECT_ID / BIGQUERY_DATASET.", file=sys.stderr)
        return 2

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    ds = f"{project_id}.{dataset_id}"

    def q(sql: str):
        return list(client.query(sql).result())

    print("=" * 60)
    print("④  Google 轉換動作（conversion action）")
    print("=" * 60)
    conv_fq = f"{ds}.{CONV_VIEW}"
    try:
        summary = q(
            f"SELECT COUNT(*) AS rows_n, MIN(date) AS min_date, MAX(date) AS max_date, "
            f"COUNT(DISTINCT account_id) AS accounts, "
            f"COUNT(DISTINCT conversion_action_name) AS actions, "
            f"SUM(all_conversions) AS all_conv "
            f"FROM `{conv_fq}`"
        )[0]
        rows_n = summary.rows_n or 0
        print(f"  view {CONV_VIEW}")
        print(f"    資料列數 rows      : {_fmt(rows_n)}")
        if rows_n == 0:
            print("    ⚠️  目前是空的 —— 代表 conversion_action 資料還沒寫進來。")
            print("       檢查：(1) backfill 是否用到新程式碼 (git pull 後再跑)")
            print("            (2) BACKFILL_GOOGLE_DAYS 視窗是否涵蓋有轉換的日期")
        else:
            print(f"    日期範圍 date      : {summary.min_date} .. {summary.max_date}")
            print(f"    帳號數 accounts    : {summary.accounts}")
            print(f"    不重複轉換動作數   : {summary.actions}")
            print(f"    all_conversions 合計: {_fmt(summary.all_conv)}")

            accts = q(f"SELECT DISTINCT account_id FROM `{conv_fq}` ORDER BY account_id")
            print("    帳號（遮罩）       : " + ", ".join(_redact(r.account_id) for r in accts))

            print("    轉換動作前 10 名（依 all_conversions）：")
            top = q(
                f"SELECT conversion_action_name AS name, "
                f"SUM(all_conversions) AS all_conv, SUM(conversion_value) AS conv_value "
                f"FROM `{conv_fq}` GROUP BY name ORDER BY all_conv DESC LIMIT 10"
            )
            for r in top:
                name = r.name or "(未命名)"
                print(f"      - {name}: all_conv={_fmt(r.all_conv)}, value={_fmt(r.conv_value)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 讀取 {CONV_VIEW} 失敗: {exc.__class__.__name__}: {exc}")

    # Cross-check the raw table actually has the new report_level rows.
    try:
        raw = q(
            f"SELECT COUNT(*) AS n FROM `{ds}.{RAW_GOOGLE}` "
            "WHERE report_level = 'conversion_action'"
        )[0]
        print(f"  raw {RAW_GOOGLE} report_level='conversion_action' 列數: {_fmt(raw.n)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 讀取 {RAW_GOOGLE} 失敗: {exc.__class__.__name__}: {exc}")

    print()
    print("=" * 60)
    print("②  每帳號 view（per-account views）")
    print("=" * 60)
    try:
        views = q(
            f"SELECT table_name FROM `{ds}.INFORMATION_SCHEMA.VIEWS` "
            "WHERE table_name LIKE 'vw_acct_%' ORDER BY table_name"
        )
        meta = [v.table_name for v in views if v.table_name.startswith("vw_acct_meta_")]
        google = [v.table_name for v in views if v.table_name.startswith("vw_acct_google_")]
        print(f"    vw_acct_* 總數: {len(views)}  (meta: {len(meta)}, google: {len(google)})")
        if not views:
            print("    ⚠️  還沒有任何 per-account view —— 跑 --apply 後再驗一次。")
        for v in views:
            # table_name embeds the account id -> redact for output.
            prefix, _, acct = v.table_name.rpartition("_")
            print(f"      - {prefix}_{_redact(acct)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 讀取 INFORMATION_SCHEMA.VIEWS 失敗: {exc.__class__.__name__}: {exc}")

    print()
    print("驗證完成（唯讀，未變更任何資料）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
