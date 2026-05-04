# AGENTS.md

You are working on the GitHub repository `Mark0615/OudSeed`.

Local development path:

```text
/Users/mark/Desktop/OudSeed
```

## Project context

This project is an ads data pipeline that syncs advertising data into BigQuery, then supports Looker Studio dashboards, Google Sheet export, and future AI-generated weekly/monthly reports.

Current MVP priority:

```text
Meta Ads → BigQuery → unified_ads_daily → Looker Studio
```

Future order:

```text
Google Ads → LINE Ads → AI weekly report → SaaS features
```

Read this file and `docs/ads_ai_pipeline_codex_development_spec.md` before making changes.

---

## Current implementation scope

Current target version: `v0.1`

Only implement work related to:

- Engineering governance files
- Project skeleton
- BigQuery schema
- Config loader
- Date utils
- BigQuery destination
- Base connector
- Meta Ads connector
- Meta Ads normalize
- Main Meta Ads sync flow
- Sync logs

Do not implement these unless explicitly requested:

- Google Ads connector
- LINE Ads connector
- OAuth login
- SaaS user system
- Payment
- Google Sheet export
- AI weekly/monthly reports
- Frontend dashboard
- Cloud Run deployment

---

## Working rules

1. Only implement the task explicitly requested by the user.
2. Do not implement future roadmap items unless explicitly requested.
3. Before editing, inspect existing code and docs to avoid duplicate or conflicting logic.
4. Build on top of the existing foundation instead of recreating files from scratch.
5. Keep changes small, modular, and easy to review.
6. Prefer simple, readable code over clever abstractions.
7. Use Python 3.11+.
8. Use type hints for new Python functions.
9. Add or update tests when changing logic.
10. Preserve raw API responses when implementing ad platform connectors.
11. Never silently drop unknown API fields.
12. If API field names are uncertain, keep them configurable and clearly mark assumptions.
13. Before finishing, summarize:
    - files changed
    - what was implemented
    - how to test it
    - assumptions or limitations
    - recommended next step

---

## Security rules

Never expose, print, log, or commit:

- API keys
- access tokens
- refresh tokens
- client secrets
- service account JSON
- real ad account IDs
- real customer IDs
- `.env`
- `config/clients.yaml`

Use placeholders only in committed files.

Allowed committed examples:

- `.env.example`
- `config/clients.example.yaml`
- fake sample fixtures

---

## BigQuery project

Use these project defaults when examples are needed:

| Item | Value |
|---|---|
| GCP project name | `oudseed` |
| GCP project id | `oudseed` |
| GCP project number | `252487346065` |
| BigQuery dataset | `ads_pipeline` |

Do not hardcode these values into reusable library functions. Prefer environment variables or config files.

---

## Testing expectations

When possible, run:

```bash
make check
```

If `make check` is not available yet, run:

```bash
python -m compileall src tests
pytest
```

If tests cannot be run, explain why and provide the exact command the user should run locally.

---

## Branch and PR expectations

The user prefers local testing before pushing to GitHub.

Recommended workflow:

```text
local feature branch → local test → push branch → open PR → review → merge to main
```

Do not assume direct commits to `main`.
