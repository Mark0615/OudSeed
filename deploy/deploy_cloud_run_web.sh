#!/usr/bin/env bash
#
# Deploy the OudSeed web app (FastAPI onboarding/dashboard) to Cloud Run as a
# public service, backed by Cloud SQL (PostgreSQL) for durable multi-tenant data.
#
# Prereqs (one-time, see docs/web_deployment_runbook.md):
#   * gcloud is installed and authenticated (`gcloud auth login`).
#   * A Postgres database exists and DATABASE_URL in .env points at it. Two ways:
#       - External Postgres (Neon/Supabase, free): leave CLOUD_SQL_INSTANCE empty,
#         DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require
#       - Cloud SQL: set CLOUD_SQL_INSTANCE=PROJECT:REGION:INSTANCE and
#         DATABASE_URL=postgresql+psycopg://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
#   * .env has the web app's OAuth/SMTP/OpenAI/session values filled in.
#
# This script is idempotent and never prints secret values. It does NOT create
# the Cloud SQL instance (that is a deliberate one-time manual step).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
REGION="${REGION:-asia-east1}"
REPOSITORY="${REPOSITORY:-ads-ai-pipeline}"
IMAGE_NAME="${IMAGE_NAME:-oudseed-web}"
SERVICE_NAME="${SERVICE_NAME:-oudseed-web}"
ENV_FILE="${ENV_FILE:-.env}"
RUNTIME_SERVICE_ACCOUNT_NAME="${RUNTIME_SERVICE_ACCOUNT_NAME:-oudseed-web-runner}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

# Cloud SQL connection name PROJECT:REGION:INSTANCE. Leave it EMPTY to use an
# external Postgres (e.g. Neon/Supabase) reached over the network via DATABASE_URL.
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-}"
USE_CLOUD_SQL=false
[[ -n "${CLOUD_SQL_INSTANCE}" ]] && USE_CLOUD_SQL=true
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Missing DATABASE_URL. Set your database connection string in ${ENV_FILE}." >&2
  exit 1
fi
if [[ "${USE_CLOUD_SQL}" == "true" ]]; then
  echo "Database: Cloud SQL (${CLOUD_SQL_INSTANCE})."
else
  echo "Database: external Postgres via DATABASE_URL (no Cloud SQL attached)."
fi

# Sensitive values -> Secret Manager (mounted as env vars at runtime).
SECRET_KEYS=(
  SESSION_SECRET
  TOKEN_ENCRYPTION_KEY
  GOOGLE_OAUTH_CLIENT_SECRET
  META_APP_SECRET
  GOOGLE_ADS_DEVELOPER_TOKEN
  OPENAI_API_KEY
  SMTP_PASSWORD
  DATABASE_URL
)

# Non-sensitive values -> plain Cloud Run env vars (only those that are set).
ENV_KEYS=(
  GCP_PROJECT_ID
  BIGQUERY_DATASET
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_REDIRECT_URI
  META_APP_ID
  META_OAUTH_REDIRECT_URI
  GOOGLE_ADS_OAUTH_REDIRECT_URI
  GOOGLE_ADS_API_VERSION
  GOOGLE_ADS_LOGIN_CUSTOMER_ID
  APP_BASE_URL
  SESSION_COOKIE_SECURE
  SMTP_HOST
  SMTP_PORT
  SMTP_USERNAME
  SMTP_FROM
  OPENAI_MODEL
  OPENAI_REASONING_EFFORT
  AI_REPORT_DEPTH
)

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:latest"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Deploying web service '${SERVICE_NAME}' to project ${PROJECT_ID} (${REGION})."

gcloud config set project "${PROJECT_ID}" >/dev/null

SERVICES=(
  artifactregistry.googleapis.com
  bigquery.googleapis.com
  cloudbuild.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
)
[[ "${USE_CLOUD_SQL}" == "true" ]] && SERVICES+=(sqladmin.googleapis.com)
gcloud services enable "${SERVICES[@]}"

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

# BigQuery (sync/preview/report) + Secret Manager (read secrets); Cloud SQL
# client role only when actually attaching a Cloud SQL instance.
ROLES=(
  roles/bigquery.jobUser
  roles/bigquery.dataEditor
  roles/secretmanager.secretAccessor
)
[[ "${USE_CLOUD_SQL}" == "true" ]] && ROLES+=(roles/cloudsql.client)
for role in "${ROLES[@]}"; do
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
  # SESSION_SECRET -> oudseed-web-session-secret
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

gcloud builds submit \
  --config=deploy/cloudbuild.web.yaml \
  --substitutions="_IMAGE_URI=${IMAGE_URI}" \
  .

DEPLOY_ARGS=(
  "${SERVICE_NAME}"
  --image="${IMAGE_URI}"
  --region="${REGION}"
  --service-account="${RUNTIME_SERVICE_ACCOUNT}"
  --platform=managed
  --allow-unauthenticated
  --port=8080
  --cpu=1
  --memory=512Mi
  --min-instances=0
  --max-instances=2
)
[[ "${USE_CLOUD_SQL}" == "true" ]] && DEPLOY_ARGS+=(--add-cloudsql-instances="${CLOUD_SQL_INSTANCE}")
[[ -n "${ENV_FLAGS}" ]] && DEPLOY_ARGS+=(--set-env-vars="${ENV_FLAGS}")
[[ -n "${SECRET_FLAGS}" ]] && DEPLOY_ARGS+=(--set-secrets="${SECRET_FLAGS}")

gcloud run deploy "${DEPLOY_ARGS[@]}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)')"
echo
echo "Web service deployed: ${SERVICE_URL}"
echo "Next: set APP_BASE_URL + the *_REDIRECT_URI vars in ${ENV_FILE} to this URL,"
echo "register those redirect URIs in the Google/Meta consoles, then re-run this script."
