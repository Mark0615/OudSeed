#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
REGION="${REGION:-asia-east1}"
SCHEDULER_REGION="${SCHEDULER_REGION:-asia-east1}"
JOB_NAME="${JOB_NAME:-oudseed-account-ai-report}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-account-ai-report-monthly}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

job_json="$(
  gcloud run jobs describe "${JOB_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format=json
)"

scheduler_json="$(
  gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --location="${SCHEDULER_REGION}" \
    --project="${PROJECT_ID}" \
    --format=json
)"

"${PYTHON_BIN}" - "${job_json}" "${scheduler_json}" <<'PY'
import json
import sys

job = json.loads(sys.argv[1])
scheduler = json.loads(sys.argv[2])

template_spec = job["spec"]["template"]["spec"]["template"]["spec"]
container = template_spec["containers"][0]
env = {item.get("name"): item for item in container.get("env", [])}
plain_env = {
    name: item.get("value")
    for name, item in env.items()
    if "value" in item
}

conditions = {
    condition.get("type"): condition.get("status")
    for condition in job.get("status", {}).get("conditions", [])
}
latest_execution = job.get("status", {}).get("latestCreatedExecution", {})

def configured(name: str) -> str:
    return str(name in env).lower()

def plain_value(name: str, default: str = "-") -> str:
    return str(plain_env.get(name) or default)

def module_name() -> str:
    args = container.get("args", [])
    if "-m" in args:
        module_index = args.index("-m") + 1
        if module_index < len(args):
            return str(args[module_index])
    return plain_value("AI_REPORT_MODULE")

print("account_report_cloud_status=true")
print(f"job={job['metadata']['name']}")
print(f"region={job['metadata']['labels'].get('cloud.googleapis.com/location', '-')}")
print(f"ready={conditions.get('Ready', '-')}")
print(f"latest_execution={latest_execution.get('name', '-')}")
print(f"latest_execution_status={latest_execution.get('completionStatus', '-')}")
print(f"max_retries={template_spec.get('maxRetries', '-')}")
print(f"task_timeout_seconds={template_spec.get('timeoutSeconds', '-')}")
print(f"command={' '.join(container.get('command', [])) or '-'}")
print(f"args={' '.join(container.get('args', [])) or '-'}")
print(f"ai_report_module={module_name()}")
print(f"ai_report_type={plain_value('AI_REPORT_TYPE')}")
print(f"ai_report_depth={plain_value('AI_REPORT_DEPTH')}")
print(f"openai_model={plain_value('OPENAI_MODEL')}")
print(f"openai_max_output_tokens={plain_value('OPENAI_MAX_OUTPUT_TOKENS')}")
print(f"openai_timeout_seconds={plain_value('OPENAI_TIMEOUT_SECONDS')}")
print(f"preflight_enabled={str(plain_env.get('AI_REPORT_PREFLIGHT') == 'true').lower()}")
print(f"schedule_id_configured={configured('AI_REPORT_SCHEDULE_ID')}")
print(f"recipient_configured={configured('AI_REPORT_EMAIL_TO')}")
print(f"openai_secret_configured={configured('OPENAI_API_KEY')}")
print(f"clients_config_secret_configured={configured('CLIENTS_CONFIG_YAML')}")
print(f"smtp_password_secret_configured={configured('SMTP_PASSWORD')}")
print(f"scheduler={scheduler.get('name', '-').rsplit('/', 1)[-1]}")
print(f"scheduler_state={scheduler.get('state', '-')}")
print(f"scheduler_schedule={scheduler.get('schedule', '-')}")
print(f"scheduler_time_zone={scheduler.get('timeZone', '-')}")
print(f"scheduler_next_schedule_time={scheduler.get('scheduleTime', '-')}")
PY
