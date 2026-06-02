# Connector Onboarding Handoff

This document maps the approved frontend connector prototype to the backend work
needed for a product-ready onboarding flow.

The current prototype lives in `frontend/prototype` and is intentionally static:
it simulates OAuth, account discovery, and destination selection without storing
tokens or touching real ad accounts.

## Product Flow

1. User chooses a data source, such as Meta Ads.
2. User grants platform access through the platform OAuth flow.
3. Backend exchanges the OAuth callback for a token and stores it securely.
4. Backend lists accessible ad accounts for that authorization.
5. User selects the ad accounts to sync.
6. User chooses destinations, such as Looker Studio, BigQuery, AI Report Email,
   or later Google Sheets.
7. Backend creates account connections, report schedules, and sync jobs.

## MVP Position

The current production backend is not yet a SaaS onboarding backend. It still
uses environment variables, Secret Manager, `config/clients.yaml`, Cloud Run
Jobs, and BigQuery views.

Therefore, the next implementation should not jump straight to full OAuth unless
we are ready to add user/workspace identity and encrypted token storage.

Recommended bridge:

- Keep the frontend connector flow as the user-facing target.
- Add a backend contract and mock API first.
- For the current internal MVP, convert approved account selections into
  managed client/account config entries.
- Keep real secrets in Secret Manager or local `.env`, never in frontend state.
- Keep Google Ads, LINE Ads, and Google Sheets visible but disabled until their
  backend paths are implemented.

## API Contract

These endpoints are the recommended shape for moving from prototype to product.
Names can change when the web framework is chosen.

The local prototype server implements this shape with safe mock data:

```bash
make onboarding-prototype
```

Local URL: `http://127.0.0.1:8765`

Real Meta account discovery is available as an explicit local opt-in:

```bash
make onboarding-prototype-real-meta
```

This uses `META_ACCESS_TOKEN` from local environment or `.env`, calls Meta
`/me/adaccounts`, and returns account metadata to the prototype. It does not
implement real OAuth, persist tokens, print tokens, or write `config/clients.yaml`.

The `Create connection` action creates a local in-memory draft and first-sync
job only. The response contains a sanitized config preview, destination handoff
metadata, an apply plan, and a prototype sync status object; it does not write
project config, Secret Manager, Cloud Run jobs, or Looker Studio assets.
Draft and sync-job state now goes through `src.onboarding.state_store` so the
prototype API contract can later swap in durable product storage without
rewriting the frontend flow. The current implementation remains process-local
and does not persist real account ids, recipients, tokens, or client config.

### List Connectors

```http
GET /api/connectors
```

Response:

```json
{
  "connectors": [
    {
      "id": "meta_ads",
      "name": "Meta Ads",
      "status": "available",
      "connected_account_count": 0
    },
    {
      "id": "google_ads",
      "name": "Google Ads",
      "status": "coming_soon",
      "connected_account_count": 0
    }
  ]
}
```

### Start OAuth

```http
POST /api/connectors/meta_ads/oauth/start
```

Request:

```json
{
  "workspace_id": "workspace_demo",
  "return_url": "https://app.example.com/connectors/meta_ads"
}
```

Response:

```json
{
  "authorization_url": "https://platform.example.com/oauth/authorize?...",
  "state": "opaque_csrf_state"
}
```

### OAuth Callback

```http
GET /api/connectors/meta_ads/oauth/callback?code=...&state=...
```

Backend responsibilities:

- Validate `state`.
- Exchange `code` for platform tokens.
- Store tokens encrypted or in Secret Manager.
- Store token metadata without exposing the token to the browser.
- Redirect the user back to the connector setup page.

### List Accessible Accounts

```http
GET /api/connectors/meta_ads/authorizations/{authorization_id}/accounts
```

Response:

```json
{
  "accounts": [
    {
      "external_account_id": "act_demo_1001",
      "name": "Demo Shop Taiwan",
      "currency": "TWD",
      "timezone": "Asia/Taipei",
      "status": "ready"
    }
  ]
}
```

### Create Account Connections

```http
POST /api/account-connections
```

Request:

```json
{
  "workspace_id": "workspace_demo",
  "connector_id": "meta_ads",
  "authorization_id": "auth_demo",
  "accounts": [
    {
      "external_account_id": "act_demo_1001",
      "account_name": "Demo Shop Taiwan"
    }
  ],
  "destinations": ["looker_studio", "ai_report_email", "bigquery"]
}
```

Response:

```json
{
  "draft_id": "draft_demo_0001",
  "connection_ids": ["conn_demo_1001"],
  "next_sync_status": "queued",
  "first_sync_job": {
    "sync_job_id": "sync_demo_0001",
    "status": "queued",
    "progress_percent": 10,
    "message": "First sync is queued."
  },
  "config_preview": {
    "summary": {
      "client_count": 1,
      "account_count": 1,
      "destinations": ["looker_studio", "ai_report_email"],
      "report_schedule_count": 1
    },
    "warnings": [],
    "yaml_text": "sanitized clients.yaml preview"
  },
  "destination_handoff": {
    "writes_config": false,
    "writes_secrets": false,
    "local_draft_only": true,
    "destinations": {
      "bigquery": {
        "status": "available",
        "project_id": "oudseed",
        "dataset": "ads_pipeline"
      },
      "looker_studio": {
        "status": "handoff_required",
        "handoff_type": "template_linking_url",
        "depends_on": ["bigquery"]
      },
      "ai_report_email": {
        "status": "config_preview_ready",
        "report_type": "monthly",
        "delivery_day": 1,
        "timezone": "Asia/Taipei",
        "depth": "standard"
      }
    }
  },
  "apply_plan": {
    "local_draft_only": true,
    "sensitive_payload_persisted": false,
    "writes_config": false,
    "writes_secrets": false
  }
}
```

### Inspect Local Draft

```http
GET /api/account-connections
GET /api/account-connections/{draft_id}
GET /api/account-connections/{draft_id}/apply-plan
```

`GET /api/account-connections` returns safe summaries of locally created
connections so the product UI can show which account groups and destinations are
set up after a page reload. The detail endpoints return only sanitized local
draft details for the prototype UI. They are intended to shape the later product
API. The local implementation uses an `OnboardingStateStore` boundary with an
in-memory store; durable product storage should implement the same
responsibilities while keeping sensitive account selections and token references
server-side.

For local product testing, `ONBOARDING_STATE_STORE_PATH` can point the prototype
at a JSON-backed store. The recommended path is `.local/onboarding_state.json`,
which is ignored by git because it may contain real ad account selections. This
only persists onboarding draft and sync-job state; platform tokens remain in
local environment variables or Secret Manager, and `config/clients.yaml` is not
written by the browser flow.

When `ONBOARDING_LOCAL_CONFIG_EXPORT_PATH` is set, an internal prototype endpoint
can export a draft's selected accounts into a local clients.yaml-compatible
artifact, such as `.local/clients.generated.yaml`. The endpoint returns only a
safe summary; the artifact itself is local and git-ignored because it may
contain real ad account IDs.
The local API also auto-exports this artifact during `POST /api/account-connections`
when the export path is configured, so the first-sync runner can use the current
selection without a separate manual export call.

Once that artifact exists, `make onboarding-sync-local-config` can run the Meta
sync using `CLIENTS_CONFIG_PATH=.local/clients.generated.yaml` and
`SYNC_ENABLED_PLATFORMS=meta_ads`. This is kept as an explicit local operations
command because it calls Meta and writes/replaces BigQuery rows.

For end-to-end local product testing, `make onboarding-prototype-live-sync`
starts the prototype with `ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true`. In that mode,
the second first-sync poll exports the selected draft into the local config
artifact, runs the Meta sync entrypoint, and returns only safe execution
metadata to the browser. This mode calls Meta and writes/replaces BigQuery rows,
so it remains opt-in.

### Inspect First Sync Status

```http
GET /api/sync-jobs/{sync_job_id}
```

The local prototype advances sync status from `queued` to `running` to
`completed` so the frontend can model a real first-sync experience. This is a
safe local state machine; it does not execute Cloud Run, call Meta Insights, or
write BigQuery.

When `ONBOARDING_USE_BIGQUERY_STATUS=true`, the completed sync job can include a
read-only backend data check. This reads the latest Meta sync log and
Looker-facing BigQuery view row counts scoped to the selected account IDs when
available, then returns only aggregate status and counts. It must not expose
account IDs, customer IDs, raw rows, or recipients.

### Send Report Email

```http
POST /api/sync-jobs/{sync_job_id}/report-email
```

In local real mode, completed sync jobs can send an AI report email through the
existing account-report pipeline. The backend uses the selected account IDs
internally, derives the report period from the latest verified sync when
available, generates/logs the AI report, and sends the HTML email through SMTP.
The response returns only delivery status, report id, report type, period, and
recipient configuration state. It must not return recipients, account IDs, raw
rows, tokens, or client secrets.

### Configure Report Schedule

```http
POST /api/report-schedules
```

Request:

```json
{
  "workspace_id": "workspace_demo",
  "account_group_name": "Demo Shop Taiwan",
  "report_type": "monthly",
  "delivery_day": 1,
  "delivery_time": "05:00",
  "timezone": "Asia/Taipei",
  "depth": "standard",
  "recipients": ["owner@example.com"]
}
```

## Data Model

The SaaS version should introduce first-class product tables instead of using
`clients.yaml` as the source of truth.

Suggested entities:

- `workspaces`: product customer/workspace boundary.
- `users`: login identity, later role-based access.
- `connector_authorizations`: one OAuth authorization per platform user or
  business identity.
- `connector_tokens`: encrypted token material or references to Secret Manager
  secret versions.
- `ad_account_connections`: selected ad accounts connected to a workspace.
- `destinations`: enabled output destinations per workspace/account group.
- `report_schedules`: cadence, delivery day, depth, timezone, recipients.
- `sync_jobs`: queued or scheduled sync state.
- `audit_events`: authorization, account selection, destination changes, token
  refresh failures, and disconnect actions.

## Current Backend Mapping

Until SaaS tables exist, the connector UI maps to existing backend concepts:

| UI Concept | Current Backend Equivalent |
|---|---|
| Meta Ads connector | `src.connectors.meta_ads` |
| Selected ad accounts | entries in `config/clients.yaml` or generated equivalent |
| Destination: BigQuery | existing BigQuery dataset and marts |
| Destination: Looker Studio | existing Looker Studio views |
| Destination: AI Report Email | `src.ai.send_account_reports` and report schedules |
| Destination: Google Sheets | disabled until Sheets export is productized |

The bridge can generate a sanitized client config object from the onboarding
selection, but it must not print or commit real account IDs, tokens, or
recipients.

## Security Requirements

- Never expose access tokens or refresh tokens to frontend JavaScript.
- Store platform tokens encrypted or in Secret Manager.
- Store only token references and metadata in product tables.
- Validate OAuth `state` and use a short-lived nonce.
- Keep platform scopes minimal and verify exact scopes against official platform
  docs before implementation.
- Provide disconnect/revoke behavior before opening OAuth to real customers.
- Add audit logs for account connection changes.
- Treat ad account IDs and customer recipients as sensitive operational data.

## Implementation Phases

### Phase 1: Prototype Contract

- Keep static UI. Completed in `frontend/prototype`.
- Add mock API response fixtures for connectors, accounts, and destinations.
  Completed in `frontend/prototype/mock-api.js`.
- Update UI to load from fixtures instead of hardcoded arrays. Completed in
  `frontend/prototype/app.js`.
- Confirm exact copy and flow.
- The prototype `Create connection` action now emits the same selection JSON
  shape that `src.onboarding.config_bridge` accepts.
- When `ai_report_email` is selected, the prototype includes user-controlled
  weekly/monthly `report_schedule` settings in that payload.

### Phase 2: Internal Config Bridge

- Add a local admin command that accepts selected connector/account/destination
  JSON and validates it. Completed in `src.onboarding.config_bridge`.
- Add a local API-shaped prototype server. Completed in
  `src.onboarding.api_server`.
- Add opt-in real Meta ad account discovery behind `ONBOARDING_USE_REAL_META`.
  Completed without storing tokens or changing client config.
- Generate a config preview compatible with the existing `clients.yaml` shape.
  Completed with sanitized placeholders.
- Create a local connection draft with destination handoff and apply-plan
  metadata. Completed in `src.onboarding.api_server` without writing config,
  secrets, Cloud Run, or Looker Studio assets.
- Add a state-store boundary for local drafts and first-sync jobs. Completed in
  `src.onboarding.state_store`; the default implementation is in-memory and
  thread-safe, with defensive copies to prevent accidental mutation leaks.
- Add a safe account-connections list endpoint for product UI reload/revisit
  flows. Completed in `src.onboarding.api_server`; it returns account counts,
  destination statuses, schedule metadata, and sync job ids without external ad
  account ids.
- Add an opt-in JSON-backed local state store for prototype restarts. Completed
  in `src.onboarding.state_store` and enabled with
  `ONBOARDING_STATE_STORE_PATH`; `.local/` remains git-ignored.
- Add an opt-in local clients.yaml-compatible export for selected account
  drafts. Completed in `src.onboarding.config_bridge` and
  `src.onboarding.api_server`; the API returns only safe metadata and writes
  the artifact only when `ONBOARDING_LOCAL_CONFIG_EXPORT_PATH` is configured.
- Add a local operations target for syncing from the generated onboarding
  config artifact. Completed as `make onboarding-sync-local-config`; running it
  is explicit because it writes selected-account data to BigQuery.
- Add an opt-in first-sync runner boundary for the prototype. Completed in
  `src.onboarding.sync_runner` and enabled only by
  `ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true`; default prototype sync remains
  simulated.
- Create a local first-sync job status after setup and poll it in the frontend
  so the user sees queued, running, and completed states.
- Add optional read-only backend data checks after completion so the prototype
  can show whether Meta sync data is visible in BigQuery and Looker-facing
  views without triggering writes from the browser flow.
- Add a user-facing `Send report email` action after completed first sync. It
  calls the existing AI report generation and HTML email delivery path, scoped
  to selected account IDs, without exposing recipients or account IDs in the UI.
- Keep draft/config diagnostics in collapsed developer details while showing
  users a simple setup-complete state focused on source, selected accounts,
  destination readiness, and first-sync status.
- Redact selected external ad account IDs from the prototype developer display.
- Do not write real `config/clients.yaml` automatically until reviewed.
  Current behavior only prints a preview.
- Add tests for validation and config generation. Covered by
  `tests/test_onboarding_config_bridge.py`.

Preview command:

```bash
.venv/bin/python -m src.onboarding.config_bridge \
  tests/fixtures/onboarding_selection_sample.json
```

Summary-only command:

```bash
.venv/bin/python -m src.onboarding.config_bridge \
  tests/fixtures/onboarding_selection_sample.json \
  --summary-only
```

API-shaped JSON command:

```bash
.venv/bin/python -m src.onboarding.config_bridge \
  tests/fixtures/onboarding_selection_sample.json \
  --json
```

### Phase 3: Real Meta OAuth

- Choose web app framework and hosting shape.
- Add user/workspace identity.
- Add OAuth start/callback endpoints.
- Add encrypted token storage.
- Add account discovery using the stored Meta authorization.
- Queue initial sync for selected accounts.

### Phase 4: Product Destinations

- Make Looker Studio and BigQuery available by default for connected accounts.
- Add AI Report Email schedule creation.
- Add Google Sheets only after Sheets export is productized.
- Add destination health checks and user-visible setup status.

## Acceptance Criteria For The Next PR

- The frontend prototype remains focused on connector onboarding.
- The backend handoff is documented with API contracts and current-backend
  mapping.
- No real OAuth, tokens, account IDs, recipients, `.env`, or `clients.yaml` are
  committed.
- Google Ads, LINE Ads, and Google Sheets remain visibly future-facing unless
  explicitly implemented.
