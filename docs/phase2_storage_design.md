# Phase 2 — Durable multi-tenant storage (design)

Status: proposed (2026-06-05). This is the "design before building" step for the
storage layer that turns the local onboarding prototype into a real product where
a few friendly users can sign in and connect their own ad accounts.

## Plain-language summary

Right now the onboarding flow keeps everything in memory (or a local JSON file)
and forgets it when the server restarts. It also has **no concept of "who is
logged in"** and deliberately does **not** store ad-platform tokens. To let
friends sign in with Google and connect their Meta/Google ad accounts, we need a
real database that remembers:

1. **Users** — who signed in (via Google).
2. **Workspaces** — each user's account space (a user can later invite others).
3. **Connections** — which ad platforms/accounts they linked, plus the
   authorization token to pull their data (stored **encrypted**).
4. **Report schedules** — weekly/monthly + which day, per client/account.
5. **Logs** — sync and AI-report history (these already live in BigQuery; we keep
   them there and only reference them).

## Recommended approach

**Relational database (PostgreSQL family) via SQLAlchemy, with SQLite for local
dev and CI.** Reasons:

- The data is naturally relational (users → workspaces → connections → accounts →
  schedules), with lots of "list everything for this workspace" queries and
  uniqueness/foreign-key rules. SQL handles this cleanly; a document store would
  make us hand-roll that integrity.
- The team already thinks in SQL (BigQuery). Easier to reason about and hand off.
- Using **SQLAlchemy** keeps the engine swappable: **SQLite** for local dev and
  CI (no credentials, fast, fixes the same class of problem Phase 1 hit), and
  **Postgres** in production — same code, same models.
- OAuth tokens are stored **encrypted at rest** (app-level Fernet encryption; the
  key lives in Secret Manager, never in the DB or git).

This supersedes the earlier loose "Cloud SQL or Firestore" note: we go relational.

### Production database host — decision needed (not blocking)

Both options run the exact same Postgres code; this only matters at deploy time:

- **Cloud SQL (GCP-native)** — consistent with "stay in GCP", small fixed cost
  (~US$10–15/mo for the smallest instance), one less external vendor.
- **Serverless Postgres free tier (e.g. Neon/Supabase)** — US$0 to start, scales
  to zero when idle, but is an external service outside GCP.

For "a few friends" the serverless free tier is cheaper; Cloud SQL is tidier
long-term. I'll default to **Cloud SQL** unless you prefer to start at $0.

## Data model (first cut)

```
users                # id, google_sub (unique), email, name, created_at
workspaces           # id, name, owner_user_id, created_at
workspace_members    # workspace_id, user_id, role  (owner/member)
platform_connections # id, workspace_id, platform (meta_ads/google_ads),
                     #   external_account_id, account_name, status,
                     #   encrypted_token, token_expires_at, scopes, created_at
clients              # id, workspace_id, client_name  (report grouping)
client_accounts      # client_id, platform_connection_id, ad account binding
report_schedules     # id, client_id, report_type, delivery_day, timezone,
                     #   channel, email_to (encrypted), depth, enabled
```

Sync logs, unified ads data, and AI report logs stay in **BigQuery** as today;
this database only stores tenant/identity/connection/config state and references
BigQuery by `workspace_id` / `client_id` (which the BigQuery schema already has).

Multi-tenancy = every query is scoped by `workspace_id`. No per-customer dataset.

## How it slots into existing code

- Keep the existing `OnboardingStateStore` Protocol (`src/onboarding/state_store.py`)
  for prototype drafts/sync-jobs; add a new `src/storage/` package with the
  SQLAlchemy engine/session, ORM models, and a thin repository layer.
- `config_bridge` already turns selections into a `clients.yaml`-shaped artifact;
  the durable layer becomes the real source those selections are written to, with
  the YAML export remaining a compatibility path for the existing sync entrypoint.
- Migrations via **Alembic** so schema changes are versioned and reviewable.

## Build slices (small, reviewable PRs)

1. **Storage skeleton**: SQLAlchemy engine/session from `DATABASE_URL`
   (SQLite default), `users` + `workspaces` + `workspace_members` models,
   repository + tests on SQLite. Tables are created via `metadata.create_all`
   for now; **Alembic migrations are added with the Postgres/Cloud SQL deploy
   slice** to keep this first slice small. (No behavior change to onboarding yet.)
2. **Connections + token encryption**: `platform_connections` with Fernet
   encryption (key from `TOKEN_ENCRYPTION_KEY` / Secret Manager), repository, tests.
3. **Clients / accounts / schedules** tables + repository.
4. **Wire onboarding API** to read/write the durable store behind the existing
   HTTP contract; keep the YAML export as a compatibility bridge.
5. (Phase 3) Google sign-in + real OAuth connect write tokens into this store.

Each slice: green `make check`, then PR → CI → merge.

## Security notes

- Tokens and recipient emails are encrypted at rest; the encryption key is never
  committed and lives in Secret Manager.
- `DATABASE_URL` and the encryption key are env/secret only; `.env.example` gets
  placeholders. Local SQLite files (`*.db`) are gitignored.
- Existing redaction of workspace/client/account identifiers in logs is preserved.
