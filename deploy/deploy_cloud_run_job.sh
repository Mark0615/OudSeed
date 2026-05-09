#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
PROJECT_NUMBER="${PROJECT_NUMBER:-252487346065}"
REGION="${REGION:-asia-east1}"
SCHEDULER_REGION="${SCHEDULER_REGION:-asia-east1}"
REPOSITORY="${REPOSITORY:-ads-ai-pipeline}"
IMAGE_NAME="${IMAGE_NAME:-oudseed-meta-ads-sync}"
JOB_NAME="${JOB_NAME:-oudseed-meta-ads-sync}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-meta-ads-sync-daily}"
SCHEDULE="${SCHEDULE:-0 4 * * *}"
TIME_ZONE="${TIME_ZONE:-Asia/Taipei}"
BIGQUERY_DATASET="${BIGQUERY_DATASET:-ads_pipeline}"
ENV_FILE="${ENV_FILE:-.env}"
CLIENTS_CONFIG_FILE="${CLIENTS_CONFIG_FILE:-config/clients.yaml}"
RUNTIME_SERVICE_ACCOUNT_NAME="${RUNTIME_SERVICE_ACCOUNT_NAME:-oudseed-ads-pipeline-runner}"
META_TOKEN_SECRET_NAME="${META_TOKEN_SECRET_NAME:-oudseed-meta-access-token}"
CLIENTS_CONFIG_SECRET_NAME="${CLIENTS_CONFIG_SECRET_NAME:-oudseed-clients-yaml}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -z "${META_ACCESS_TOKEN:-}" ]]; then
  echo "Missing META_ACCESS_TOKEN. Set it in ${ENV_FILE} or the environment." >&2
  exit 1
fi

if [[ ! -f "${CLIENTS_CONFIG_FILE}" ]]; then
  echo "Missing ${CLIENTS_CONFIG_FILE}. Create it from config/clients.example.yaml." >&2
  exit 1
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:latest"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

echo "Using project ${PROJECT_ID}, region ${REGION}, job ${JOB_NAME}."

gcloud config set project "${PROJECT_ID}" >/dev/null

gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com

if ! gcloud artifacts repositories describe "${REPOSITORY}" \
  --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="OudSeed ads pipeline images"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SERVICE_ACCOUNT}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SERVICE_ACCOUNT_NAME}" \
    --display-name="OudSeed Ads Pipeline Runner"
fi

for role in roles/bigquery.jobUser roles/bigquery.dataEditor; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role="${role}" \
    --quiet >/dev/null
done

upsert_secret_from_stdin() {
  local secret_name="$1"
  if gcloud secrets describe "${secret_name}" >/dev/null 2>&1; then
    gcloud secrets versions add "${secret_name}" --data-file=-
  else
    gcloud secrets create "${secret_name}" --replication-policy=automatic --data-file=-
  fi
}

printf "%s" "${META_ACCESS_TOKEN}" | upsert_secret_from_stdin "${META_TOKEN_SECRET_NAME}" >/dev/null
upsert_secret_from_stdin "${CLIENTS_CONFIG_SECRET_NAME}" < "${CLIENTS_CONFIG_FILE}" >/dev/null

for secret_name in "${META_TOKEN_SECRET_NAME}" "${CLIENTS_CONFIG_SECRET_NAME}"; do
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
done

gcloud builds submit \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_IMAGE_URI=${IMAGE_URI}" \
  .

gcloud run jobs deploy "${JOB_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --service-account="${RUNTIME_SERVICE_ACCOUNT}" \
  --tasks=1 \
  --max-retries=1 \
  --task-timeout=900s \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},BIGQUERY_DATASET=${BIGQUERY_DATASET}" \
  --set-secrets="META_ACCESS_TOKEN=${META_TOKEN_SECRET_NAME}:latest,CLIENTS_CONFIG_YAML=${CLIENTS_CONFIG_SECRET_NAME}:latest"

gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --quiet >/dev/null

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
  --location="${SCHEDULER_REGION}" >/dev/null 2>&1; then
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

echo "Cloud Run Job deployed: ${JOB_NAME}"
echo "Cloud Scheduler trigger configured: ${SCHEDULER_JOB_NAME} (${SCHEDULE}, ${TIME_ZONE})"
echo "Run manually with:"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"
