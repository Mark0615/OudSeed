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

To keep local connection drafts and first-sync state after restarting the
prototype server, run:

```bash
make onboarding-prototype-persistent
```

This writes onboarding state to `.local/onboarding_state.json` and enables local
config artifact export to `.local/clients.generated.yaml`. Both paths are
ignored by git because they may contain real ad account selections. It still
does not store platform tokens or write `config/clients.yaml`.

After the local artifact exists, this command runs a Meta sync from it:

```bash
make onboarding-sync-local-config
```

This calls Meta and writes/replaces BigQuery rows for the configured date range,
so keep it as an explicit local operations step.

Current prototype scope:

- Select an ad/data platform.
- Simulate OAuth authorization for Meta Ads.
- Select accessible ad accounts after authorization.
- Choose destinations such as Looker Studio, BigQuery, and AI Report Email.
- Configure weekly or monthly cadence when AI Report Email is selected.
- Keep Google Ads, Google Analytics 4, LINE Ads, Google Sheets, and other future destinations visible as disabled product roadmap items.
- Load connector, account, destination, and connection responses through
  `mock-api.js`, so the UI can later swap to real API calls with minimal
  component changes.
- Show the `Create connection` handoff payload in the same shape consumed by
  `src.onboarding.config_bridge`.
- Show a mock `config_preview` response shaped like
  `.venv/bin/python -m src.onboarding.config_bridge ... --json`.
- Show a user-facing completion state after setup, focused on connected source,
  selected accounts, destination readiness, and first-sync status.
- Create and poll a local first-sync job status so the UI shows queued,
  running, and completed states after setup.
- In real local mode, show a read-only backend data check after completion with
  aggregate BigQuery and dashboard-view status.
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
- Optionally run selected-account Meta sync from that artifact with
  `make onboarding-sync-local-config`.

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
