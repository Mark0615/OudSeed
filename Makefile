PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: install test lint run check onboarding-prototype onboarding-prototype-real-meta onboarding-prototype-persistent onboarding-prototype-google-persistent onboarding-prototype-live-sync onboarding-prototype-google-live-sync onboarding-live-sync-ready onboarding-google-live-sync-ready onboarding-sync-local-config onboarding-google-sync-local-config ai-report-deploy-dry-run ai-report-status ai-report-ready ai-report-preflight ai-report-logs ai-report-post-run ai-report-verify clean

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m compileall src tests

run:
	$(PYTHON) -m src.main

check:
	$(PYTHON) -m compileall src tests && $(PYTHON) -m pytest

onboarding-prototype:
	$(PYTHON) -m src.onboarding.api_server

onboarding-prototype-real-meta:
	ONBOARDING_USE_REAL_META=true ONBOARDING_USE_BIGQUERY_STATUS=true ONBOARDING_ENABLE_EMAIL_SEND=true $(PYTHON) -m src.onboarding.api_server

onboarding-prototype-persistent:
	ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_READINESS=true ONBOARDING_USE_REAL_META=true ONBOARDING_USE_BIGQUERY_STATUS=true ONBOARDING_ENABLE_EMAIL_SEND=true $(PYTHON) -m src.onboarding.api_server

onboarding-prototype-google-persistent:
	ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_READINESS=true ONBOARDING_LIVE_SYNC_PLATFORM=google_ads ONBOARDING_USE_BIGQUERY_STATUS=true ONBOARDING_ENABLE_EMAIL_SEND=true $(PYTHON) -m src.onboarding.api_server

onboarding-prototype-live-sync:
	ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true ONBOARDING_USE_REAL_META=true ONBOARDING_USE_BIGQUERY_STATUS=true ONBOARDING_ENABLE_EMAIL_SEND=true $(PYTHON) -m src.onboarding.api_server

onboarding-prototype-google-live-sync:
	ONBOARDING_STATE_STORE_PATH=.local/onboarding_state.json ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true ONBOARDING_LIVE_SYNC_PLATFORM=google_ads ONBOARDING_USE_BIGQUERY_STATUS=true ONBOARDING_ENABLE_EMAIL_SEND=true $(PYTHON) -m src.onboarding.api_server

onboarding-live-sync-ready:
	ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true SYNC_ENABLED_PLATFORMS=meta_ads $(PYTHON) -m src.onboarding.live_sync_readiness

onboarding-google-live-sync-ready:
	ONBOARDING_LOCAL_CONFIG_EXPORT_PATH=.local/clients.generated.yaml ONBOARDING_ENABLE_LOCAL_SYNC_RUN=true ONBOARDING_LIVE_SYNC_PLATFORM=google_ads SYNC_ENABLED_PLATFORMS=google_ads $(PYTHON) -m src.onboarding.live_sync_readiness

onboarding-sync-local-config:
	CLIENTS_CONFIG_PATH=.local/clients.generated.yaml SYNC_ENABLED_PLATFORMS=meta_ads $(PYTHON) -m src.main

onboarding-google-sync-local-config:
	CLIENTS_CONFIG_PATH=.local/clients.generated.yaml SYNC_ENABLED_PLATFORMS=google_ads $(PYTHON) -m src.main

ai-report-deploy-dry-run:
	DEPLOY_DRY_RUN=true bash deploy/deploy_account_ai_report_job.sh

ai-report-status:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_status.sh

ai-report-ready:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_ready.sh

ai-report-preflight:
	bash deploy/run_account_ai_report_preflight.sh

ai-report-logs:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_logs.sh

ai-report-post-run:
	PYTHON_BIN=$(PYTHON) bash deploy/verify_account_ai_report_post_run.sh

ai-report-verify:
	PYTHON_BIN=$(PYTHON) bash deploy/verify_account_ai_report_ops.sh

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
