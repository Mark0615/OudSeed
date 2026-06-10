# Web deployment runbook (Cloud Run + Cloud SQL)

How to put the OudSeed web app (sign-in → connect → onboarding dashboard) online
so a few friendly users can reach it by URL. This is the production counterpart
of running `make web` locally.

> **Cost note:** this adds a small always-available **Cloud SQL** instance
> (roughly US$8–25/month for the smallest tiers) plus pay-per-use Cloud Run
> (≈US$0 when idle). You can delete the Cloud SQL instance to stop the cost.

Architecture: `Browser → Cloud Run (oudseed-web) → Cloud SQL (Postgres) + BigQuery`.

---

## 0. Prerequisites (one-time)

- Install and authenticate the gcloud CLI: `gcloud auth login`.
- You already own GCP project `oudseed` (BigQuery + the daily sync job live here).
- Your local `.env` already has the Meta/Google/OpenAI/SMTP values you use for
  `make web`. Keep using that file — the deploy script reads it.

---

## 1. Create the database (one-time)

Cloud Run's filesystem is ephemeral, so the durable multi-tenant data lives in
Cloud SQL (Postgres). Create the smallest instance, a database, and a user:

```bash
# Smallest shared-core tier; pick a strong password.
gcloud sql instances create oudseed-db \
  --database-version=POSTGRES_16 \
  --tier=db-g1-small \
  --region=asia-east1

gcloud sql databases create oudseed --instance=oudseed-db
gcloud sql users create oudseed_app --instance=oudseed-db --password='CHOOSE-A-STRONG-PASSWORD'

# The connection name looks like: oudseed:asia-east1:oudseed-db
gcloud sql instances describe oudseed-db --format='value(connectionName)'
```

Then add these two lines to your `.env` (use the connection name from above):

```bash
CLOUD_SQL_INSTANCE=oudseed:asia-east1:oudseed-db
DATABASE_URL=postgresql+psycopg://oudseed_app:CHOOSE-A-STRONG-PASSWORD@/oudseed?host=/cloudsql/oudseed:asia-east1:oudseed-db
```

> The app creates its tables automatically on first boot — no migration step.

---

## 2. Set the production-only env values

Add/confirm these in `.env` (the deploy script routes secrets to Secret Manager
and the rest to Cloud Run env vars automatically):

```bash
GCP_PROJECT_ID=oudseed
BIGQUERY_DATASET=ads_pipeline
SESSION_COOKIE_SECURE=true            # HTTPS-only cookie in production
SESSION_SECRET=<run: python -c "import secrets;print(secrets.token_urlsafe(48))">
TOKEN_ENCRYPTION_KEY=<the SAME key you already use locally — do not regenerate>
```

> ⚠️ `TOKEN_ENCRYPTION_KEY` must match whatever encrypted the data you want to
> keep. For a fresh production DB you can generate a new one
> (`python -c "from src.storage.crypto import generate_key; print(generate_key())"`),
> but never change it after data exists or stored tokens become unreadable.

Leave `APP_BASE_URL` and the three `*_REDIRECT_URI` values as-is for now — you'll
set them in step 4 once you know the service URL.

---

## 3. First deploy

```bash
make web-deploy        # or: ./deploy/deploy_cloud_run_web.sh
```

The script builds the image, wires Secret Manager + Cloud SQL + IAM, deploys the
service, and prints the public URL, e.g. `https://oudseed-web-xxxx.a.run.app`.

---

## 4. Point OAuth at the real URL (two-pass)

OAuth needs the redirect URLs to match the live host. Using the URL from step 3:

1. Put these in `.env` (replace the host):

   ```bash
   APP_BASE_URL=https://oudseed-web-xxxx.a.run.app
   GOOGLE_OAUTH_REDIRECT_URI=https://oudseed-web-xxxx.a.run.app/oauth/google/callback
   META_OAUTH_REDIRECT_URI=https://oudseed-web-xxxx.a.run.app/oauth/meta/callback
   GOOGLE_ADS_OAUTH_REDIRECT_URI=https://oudseed-web-xxxx.a.run.app/oauth/google-ads/callback
   ```

2. Register those exact URLs in the consoles:
   - **Google Auth Platform** → your OAuth client → *Authorized redirect URIs*
     (add the Google sign-in **and** Google Ads callback URLs).
   - **Meta App** → Facebook Login → *Valid OAuth Redirect URIs* (add the Meta one).

3. Redeploy so the service picks up the new values:

   ```bash
   make web-deploy
   ```

Now open `APP_BASE_URL` and run through sign-in → connect → first sync.

---

## 5. Let friends in (dev-mode apps)

While the Meta/Google apps are unverified (dev/test mode), only allow-listed
people can connect their ad accounts:

- **Meta:** App → *Roles* → add each friend as a **Tester** (they must accept).
- **Google:** OAuth consent screen → *Test users* → add each friend's email.

Your own accounts already work without this.

---

## 6. Verify & operate

```bash
# Health check (should return {"status":"ok"})
curl -s "$APP_BASE_URL/healthz"

# Logs
gcloud run services logs read oudseed-web --region=asia-east1 --limit=50

# Roll back to the previous revision if a deploy goes wrong
gcloud run services update-traffic oudseed-web --region=asia-east1 --to-revisions=PREVIOUS=100
```

To stop all cost: delete the Cloud Run service and the Cloud SQL instance
(`gcloud run services delete oudseed-web` / `gcloud sql instances delete oudseed-db`).

---

## 7. Automatic daily sync + one-time history backfill

This makes the accounts you selected in the dashboard refresh **automatically
every day**, with no button-clicking — and lets you pull full history once.

> **Depends on the cloud DB.** These jobs read your selected accounts from Cloud
> SQL, so they only work after the web app (steps 1–6) is deployed and you have
> connected/selected accounts in the **deployed** app (not the local SQLite one).
> They reuse the web app's runtime service account + secrets.

```bash
# .env must still have CLOUD_SQL_INSTANCE, DATABASE_URL, TOKEN_ENCRYPTION_KEY and
# the Google OAuth/Ads values (same file you used for the web deploy).
make daily-sync-deploy
```

This deploys two Cloud Run Jobs from the web image and a daily trigger:

- **`oudseed-daily-sync`** — runs every day at 05:00 Asia/Taipei (override with
  `SCHEDULE=...`). Re-pulls the last few days (`DAILY_SYNC_LOOKBACK_DAYS`,
  default 3) for every workspace's active accounts, then refreshes the views.
- **`oudseed-backfill`** — **not** scheduled. Run it **once** to pull full
  history (Meta ~36 months / Google ~36 months; the Meta API can't go past ~37
  months — a platform limit). It writes window-by-window and is idempotent, so
  re-running just resumes.

```bash
# Optional: run the daily sync immediately to confirm it works.
gcloud run jobs execute oudseed-daily-sync --region=asia-east1 --wait

# Recommended once: pull full history (can take a while; safe to re-run).
gcloud run jobs execute oudseed-backfill --region=asia-east1 --wait

# Logs for either job
gcloud run jobs executions list --job=oudseed-daily-sync --region=asia-east1 --limit=5
```

Cost: a daily run is a few minutes of a small container + one Cloud Scheduler
job — typically a few NT$/month. To stop it: `gcloud scheduler jobs delete
oudseed-daily-sync-trigger --location=asia-east1`.

### Cheaper alternative (single user, no always-on cloud)

If it's just you and you don't want a cloud DB running 24/7, skip the jobs above
and run the sync **locally on a schedule** instead (uses your local SQLite DB):

```bash
# Runs once; point cron/launchd at it daily. No cloud cost.
cd /path/to/OudSeed && make daily-sync
```

---

## What this does **not** do yet

- **Automatic scheduled report sending** — reports are sent on demand from the
  dashboard ("寄送測試報告"). A per-workspace Cloud Scheduler trigger is the next
  step.
- **App Review / public access** — still dev-mode OAuth, so friends must be added
  as testers (step 5).
- **DB migrations** — tables are created on boot (`create_all`); schema changes
  will need a migration tool once there's data you can't recreate.
