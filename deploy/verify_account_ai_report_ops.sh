#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

echo "== Account AI report deploy preview =="
DEPLOY_DRY_RUN=true bash deploy/deploy_account_ai_report_job.sh

echo
echo "== Account AI report Cloud Run status =="
PYTHON_BIN="${PYTHON_BIN}" bash deploy/check_account_ai_report_status.sh

if [[ -n "${AI_REPORT_PERIOD_START_DATE:-}" ]]; then
  echo
  echo "== Account AI report log completeness =="
  if [[ -n "${AI_REPORT_LOG_CREATED_AFTER:-}" ]]; then
    require_complete="${AI_REPORT_LOG_REQUIRE_COMPLETE:-true}"
  else
    require_complete="${AI_REPORT_LOG_REQUIRE_COMPLETE:-false}"
    echo "AI_REPORT_LOG_CREATED_AFTER is not set; running informational log check."
    echo "Set AI_REPORT_LOG_CREATED_AFTER to verify one specific send batch strictly."
  fi
  AI_REPORT_LOG_REQUIRE_COMPLETE="${require_complete}" \
  AI_REPORT_LOG_SHOW_ROWS="${AI_REPORT_LOG_SHOW_ROWS:-false}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  bash deploy/check_account_ai_report_logs.sh
else
  echo
  echo "Skipping report-log completeness check: AI_REPORT_PERIOD_START_DATE is not set."
fi
