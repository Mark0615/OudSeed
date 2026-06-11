# CLAUDE.md

Guidance for Claude Code working in `Mark0615/OudSeed`. Read this first, then
`AGENTS.md` and `docs/ads_ai_pipeline_codex_development_spec.md` for the full
product spec. This file is the fast-path operating manual; `AGENTS.md` is the
canonical product/behavior contract and wins on any conflict.

## What this project is

An automated ads-performance assistant for media buyers. It syncs ad-platform
data into BigQuery, exposes reporting datasets to Looker Studio, and generates
recurring AI performance reports delivered as account-grouped HTML emails.

```text
Ads APIs → BigQuery (raw + unified) → reporting marts → Looker Studio + AI report → HTML email
```

Runtime: Python 3.13 (spec floor is 3.11+). Timezone: `Asia/Taipei`.
GCP project `oudseed`, BigQuery dataset `ads_pipeline`, region `asia-east1`.

## Current state (v0.4 product-shaped MVP)

Implemented and live:
- Meta Ads daily sync → `raw_meta_ads_daily` + `unified_ads_daily` + `sync_logs`
- Basic Google Ads connector, normalization, and sync foundation
- Weekly/monthly BigQuery summary marts + Looker Studio views
- Cloud Run Job + Cloud Scheduler for Meta sync
- OpenAI-powered (`gpt-5.2`) weekly/monthly report generation + `ai_report_logs`
- Account-grouped AI reports sent as SMTP HTML email (one email per account group)
- Local connector-onboarding prototype (Meta + Google discovery, destination
  selection, local config export, readiness gates, opt-in first-sync runner)

Tests: 215 passing. CI runs ruff + compileall + pytest on every PR
(`.github/workflows/ci.yml`); run `make check` locally before declaring done.

## Product direction (decided 2026-06-05)

Goal: replace a paid Windsor.ai-style subscription and let a few friendly users
self-onboard. Goal 1 (Meta/Google → BigQuery → Looker Studio) is ~done; Goal 2
(AI email report) exists. **The active main line is real self-serve onboarding.**

Decisions (see `AGENTS.md` "Product direction" for the full list):
- Platform login: **Google sign-in**. Ad-account auth: **dev-mode self-serve
  OAuth** (Meta + Google in development/test mode, early users added as testers,
  no App Review yet).
- Hosting/storage: stay in GCP — Cloud Run + Cloud SQL/Firestore + Secret
  Manager. Multi-tenancy via existing `workspace_id`/`client_id` columns.
- AI model stays OpenAI `gpt-5.2`; report format is acceptable, polish only.

Phased plan: (1) hardening baseline ✅ → (2) durable multi-tenant storage →
(3) Meta+Google OAuth connect → (4) Google sign-in + end-to-end onboarding →
(5) per-customer report scheduling + polish.

## Scope discipline (important)

**In scope now:** OAuth connect, SaaS user system + Google sign-in, durable
multi-tenant storage, production onboarding frontend.

Do **not** build these unless the user explicitly asks this session:
- LINE Ads connector · LINE delivery · payment/billing · Google Sheets export
- Google Ads hardening beyond what onboarding/connect needs (basic connect is OK;
  deep keyword/field expansion is not)
- Any email path beyond the existing account-report SMTP flow

When a request is ambiguous about scope, ask before expanding surface area.

## Architecture map

```
src/
  main.py                  # daily sync entrypoint (Meta + Google); python -m src.main
  connectors/              # base.py, meta_ads.py, google_ads.py, line_ads.py (stub)
  transforms/              # normalize_meta/google/line → unified schema + derived metrics
  destinations/            # bigquery.py (raw/unified/logs), google_sheets.py (stub)
  ai/
    report_context.py      # builds metric context from BigQuery for the model
    report_generator.py    # assembles report; report_diagnostics.py adds WoW/MoM
    openai_client.py        prompt_templates.py  report_schedules.py
    generate_report.py     # single-report CLI
    send_account_reports.py # account-grouped batch send (deployed job entrypoint)
    send_report_email.py   report_log_status.py
  notifications/email_delivery.py   # SMTP HTML email
  web/                     # FastAPI app: sign-in, OAuth connect, dashboard; assets/
  sync/                    # daily_sync + historical backfill entrypoints (read DB)
  utils/                   # config_loader, date_utils, logger, secret_manager
sql/                       # create_tables, weekly/monthly_summary, looker_studio_views
deploy/                    # Cloud Run / Scheduler deploy + ops verification scripts
tests/                     # pytest, one file per module; fixtures in tests/fixtures
config/clients.yaml        # local, gitignored — real account config
docs/                      # spec, runbooks (deploy, AI report), Looker setup guide
```

Data layering rule: preserve full **raw API payloads**; keep `unified_ads_daily`
compact and cross-platform; put Meta/Google-only fields in platform-specific
raw/wide tables or views, never bloat the unified table. Field sets are
configurable by report preset — do not hardcode one giant API call.

## Commands

```bash
make check        # ruff + compileall + pytest — run before declaring done (CI runs the same)
make test         # pytest only
make lint         # ruff check + compileall
make format       # ruff check --fix (auto-fix lint issues)
make install-dev  # install runtime + dev deps (ruff) from requirements-dev.txt
make run          # python -m src.main  (calls real APIs + writes BigQuery)
```

Ruff config is in `pyproject.toml` (rules `E,F,W,I,UP,B,SIM`; `E501` line-length
deferred). Runtime deps are pinned in `requirements.txt`; dev tools in
`requirements-dev.txt`.

Local Meta-only sync smoke test (no marts refresh):
```bash
SYNC_ENABLED_PLATFORMS=meta_ads SYNC_START_DATE=YYYY-MM-DD SYNC_END_DATE=YYYY-MM-DD \
REFRESH_REPORTING_MARTS=false .venv/bin/python -m src.main
```

Cloud sync lifecycle: `make refresh-marts` (rebuild views), `make backfill`
(one-time history), `make daily-sync` (the daily job), `make daily-sync-deploy`
(Cloud Run Job + Scheduler). AI report ops: `make ai-report-{deploy-dry-run,status,ready,preflight,logs,verify,post-run}`.
The `ai-report-*`, `backfill`, `daily-sync*`, and `*-deploy` targets touch GCP,
real APIs, or BigQuery — treat as manual/opt-in, never run them unprompted.

Use the `.venv` interpreter (`.venv/bin/python`); the repo targets Python 3.11+.

## Working rules

1. Build on the existing foundation; inspect files before editing to avoid
   duplicate/conflicting logic. Keep changes small and reviewable.
2. Type hints on new functions. Keep connectors / transforms / destinations
   separate. Prefer simple readable code over clever abstractions.
3. Connectors: preserve raw payloads, never silently drop unknown fields, keep
   uncertain API field names configurable and mark assumptions in comments.
4. Add/update tests when changing logic. Derived-metric denominators that are 0
   return `None` (see normalize transforms).
5. Finish by summarizing: files changed, what was done, how to test, assumptions/
   limitations, recommended next step.

## AI report behavior (high-value, easy to regress)

Reports are in **Traditional Chinese**, useful to a media buyer, not just
descriptive. Group by platform; name specific campaigns/ad sets/ads/keywords;
tie advice to the campaign objective. Number formatting: `$` prefix on money,
thousands separators, CPC to 2 decimals, other money rounded whole, rates as
`%` to 2 decimals, ROAS to 2 decimals. WoW/MoM shows current + previous +
absolute movement, with previous totals computed from the **complete** prior
period. Output HTML email (not raw Markdown). Depth is product-controlled via
`AI_REPORT_DEPTH` (`brief`/`standard`/`deep`). See `AGENTS.md` "Product
reporting rules" for the full contract before touching report generation.

## Security (hard rules)

Never print, log, or commit tokens, API keys, client secrets, service-account
JSON, real ad account IDs, real customer IDs, recipient emails, `.env`, or
`config/clients.yaml`. Committed files use placeholders only (`.env.example`,
`config/clients.example.yaml`, fake fixtures). `secrets/`, `.env`, `.local/`,
and `config/clients.yaml` are gitignored and must stay that way. Onboarding/log
output redacts workspace/client/account/customer identifiers — preserve that.

## Git / PR workflow

User prefers: local feature branch → local test (`make check`) → push → PR →
review → merge to `main`. Do **not** commit directly to `main`, and do not push
or commit unless asked. Co-author line for commits:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
