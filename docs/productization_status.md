# OudSeed Productization Status

This note tracks the current product-shaped MVP state for account-grouped AI
reports. It should stay operational and avoid secrets, real account IDs, or raw
recipient values.

## Current State

- Main deployed report job: `oudseed-account-ai-report`
- Region: `asia-east1`
- Scheduler job: `oudseed-account-ai-report-monthly`
- Scheduler cadence: `0 5 1 * *`, `Asia/Taipei`
- Runtime module: `src.ai.send_account_reports`
- OpenAI model: `gpt-5.2`
- Account-report defaults: `OPENAI_TIMEOUT_SECONDS=180`,
  `OPENAI_MAX_OUTPUT_TOKENS=5000`, `JOB_MAX_RETRIES=0`
- Schedule id: `monthly_email_default`
- Delivery: HTML email, one email per account group

## Operational Commands

Preview deployment settings without touching GCP:

```bash
make ai-report-deploy-dry-run
```

Check deployed Cloud Run and Scheduler status:

```bash
make ai-report-status
```

Run strict readiness checks before a scheduled send:

```bash
make ai-report-ready
```

Run safe preflight without sending email:

```bash
make ai-report-preflight
```

Verify a specific send batch:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
make ai-report-verify
```

Verify only post-run report logs after a scheduled send:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-05-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z \
make ai-report-post-run
```

Run a narrow local Meta-only sync smoke test:

```bash
SYNC_ENABLED_PLATFORMS=meta_ads \
SYNC_START_DATE=2026-05-30 \
SYNC_END_DATE=2026-05-30 \
REFRESH_REPORTING_MARTS=false \
.venv/bin/python -m src.main
```

`SYNC_ENABLED_PLATFORMS` is intended for one-off operational tests when local
config has more than one enabled platform. Runtime progress logs redact
workspace, client, account, and customer identifiers.

## Next Scheduled Monthly Run

The configured monthly scheduler fires at `2026-06-01 05:00:00 Asia/Taipei`,
which is `2026-05-31T21:00:00Z`. It should generate the May 2026 monthly report
period:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-05-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z \
make ai-report-post-run
```

Expected healthy post-run values:

- `expected_group_count=2`
- `successful_group_count=2`
- `failed_log_count=0`
- `delivery_failure_count=0`
- `unconfirmed_group_count=0`

## Expected Healthy State

- `account_report_ready=true`
- `ready=True`
- `max_retries=0`
- `openai_model=gpt-5.2`
- `openai_timeout_seconds=180`
- `openai_max_output_tokens=5000`
- `preflight_enabled=false`
- `schedule_id_configured=true`
- `recipient_configured=true`
- `openai_secret_configured=true`
- `clients_config_secret_configured=true`
- `smtp_password_secret_configured=true`
- `scheduler_state=ENABLED`

## Reporting Observability

`vw_looker_ai_report_logs` exposes operational fields for Looker Studio:

- `account_group_name`
- `status`
- `is_email_delivery_failure`
- `has_report_text`
- `report_text_chars`

Use `make ai-report-logs` or `make ai-report-verify` for routine checks. Use
`AI_REPORT_LOG_CREATED_AFTER` when a reporting period has older test runs.

## Current Limitations

- `ai_report_logs` does not yet store `account_group_name` as a first-class
  column; the current view infers it from report context.
- `make ai-report-ready` depends on local `gcloud` responsiveness and exits
  non-zero if GCP reads time out.
- Scheduler success after the next real run still needs post-run verification
  with `AI_REPORT_LOG_CREATED_AFTER` set to the batch start time.
- LINE delivery, SaaS users, OAuth, and payment remain out of MVP scope.

## Frontend Prototype Direction

The approved frontend direction is a connector onboarding wizard, not an
internal AI report operations dashboard:

- choose an ad/data platform;
- grant platform authorization;
- select accessible ad accounts;
- choose destinations such as Looker Studio, BigQuery, and AI Report Email.

The static prototype is in `frontend/prototype`. The backend handoff contract is
tracked in `docs/connector_onboarding_handoff.md`.

Prototype data now flows through `frontend/prototype/mock-api.js`, which mirrors
the intended connector/account/destination API shape while staying fully static.

The internal config bridge is available through `src.onboarding.config_bridge`.
It accepts onboarding selection JSON and prints a sanitized
`clients.yaml`-compatible preview without writing `config/clients.yaml`.

The local onboarding API now creates an in-memory connection draft after the
user selects Meta or Google Ads preview accounts and destinations. The draft
includes destination handoff metadata for BigQuery, Looker Studio, and AI Report
Email plus an apply plan for promoting the selection into managed config. It is
intentionally non-durable and reports `writes_config=false` and
`writes_secrets=false`.
The frontend presents this as a user-facing setup-complete state; draft/config
details are kept in a collapsed developer details section for debugging.

Onboarding draft and first-sync job state now sits behind
`src.onboarding.state_store`. The default store remains process-local and
in-memory for safety, but the API no longer depends directly on internal dicts.
This is the intended boundary for replacing local prototype state with a durable
workspace/account connection store later.

The local API also exposes `GET /api/account-connections` as a safe list view
for created connections. It returns safe account group names, account counts,
enabled destinations, destination statuses, report schedule metadata, initial
import range metadata, and first-sync job ids, but not external ad account ids,
recipients, tokens, or raw selections.

For longer local product tests, the prototype can persist draft/sync-job state
with:

```bash
make onboarding-prototype-persistent
```

This sets `ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json`. The
`.local/` directory is ignored by git because the JSON state can contain real ad
account selections. It does not persist platform tokens or write
`config/clients.yaml`.

The persistent prototype target also sets
`ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml`. That enables
an internal local export endpoint for turning an onboarding draft into a
clients.yaml-compatible artifact. The API response is safe metadata only; the
generated local file is ignored by git and may contain real ad account IDs.
When this path is configured, `POST /api/account-connections` also auto-exports
the artifact so the current selected accounts are ready for first-sync execution.
The export now rebuilds the artifact from all locally stored connection drafts,
not only the latest setup. Drafts with the same safe client/report name are
merged into one client entry, so a Meta setup and a Google Ads setup can feed
the same account-grouped report when they use the same client name. Different
client names remain separate client entries. The API response still returns
only safe aggregate metadata; the ignored artifact may contain real platform
account IDs.
The onboarding selection can carry `initial_sync.sync_days_back`, currently
driven by the prototype's 7/14/30/90 day initial import setting. The generated
local artifact writes that value into `defaults.sync_days_back`, so the manual
first-sync command uses the selected backfill window without extra flags.

For Google Ads onboarding without automatically running the write path, use:

```bash
make onboarding-prototype-google-persistent
```

This enables the same persistent state and local config export path, sets the
readiness platform to Google Ads, and keeps first-sync execution disabled. It is
the safe local flow for generating a Google `.local/clients.generated.yaml`
artifact before running `make onboarding-google-live-sync-ready`.

After a local config artifact exists, a selected-account Meta sync can be run
from that artifact with:

```bash
make onboarding-sync-local-config
```

This runs `src.main` with `CLIENTS_CONFIG_PATH=.local/clients.generated.yaml`
and `SYNC_ENABLED_PLATFORMS=meta_ads`. It is intentionally a manual command
because it calls Meta and writes/replaces rows in BigQuery for the configured
date range.

Google Ads can now be previewed through the same onboarding selection and local
config export bridge. Google live sync remains a separate gated step because it
requires Google Ads API credentials and customer access validation.

Before running that write path, use the safe readiness check:

```bash
make onboarding-live-sync-ready
```

This inspects the ignored local config artifact, required environment toggles,
Meta token presence, and BigQuery project/dataset configuration. It does not
call Meta, query BigQuery, write BigQuery, print tokens, or return real ad
account IDs. The output includes `writes_bigquery=true` as an explicit reminder
that the next live sync step will write/replace BigQuery rows.

Google Ads preview onboarding has its own safe readiness gate:

```bash
make onboarding-google-live-sync-ready
```

This inspects the ignored local config artifact for enabled Google Ads
customers, required Google Ads environment credentials, the platform filter, and
BigQuery project/dataset configuration. It does not call Google Ads, query
BigQuery, write BigQuery, print credentials, or return real customer IDs.

After Google Ads readiness passes and the user confirms the write path, run:

```bash
make onboarding-google-sync-local-config
```

This runs `src.main` with `CLIENTS_CONFIG_PATH=.local/clients.generated.yaml`
and `SYNC_ENABLED_PLATFORMS=google_ads`. It calls Google Ads and writes/replaces
BigQuery rows for the configured date range, so it remains a manual operation.

For an end-to-end local prototype where first sync is triggered by the onboarding
polling flow, run:

```bash
make onboarding-prototype-live-sync
```

This enables `ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true`. The runner exports the
selected draft to `.local/clients.generated.yaml`, runs the Meta sync entrypoint,
and returns only safe execution metadata to the browser. This mode is opt-in
because it writes/replaces BigQuery rows. Before the subprocess starts, the
runner now enforces the same safe readiness checks used by
`make onboarding-live-sync-ready`; if required local config, Meta token, or
BigQuery settings are missing, it stops before calling Meta or writing BigQuery.

Google Ads can use the same local prototype first-sync polling flow with:

```bash
make onboarding-prototype-google-live-sync
```

This sets `ONBOARDING_LIVE_SYNC_PLATFORM=google_ads`, exports the selected
Google Ads customers to the ignored local artifact, enforces the Google-specific
readiness gate, and only then runs the Google Ads sync subprocess. It calls
Google Ads and writes/replaces BigQuery rows after readiness passes, so it
remains an opt-in write path.

The prototype also creates a local first-sync job status and polls it from the
frontend. This models the product experience of queued, running, and completed
sync states without automatically executing Cloud Run or writing BigQuery from
the browser flow.

When started through `make onboarding-prototype-real-meta`, the local prototype
also enables a read-only BigQuery backend data check. After first sync reaches
completed, the UI can show the latest aggregate Meta sync status plus BigQuery
and Looker-facing view row counts scoped to the selected accounts. This status
check does not print or return real account IDs.

Completed first-sync jobs can now send an AI report email from the prototype.
The endpoint uses the existing account-grouped AI report generator and SMTP HTML
email delivery path, scoped to selected account IDs. The browser receives only
safe delivery metadata and never sees the configured recipient or real account
IDs.

Run the fuller local onboarding product slice with:

```bash
make onboarding-prototype
```

This serves `frontend/prototype` and safe local `/api/*` endpoints backed by the
config bridge.

Real Meta ad account discovery can be tested locally with:

```bash
make onboarding-prototype-real-meta
```

This uses `META_ACCESS_TOKEN` from local `.env` only when explicitly enabled.
It does not change deployed Cloud Run jobs, Secret Manager, or `config/clients.yaml`.

Real Google Ads customer discovery can be tested locally with:

```bash
make onboarding-prototype-real-google
```

This uses local Google Ads environment credentials only when explicitly enabled.
It lists accessible Google Ads customers through the prototype flow, returns
only local aliases to the browser, and can export the selected real customer IDs
to the ignored `.local/clients.generated.yaml` artifact. It keeps live sync
execution disabled; run `make onboarding-google-live-sync-ready` before any
confirmed Google Ads write path.
