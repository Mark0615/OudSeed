#!/usr/bin/env bash
set -euo pipefail

JOB_NAME="${JOB_NAME:-oudseed-account-ai-report}" \
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-account-ai-report-monthly}" \
SCHEDULE="${SCHEDULE:-0 5 1 * *}" \
AI_REPORT_MODULE="${AI_REPORT_MODULE:-src.ai.send_account_reports}" \
AI_REPORT_TYPE="${AI_REPORT_TYPE:-monthly}" \
bash deploy/deploy_ai_report_job.sh
