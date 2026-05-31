#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
REGION="${REGION:-asia-east1}"
JOB_NAME="${JOB_NAME:-oudseed-account-ai-report}"
LOG_LIMIT="${LOG_LIMIT:-30}"

cleanup() {
  gcloud run jobs update "${JOB_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --remove-env-vars=AI_REPORT_PREFLIGHT >/dev/null
}

trap cleanup EXIT

echo "Enabling account-report preflight for ${JOB_NAME}."
gcloud run jobs update "${JOB_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars=AI_REPORT_PREFLIGHT=true >/dev/null

echo "Executing ${JOB_NAME} in preflight mode."
execution_output="$(
  gcloud run jobs execute "${JOB_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --wait 2>&1
)"
printf "%s\n" "${execution_output}"

execution_name="$(
  printf "%s\n" "${execution_output}" \
    | sed -n 's/.*Execution \[\([^]]*\)\].*/\1/p' \
    | tail -n 1
)"

if [[ -z "${execution_name}" ]]; then
  echo "Could not determine Cloud Run execution name from gcloud output." >&2
  exit 1
fi

echo "Preflight logs for ${execution_name}:"
gcloud logging read \
  "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB_NAME}\" AND labels.\"run.googleapis.com/execution_name\"=\"${execution_name}\"" \
  --project="${PROJECT_ID}" \
  --limit="${LOG_LIMIT}" \
  --format="value(textPayload)"

echo "Account-report preflight completed; AI_REPORT_PREFLIGHT will be removed by cleanup."
