# OudSeed Ads AI Pipeline

OudSeed is a Python ads data pipeline for syncing advertising performance data into BigQuery, then making it available to Looker Studio and future reporting workflows.

The current MVP priority is:

```text
Meta Ads -> BigQuery -> unified_ads_daily -> Looker Studio
```

Future phases will add Google Ads, LINE Ads, Google Sheet export, and AI-generated weekly reports.

## Project Structure

```text
config/        Example client configuration
docs/          Product and engineering specifications
src/           Pipeline source code
sql/           BigQuery SQL scripts
tests/         Unit tests and fixtures
deploy/        Deployment files for later Cloud Run usage
```

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
make install
make check
```

Copy `config/clients.example.yaml` to `config/clients.yaml` for local development, and copy `.env.example` to `.env` when credentials are needed.

Do not commit real credentials, ad account IDs, service account JSON files, `.env`, or `config/clients.yaml`.

## Local Run

Create local-only config files:

```bash
cp .env.example .env
cp config/clients.example.yaml config/clients.yaml
mkdir -p secrets
```

Fill `.env` with local credentials:

```bash
GCP_PROJECT_ID=oudseed
BIGQUERY_DATASET=ads_pipeline
GOOGLE_APPLICATION_CREDENTIALS=/Users/mark/Desktop/OudSeed/secrets/your-service-account.json
META_ACCESS_TOKEN=your-meta-marketing-api-token
```

Fill `config/clients.yaml` with the real Meta Ads account settings:

```yaml
clients:
  - client_id: your_client_id
    client_name: Your Client Name
    enabled: true
    platforms:
      meta_ads:
        enabled: true
        accounts:
          - ad_account_id: "act_000000000000000"
            account_name: "Your Meta Ads Account"
            report_level: "ad"
            attribution_setting: "platform_default"
            timezone_setting: "platform_account_default"
            conversion_action_type: "purchase"
```

Create or update the BigQuery tables and Looker Studio views:

```bash
.venv/bin/python -c 'from dotenv import load_dotenv; load_dotenv(); from google.cloud import bigquery; client=bigquery.Client(); client.query(open("sql/create_tables.sql", encoding="utf-8").read()).result(); client.query(open("sql/looker_studio_views.sql", encoding="utf-8").read()).result(); print("bigquery_ready=True")'
```

Run the default daily sync:

```bash
make run
```

The default sync range is yesterday and the previous 7 days in `Asia/Taipei`.

## Backfill

Use `SYNC_START_DATE` and `SYNC_END_DATE` for a manual date range backfill:

```bash
SYNC_START_DATE=2025-03-01 SYNC_END_DATE=2025-03-31 make run
```

The sync flow will:

- fetch Meta Ads Insights rows
- replace matching rows in `raw_meta_ads_daily`
- normalize rows into `unified_ads_daily`
- write a row to `sync_logs`

For the March 2025 test account validation, the expected BigQuery result is:

```text
spend = 42218.0
link_clicks = 3611
```

Verify a backfill in BigQuery:

```sql
SELECT
  COUNT(*) AS row_count,
  ROUND(SUM(spend), 2) AS spend,
  SUM(link_clicks) AS link_clicks,
  SAFE_DIVIDE(SUM(spend), SUM(link_clicks)) AS cpc
FROM `oudseed.ads_pipeline.vw_looker_ads_campaign_daily`
WHERE date BETWEEN DATE("2025-03-01") AND DATE("2025-03-31")
  AND platform = "meta_ads";
```

## Looker Studio Setup

In Looker Studio, create a BigQuery data source:

```text
Project: oudseed
Dataset: ads_pipeline
Table/View: vw_looker_ads_campaign_daily
```

Recommended starter dashboard:

- Scorecard: `spend`
- Scorecard: `link_clicks`
- Scorecard: `cpc`
- Time series: `date` by `spend`
- Time series: `date` by `link_clicks`
- Table: `campaign_name`, `spend`, `link_clicks`, `ctr`, `cpc`

Available reporting views:

| View | Purpose |
|---|---|
| `vw_looker_ads_campaign_daily` | Campaign-level daily dashboard source |
| `vw_looker_ads_ad_daily` | Ad-level detail table source |
| `vw_looker_sync_status` | Sync monitoring and error review |

Use `link_clicks` as the primary click metric for Meta reporting. It maps to Meta `inline_link_clicks`, which matches the current validation baseline.

## Current Scope

This repository is currently prepared for v0.1 development:

- Project skeleton
- BigQuery schema
- Config loader
- Date utilities
- BigQuery destination
- Base connector
- Meta Ads connector
- Meta Ads normalize
- Main Meta Ads sync flow
- Sync logs

Google Ads, LINE Ads, AI reports, OAuth, SaaS login, payment, and frontend dashboard work are intentionally out of scope until explicitly requested.
