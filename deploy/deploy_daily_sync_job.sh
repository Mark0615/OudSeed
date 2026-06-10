#!/usr/bin/env bash
#
# Deploy the OudSeed automatic sync as Cloud Run Jobs, backed by the same Cloud
# SQL (PostgreSQL) the web app uses — so the job reads each workspace's selected
# accounts from the database and refreshes BigQuery on a schedule.
#
# It deploys TWO jobs from the same web image:
#   * oudseed-daily-sync  — runs `python -m src.sync.daily_sync`, triggered DAILY
#     by Cloud Scheduler. Re-pulls the last few days for every workspace's active
#     accounts, then refreshes the reporting views.
#   * oudseed-backfill    — runs `python -m src.sync.backfill`, NOT scheduled.
#     Run it ONCE by hand to pull full history (see the printed command). Writes
#     window-by-window and is idempotent, so re-running resumes safely.
#
# Prereqs (one-time, see docs/web_deployment_runbook.md):
#   * gcloud installed + authenticated (`gcloud auth login`).
#   * A Cloud SQL Postgres instance + database + user exist; DATABASE_URL in .env
#     points at it via the unix socket:
#       postgresql+psycopg://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
#   * CLOUD_SQL_INSTANCE = that connection name (PROJECT:REGION:INSTANCE).
#   * The accounts you want synced are already connected in that database (i.e.
#     you used the deployed web app, not the local SQLite one).
#   * .env has TOKEN_ENCRYPTION_KEY + the Google OAuth/Ads values filled in.
#
# Idempotent; never prints secret values. Shares the web app's runtime service
# account + secrets so there is one set to manage.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
REGION="${REGION:-asia-east1}"
SCHEDULER_REGION="${SCHEDULER_REGION:-asia-east1}"
REPOSITORY="${REPOSITORY:-ads-ai-pipeline}"
IMAGE_NAME="${IMAGE_NAME:-oudseed-web}"          # reuse the web image (has all code+deps)
DAILY_JOB_NAME="${DAILY_JOB_NAME:-oudseed-daily-sync}"
BACKFILL_JOB_NAME="${BACKFILL_JOB_NAME:-oudseed-backfill}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-daily-sync-trigger}"
SCHEDULE="${SCHEDULE:-0 5 * * *}"                # 05:00 daily
TIME_ZONE="${TIME_ZONE:-Asia/Taipei}"
DAILY_TASK_TIMEOUT="${DAILY_TASK_TIMEOUT:-1800s}"     # 30 min
BACKFILL_TASK_TIMEOUT="${BACKFILL_TASK_TIMEOUT:-7200s}"  # 2 h (re-run resumes if it hits this)
ENV_FILE="${ENV_FILE:-.env}"
# Shared with the web deploy so secrets/SA are not duplicated.
RUNTIME_SERVICE_ACCOUNT_NAME="${RUNTIME_SERVICE_ACCOUNT_NAME:-oudseed-web-runner}"
SKIP_BUILD="${SKIP_BUILD:-false}"               # set true to reuse the existing image

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-}"
if [[ -z "${CLOUD_SQL_INSTANCE}" ]]; then
  echo "Missing CLOUD_SQL_INSTANCE (PROJECT:REGION:INSTANCE). Set it in ${ENV_FILE}." >&2
  exit 1
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Missing DATABASE_URL. Set the Cloud SQL connection string in ${ENV_FILE}." >&2
  exit 1
fi
if [[ -z "${TOKEN_ENCRYPTION_KEY:-}" ]]; then
  echo "Missing TOKEN_ENCRYPTION_KEY (needed to decrypt stored ad tokens)." >&2
  exit 1
fi

# Sensitive -> Secret Manager (reuse the web app's secret names).
SECRET_KEYS=(
  TOKEN_ENCRYPTION_KEY
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_ADS_DEVELOPER_TOKEN
  DATABASE_URL
)
# Non-sensitive -> plain env vars (only those that are set).
ENV_KEYS=(
  GCP_PROJECT_ID
  BIGQUERY_DATASET
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_ADS_API_VERSION
  GOOGLE_ADS_LOGIN_CUSTOMER_ID
  DAILY_SYNC_LOOKBACK_DAYS
  BACKFILL_META_DAYS
  BACKFILL_GOOGLE_DAYS
  BACKFILL_WINDOW_DAYS
)

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:latest"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${DAILY_JOB_NAME}:run"

echo "Deploying sync jobs to project ${PROJECT_ID} (${REGION})."

gcloud config set project "${PROJECT_ID}" >/dev/null

gcloud services enable \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com

if ! gcloud artifacts repositories describe "${REPOSITORY}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="OudSeed images"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SERVICE_ACCOUNT}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SERVICE_ACCOUNT_NAME}" \
    --display-name="OudSeed Web Runner"
fi

for role in \
  roles/bigquery.jobUser \
  roles/bigquery.dataEditor \
  roles/secretmanager.secretAccessor \
  roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role="${role}" \
    --quiet >/dev/null
done

upsert_secret_from_stdin() {
  local secret_name="$1"
  if gcloud secrets describe "${secret_name}" >/dev/null 2>&1; then
    gcloud secrets versions add "${secret_name}" --data-file=- >/dev/null
  else
    gcloud secrets create "${secret_name}" --replication-policy=automatic --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
}

secret_name_for() {
  # SESSION_SECRET -> oudseed-web-session-secret (shared with the web deploy)
  local key="$1"
  echo "oudseed-web-$(echo "${key}" | tr '[:upper:]_' '[:lower:]-')"
}

SECRET_FLAGS=""
for key in "${SECRET_KEYS[@]}"; do
  value="${!key:-}"
  [[ -z "${value}" ]] && continue
  secret_name="$(secret_name_for "${key}")"
  printf "%s" "${value}" | upsert_secret_from_stdin "${secret_name}"
  SECRET_FLAGS="${SECRET_FLAGS:+${SECRET_FLAGS},}${key}=${secret_name}:latest"
done

ENV_FLAGS=""
for key in "${ENV_KEYS[@]}"; do
  value="${!key:-}"
  [[ -z "${value}" ]] && continue
  ENV_FLAGS="${ENV_FLAGS:+${ENV_FLAGS},}${key}=${value}"
done

if [[ "${SKIP_BUILD}" != "true" ]]; then
  gcloud builds submit \
    --config=deploy/cloudbuild.web.yaml \
    --substitutions="_IMAGE_URI=${IMAGE_URI}" \
    .
fi

deploy_job() {
  local job_name="$1" module="$2" timeout="$3"
  local args=(
    "${job_name}"
    --image="${IMAGE_URI}"
    --region="${REGION}"
    --service-account="${RUNTIME_SERVICE_ACCOUNT}"
    --command="python"
    --args="-m,${module}"
    --set-cloudsql-instances="${CLOUD_SQL_INSTANCE}"
    --tasks=1
    --max-retries=1
    --task-timeout="${timeout}"
    --cpu=1
    --memory=512Mi
  )
  [[ -n "${ENV_FLAGS}" ]] && args+=(--set-env-vars="${ENV_FLAGS}")
  [[ -n "${SECRET_FLAGS}" ]] && args+=(--set-secrets="${SECRET_FLAGS}")
  gcloud run jobs deploy "${args[@]}"
}

deploy_job "${DAILY_JOB_NAME}" "src.sync.daily_sync" "${DAILY_TASK_TIMEOUT}"
deploy_job "${BACKFILL_JOB_NAME}" "src.sync.backfill" "${BACKFILL_TASK_TIMEOUT}"

# Let the scheduler's service account invoke the daily job.
gcloud run jobs add-iam-policy-binding "${DAILY_JOB_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --quiet >/dev/null

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${SCHEDULER_REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
    --location="${SCHEDULER_REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${RUN_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${RUNTIME_SERVICE_ACCOUNT}"
else
  gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
    --location="${SCHEDULER_REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${RUN_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${RUNTIME_SERVICE_ACCOUNT}"
fi

echo
echo "Daily auto-sync job deployed:  ${DAILY_JOB_NAME}"
echo "Scheduled trigger:             ${SCHEDULER_JOB_NAME} (${SCHEDULE}, ${TIME_ZONE})"
echo "History backfill job deployed: ${BACKFILL_JOB_NAME} (not scheduled)"
echo
echo "Run the daily sync once now (optional):"
echo "  gcloud run jobs execute ${DAILY_JOB_NAME} --region ${REGION} --wait"
echo
echo "Run the one-time history backfill now (recommended once, can take a while):"
echo "  gcloud run jobs execute ${BACKFILL_JOB_NAME} --region ${REGION} --wait"
