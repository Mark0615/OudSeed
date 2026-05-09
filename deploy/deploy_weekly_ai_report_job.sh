#!/usr/bin/env bash
set -euo pipefail

JOB_NAME="${JOB_NAME:-oudseed-ai-report-weekly}" \
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-ai-report-weekly}" \
SCHEDULE="${SCHEDULE:-0 5 * * 1}" \
AI_REPORT_TYPE="${AI_REPORT_TYPE:-weekly}" \
bash deploy/deploy_ai_report_job.sh
