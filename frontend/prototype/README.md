# OudSeed Connector Prototype

Static click-through prototype for the user-facing data connector flow.

Open `index.html` directly in a browser. No build step, backend, OAuth app, or API keys are required.

For the fuller local product slice, run:

```bash
make onboarding-prototype
```

Then open `http://127.0.0.1:8765`. This serves the same UI plus local `/api/*`
endpoints backed by `src.onboarding.api_server` and `src.onboarding.config_bridge`.

To test real Meta ad account discovery with your local `.env` token:

```bash
make onboarding-prototype-real-meta
```

This reads `META_ACCESS_TOKEN` locally and calls Meta's `/me/adaccounts` endpoint
after the prototype authorization step. It does not store tokens, print tokens,
or write `config/clients.yaml`.

To test real Google Ads customer discovery with local Google Ads credentials:

```bash
make onboarding-prototype-real-google
```

This reads local Google Ads environment credentials, lists accessible customers
after the prototype authorization step, and returns only local account aliases
to the browser. Finishing setup can export the selected real customer IDs to
the ignored `.local/clients.generated.yaml` artifact, but this target keeps live
sync execution disabled.

To keep local connection drafts and first-sync state after restarting the
prototype server, run:

```bash
make onboarding-prototype-persistent
```

This writes onboarding state to `.local/onboarding_state.json` and enables local
config artifact export to `.local/clients.generated.yaml`. Both paths are
ignored by git because they may contain real ad account selections. It still
does not store platform tokens or write `config/clients.yaml`.
When the export path is configured, finishing setup auto-exports the local
artifact for the selected accounts. The artifact is rebuilt from all local
connection drafts, so you can finish a Meta setup and then a Google Ads setup;
when both use the same report/client name, they are merged into one client in
`.local/clients.generated.yaml`.

For the same persistent prototype flow focused on Google Ads readiness, run:

```bash
make onboarding-prototype-google-persistent
```

This sets the Google Ads readiness platform and keeps live sync execution
disabled. Finishing setup can generate `.local/clients.generated.yaml` for the
selected Google Ads accounts, then `make onboarding-google-live-sync-ready` can
verify the safe gate before any write path is confirmed.

After the local artifact exists, this command runs a Meta sync from it:

```bash
make onboarding-sync-local-config
```

This calls Meta and writes/replaces BigQuery rows for the configured date range,
so keep it as an explicit local operations step.

Before running the write path, check readiness safely:

```bash
make onboarding-live-sync-ready
```

This verifies the local config artifact and required environment settings
without calling Meta, querying BigQuery, writing BigQuery, printing tokens, or
showing real ad account IDs.

For Google Ads preview selections, use the Google-specific safe gate:

```bash
make onboarding-google-live-sync-ready
```

This validates local Google Ads customer config and required credentials without
calling Google Ads or writing BigQuery.

After Google readiness passes and the write path is confirmed, run:

```bash
make onboarding-google-sync-local-config
```

This calls Google Ads and writes/replaces BigQuery rows for the selected local
config artifact.

For an end-to-end local run where the prototype first-sync polling flow runs the
Meta sync automatically, use:

```bash
make onboarding-prototype-live-sync
```

This is opt-in because it calls Meta and writes/replaces BigQuery rows. The
browser receives only safe execution metadata, not sync logs or account IDs.
The runner enforces the same readiness gate as `make onboarding-live-sync-ready`
before it starts the subprocess.

For the same prototype polling flow with Google Ads selected, use:

```bash
make onboarding-prototype-google-live-sync
```

This sets `ONBOARDING_LIVE_SYNC_PLATFORM=google_ads` so the first-sync runner
exports the selected Google Ads customers, enforces the Google readiness gate,
then runs the Google Ads sync subprocess only after readiness passes.

Current prototype scope:

- Select an ad/data platform.
- Simulate OAuth authorization for Meta Ads.
- Select accessible ad accounts after authorization.
- Choose destinations such as Looker Studio, BigQuery, and AI Report Email.
- Configure weekly or monthly cadence when AI Report Email is selected.
- Keep Google Ads available as the next preview onboarding path while Google
  Analytics 4, LINE Ads, Google Sheets, and other future destinations remain
  visible as disabled product roadmap items.
- Load connector, account, destination, and connection responses through
  `mock-api.js`, so the UI can later swap to real API calls with minimal
  component changes.
- Show the `Create connection` handoff payload in the same shape consumed by
  `src.onboarding.config_bridge`.
- Show a mock `config_preview` response shaped like
  `.venv/bin/python -m src.onboarding.config_bridge ... --json`.
- Let users rename selected accounts with safe client/report names before
  finishing setup. The edited names feed the handoff payload and report grouping,
  while platform account IDs remain hidden.
- Show connected setups by the safe account group name plus account count and
  outputs, not by platform account identifiers.
- Let users choose the initial import range, currently 7, 14, 30, or 90 days.
  The selected range feeds `initial_sync.sync_days_back` and the generated local
  clients config default.
- Show a user-facing completion state after setup, focused on connected source,
  selected accounts, output readiness, report schedule, and whether recent
  performance data is available.
- Create and poll a local first-sync job status so the UI shows queued,
  running, and completed states after setup.
- In real local mode, use the read-only backend data check to power the
  user-facing data availability preview. Aggregate BigQuery and dashboard-view
  status stays in collapsed developer details.
- After first sync completes, show `Send report email` for AI Report Email
  connections. In real local mode this calls the existing AI report + SMTP HTML
  email pipeline and returns only safe delivery metadata.
- Keep the local connection draft, destination handoff, and sanitized config
  preview available only inside collapsed developer details. This remains
  preview-only and does not write config, secrets, Cloud Run jobs, or Looker
  Studio assets.
- Redact external ad account IDs from the displayed handoff payload.
- Optionally list real Meta ad accounts through local API mode when
  `ONBOARDING_USE_REAL_META=true`.
- Optionally persist local connection and first-sync state with
  `ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json`.
- Optionally export selected account drafts to a local clients.yaml-compatible
  artifact with `ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml`.
- Optionally run Google Ads persistent readiness mode with
  `make onboarding-prototype-google-persistent`.
- Optionally run selected-account Meta sync from that artifact with
  `make onboarding-sync-local-config`.
- Optionally enable live first-sync execution in the prototype with
  `make onboarding-prototype-live-sync`.
- Optionally enable Google Ads live first-sync execution in the prototype with
  `make onboarding-prototype-google-live-sync`.

This prototype intentionally does not implement real OAuth, token storage, user login, or SaaS account management.

Backend handoff notes are tracked in `../../docs/connector_onboarding_handoff.md`.

The backend preview bridge can be tested with:

```bash
.venv/bin/python -m src.onboarding.config_bridge \
  tests/fixtures/onboarding_selection_sample.json
```

API-shaped JSON preview:

```bash
.venv/bin/python -m src.onboarding.config_bridge \
  tests/fixtures/onboarding_selection_sample.json \
  --json
```
