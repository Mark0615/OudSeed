(function () {
  const connectors = [
    {
      id: "meta_ads",
      name: "Meta Ads",
      label: "Facebook Ads",
      logo: "f",
      color: "blue",
      status: "available",
      connected: false,
      note: "Live sync ready",
    },
    {
      id: "google_ads",
      name: "Google Ads",
      label: "Google Ads",
      logo: "G",
      color: "google",
      status: "available",
      connected: false,
      note: "Ready for gated sync",
    },
    {
      id: "ga4",
      name: "Google Analytics 4",
      label: "Google Analytics 4",
      logo: "A",
      color: "amber",
      status: "coming_soon",
      connected: false,
      note: "Later destination context",
    },
    {
      id: "line_ads",
      name: "LINE Ads",
      label: "LINE Ads",
      logo: "L",
      color: "green",
      status: "coming_soon",
      connected: false,
      note: "Not enabled yet",
    },
    {
      id: "instagram_insights",
      name: "Instagram Insights",
      label: "Instagram Insights",
      logo: "IG",
      color: "pink",
      status: "coming_soon",
      connected: false,
      note: "Via Meta later",
    },
  ];

  const accountsByConnector = {
    meta_ads: [
      { id: "act_demo_1001", name: "Demo Shop Taiwan", currency: "TWD", timezone: "Asia/Taipei", status: "Ready" },
      { id: "act_demo_1002", name: "Demo Shop USA", currency: "USD", timezone: "America/Los_Angeles", status: "Ready" },
      { id: "act_demo_1003", name: "Pet Brand Sample", currency: "TWD", timezone: "Asia/Taipei", status: "Ready" },
      { id: "act_demo_1004", name: "Lifestyle Sample EU", currency: "EUR", timezone: "Europe/Berlin", status: "Ready" },
      { id: "act_demo_1005", name: "Agency Sandbox", currency: "TWD", timezone: "Asia/Taipei", status: "Ready" },
    ],
    google_ads: [
      { id: "1234567890", name: "Demo Search Account", currency: "TWD", timezone: "Asia/Taipei", status: "Preview" },
      { id: "2345678901", name: "Demo Shopping Account", currency: "TWD", timezone: "Asia/Taipei", status: "Preview" },
    ],
  };

  const destinations = [
    {
      id: "looker_studio",
      name: "Looker Studio",
      subtitle: "Dashboard reporting",
      category: "dashboard",
      status: "available",
      icon: "LS",
    },
    {
      id: "ai_report_email",
      name: "AI Report Email",
      subtitle: "Weekly or monthly insights",
      category: "ai",
      status: "available",
      icon: "AI",
    },
    {
      id: "bigquery",
      name: "BigQuery",
      subtitle: "Warehouse tables",
      category: "warehouse",
      status: "available",
      icon: "BQ",
    },
    {
      id: "google_sheets",
      name: "Google Sheets",
      subtitle: "Coming soon",
      category: "spreadsheet",
      status: "coming_soon",
      icon: "GS",
    },
    {
      id: "power_bi",
      name: "Power BI",
      subtitle: "Later",
      category: "dashboard",
      status: "coming_soon",
      icon: "BI",
    },
    {
      id: "cloud_storage",
      name: "Cloud Storage",
      subtitle: "Later",
      category: "warehouse",
      status: "coming_soon",
      icon: "CS",
    },
  ];

  let draftCounter = 0;
  let syncJobCounter = 0;
  const connectionDrafts = {};
  const syncJobs = {};

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function delay(value) {
    return new Promise((resolve) => {
      window.setTimeout(() => resolve(clone(value)), 120);
    });
  }

  function findConnector(connectorId) {
    return connectors.find((connector) => connector.id === connectorId);
  }

  async function apiRequest(path, options, fallback) {
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      try {
        const response = await fetch(path, {
          headers: {
            "Content-Type": "application/json",
            ...(options?.headers || {}),
          },
          ...options,
        });
        if (response.ok) {
          return response.json();
        }
      } catch {
        // Fall back to the static mock so direct file use and offline demos keep working.
      }
    }
    return fallback();
  }

  function postJson(body) {
    return {
      method: "POST",
      body: JSON.stringify(body || {}),
    };
  }

  window.OudSeedMockApi = {
    mode() {
      return window.location.protocol === "http:" || window.location.protocol === "https:"
        ? "Local API"
        : "Static mock";
    },

    listConnectors() {
      return apiRequest("/api/connectors", undefined, () => delay({
        connectors: connectors.map((connector) => ({
          ...connector,
          connected_account_count: connector.connected
            ? (accountsByConnector[connector.id] || []).length
            : 0,
        })),
      }));
    },

    startOAuth(connectorId) {
      return apiRequest(`/api/connectors/${connectorId}/oauth/start`, postJson(), () => {
        const connector = findConnector(connectorId);
        if (!connector || connector.status !== "available") {
          return Promise.reject(new Error("Connector is not available."));
        }
        return delay({
          authorization_url: `https://auth.example.test/${connectorId}/authorize`,
          state: "prototype_state",
        });
      });
    },

    completeOAuth(connectorId) {
      return apiRequest(`/api/connectors/${connectorId}/oauth/complete`, postJson(), () => {
        const connector = findConnector(connectorId);
        if (!connector || connector.status !== "available") {
          return Promise.reject(new Error("Connector is not available."));
        }
        connector.connected = true;
        return delay({
          authorization_id: `auth_${connectorId}_demo`,
          connector_id: connectorId,
          status: "connected",
        });
      });
    },

    listAccounts(connectorId) {
      const authorizationId = `auth_${connectorId}_demo`;
      return apiRequest(`/api/connectors/${connectorId}/authorizations/${authorizationId}/accounts`, undefined, () => {
        const connector = findConnector(connectorId);
        if (!connector || !connector.connected) {
          return delay({ accounts: [] });
        }
        return delay({ accounts: accountsByConnector[connectorId] || [] });
      });
    },

    listDestinations() {
      return apiRequest("/api/destinations", undefined, () => delay({ destinations }));
    },

    createConnection(payload) {
      return apiRequest("/api/account-connections", postJson(payload), () => {
        const configPreview = buildConfigPreview(payload);
        const draftId = nextDraftId();
        const firstSyncJob = createFirstSyncJob(draftId, payload);
        const destinationHandoff = buildDestinationHandoff(payload);
        const applyPlan = buildApplyPlan(payload, draftId);
        connectionDrafts[draftId] = {
          draft_id: draftId,
          status: "draft",
          created_at: new Date().toISOString(),
          local_draft_only: true,
          writes_config: false,
          writes_secrets: false,
          connection_ids: payload.accounts.map((account, index) => `conn_demo_${index + 1}`),
          first_sync_job_id: firstSyncJob.sync_job_id,
          config_preview: configPreview,
          destination_handoff: destinationHandoff,
          apply_plan: applyPlan,
        };
        return delay({
          draft_id: draftId,
          connection_ids: connectionDrafts[draftId].connection_ids,
          ok: true,
          config_preview: configPreview,
          next_sync_status: "queued",
          first_sync_job: firstSyncJob,
          destination_handoff: destinationHandoff,
          apply_plan: applyPlan,
        });
      });
    },

    listAccountConnections() {
      return apiRequest("/api/account-connections", undefined, () => {
        return delay({
          ok: true,
          connections: Object.values(connectionDrafts).map(publicConnectionSummary),
        });
      });
    },

    liveSyncReadiness() {
      return apiRequest("/api/onboarding/live-sync-readiness", undefined, () => {
        return delay({
          ok: true,
          live_sync_readiness: {
            ready: false,
            writes_bigquery: true,
            config_path: null,
            checks: [
              {
                id: "local_config_artifact_exists",
                ok: false,
                message: "Local API is required to create a local sync artifact.",
              },
            ],
            summary: {
              platform: "meta_ads",
              client_count: 0,
              enabled_meta_account_count: 0,
              destination_count: 0,
              report_schedule_count: 0,
            },
            warnings: ["static_mock_no_local_artifact"],
          },
        });
      });
    },

    getSyncJob(syncJobId) {
      return apiRequest(`/api/sync-jobs/${syncJobId}`, undefined, () => {
        const job = syncJobs[syncJobId];
        if (!job) {
          return Promise.reject(new Error("Unknown sync job."));
        }
        advanceSyncJob(job);
        return delay({ ok: true, sync_job: publicSyncJob(job) });
      });
    },

    sendReportEmail(syncJobId) {
      return apiRequest(`/api/sync-jobs/${syncJobId}/report-email`, postJson(), () => {
        const job = syncJobs[syncJobId];
        if (!job) {
          return Promise.reject(new Error("Unknown sync job."));
        }
        if (job.status !== "completed") {
          return Promise.reject(new Error("First sync must complete before sending report email."));
        }
        job.email_delivery = {
          status: "sent",
          message: "Report email sent.",
          report_id: `report_demo_${syncJobId}`,
          report_type: job.report_type || "monthly",
          period_start_date: "2026-05-01",
          recipient_configured: true,
        };
        return delay({ ok: true, email_delivery: job.email_delivery });
      });
    },

    reset() {
      return apiRequest("/api/reset", postJson(), () => {
        connectors.forEach((connector) => {
          connector.connected = false;
        });
        Object.keys(syncJobs).forEach((syncJobId) => {
          delete syncJobs[syncJobId];
        });
        Object.keys(connectionDrafts).forEach((draftId) => {
          delete connectionDrafts[draftId];
        });
        return delay({ ok: true });
      });
    },
  };

  function publicConnectionSummary(draft) {
    const summary = draft.config_preview?.summary || {};
    const handoffDestinations = draft.destination_handoff?.destinations || {};
    const reportHandoff = handoffDestinations.ai_report_email || null;
    return {
      draft_id: draft.draft_id,
      status: draft.status,
      created_at: draft.created_at,
      first_sync_job_id: draft.first_sync_job_id,
      connection_count: draft.connection_ids.length,
      account_count: summary.account_count || 0,
      destinations: summary.destinations || [],
      destination_statuses: Object.fromEntries(
        Object.entries(handoffDestinations).map(([destinationId, handoff]) => [
          destinationId,
          handoff.status || "unknown",
        ])
      ),
      report_schedule: reportHandoff
        ? {
            report_type: reportHandoff.report_type || "monthly",
            delivery_day: reportHandoff.delivery_day || 1,
            timezone: reportHandoff.timezone || "Asia/Taipei",
            depth: reportHandoff.depth || "standard",
          }
        : null,
      local_draft_only: true,
      writes_config: false,
      writes_secrets: false,
    };
  }

  function buildConfigPreview(payload) {
    const warnings = [];
    if (payload.destinations.includes("looker_studio") && !payload.destinations.includes("bigquery")) {
      warnings.push("looker_studio_uses_bigquery_views");
    }
    if (payload.destinations.includes("google_sheets")) {
      warnings.push("google_sheets_destination_not_productized");
    }
    const summary = {
      client_count: 1,
      account_count: payload.accounts.length,
      destinations: payload.destinations,
      report_schedule_count: payload.report_schedule ? 1 : 0,
    };
    return {
      summary,
      summary_lines: [
        "onboarding_config_preview=true",
        "client_count=1",
        `account_count=${payload.accounts.length}`,
        `destinations=${payload.destinations.join(",")}`,
        `report_schedule_count=${payload.report_schedule ? 1 : 0}`,
        ...warnings.map((warning) => `warning=${warning}`),
      ],
      warnings,
      yaml_text: buildPreviewYaml(payload),
    };
  }

  function buildDestinationHandoff(payload) {
    const selectedDestinations = payload.destinations || [];
    const reportSchedule = payload.report_schedule || {};
    const handoff = {
      writes_config: false,
      writes_secrets: false,
      local_draft_only: true,
      destinations: {},
    };
    if (selectedDestinations.includes("bigquery") || selectedDestinations.includes("looker_studio")) {
      handoff.destinations.bigquery = {
        status: "available",
        project_id: "oudseed",
        dataset: "ads_pipeline",
        uses_existing_pipeline: true,
        next_step: "Map the approved account selection into clients.yaml or Secret Manager-backed config.",
      };
    }
    if (selectedDestinations.includes("looker_studio")) {
      handoff.destinations.looker_studio = {
        status: "handoff_required",
        handoff_type: "template_linking_url",
        depends_on: ["bigquery"],
        template_report_required: true,
        next_step: "Create or copy a Looker Studio template connected to the existing BigQuery views, then attach the template/linking URL to this account group.",
      };
    }
    if (selectedDestinations.includes("ai_report_email")) {
      handoff.destinations.ai_report_email = {
        status: "config_preview_ready",
        report_type: reportSchedule.report_type || "monthly",
        delivery_day: reportSchedule.delivery_day || 1,
        timezone: reportSchedule.timezone || "Asia/Taipei",
        depth: reportSchedule.depth || "standard",
        next_step: "Review the sanitized report schedule and promote it into managed client config.",
      };
    }
    if (selectedDestinations.includes("google_sheets")) {
      handoff.destinations.google_sheets = {
        status: "not_productized",
        next_step: "Keep disabled until Google Sheets export is implemented.",
      };
    }
    return handoff;
  }

  function buildApplyPlan(payload, draftId) {
    const selectedDestinations = payload.destinations || [];
    const platform = payload.connector_id === "google_ads" ? "google_ads" : "meta_ads";
    const platformLabel = platform === "google_ads" ? "Google Ads" : "Meta";
    const steps = [
      {
        id: "review_config_preview",
        status: "ready",
        label: "Review sanitized clients.yaml-compatible preview.",
      },
      {
        id: "promote_account_config",
        status: "manual_gate",
        label: "Promote selected accounts into managed config after review.",
      },
      {
        id: `run_${platform}_sync_preflight`,
        status: "ready_after_config",
        label: `Run ${platformLabel} sync readiness against the selected account group.`,
      },
    ];
    if (selectedDestinations.includes("looker_studio")) {
      steps.push({
        id: "prepare_looker_template",
        status: "handoff_required",
        label: "Attach a Looker Studio template or linking URL backed by BigQuery views.",
      });
    }
    if (selectedDestinations.includes("ai_report_email")) {
      steps.push({
        id: "run_ai_report_preflight",
        status: "ready_after_config",
        label: "Run AI report preflight before enabling recurring delivery.",
      });
    }
    return {
      draft_id: draftId,
      safe_to_display: true,
      local_draft_only: true,
      sensitive_payload_persisted: false,
      writes_config: false,
      writes_secrets: false,
      steps,
      recommended_checks: ["make ai-report-ready", "make ai-report-preflight"],
    };
  }

  function nextDraftId() {
    draftCounter += 1;
    return `draft_demo_${String(draftCounter).padStart(4, "0")}`;
  }

  function createFirstSyncJob(draftId, payload) {
    syncJobCounter += 1;
    const syncJobId = `sync_demo_${String(syncJobCounter).padStart(4, "0")}`;
    const job = {
      sync_job_id: syncJobId,
      draft_id: draftId,
      status: "queued",
      progress_percent: 10,
      checks: 0,
      account_count: payload.accounts.length,
      destinations: payload.destinations || [],
      platform: payload.connector_id === "google_ads" ? "google_ads" : "meta_ads",
      message: "First sync is queued.",
      email_delivery: null,
    };
    syncJobs[syncJobId] = job;
    return publicSyncJob(job);
  }

  function advanceSyncJob(job) {
    job.checks += 1;
    if (job.checks === 1) {
      job.status = "running";
      job.progress_percent = 55;
      job.message = "Syncing selected ad account data.";
    } else {
      job.status = "completed";
      job.progress_percent = 100;
      job.message = "First sync completed. Destinations are ready.";
    }
  }

  function publicSyncJob(job) {
    const syncJob = {
      sync_job_id: job.sync_job_id,
      draft_id: job.draft_id,
      status: job.status,
      progress_percent: job.progress_percent,
      message: job.message,
      summary: {
        account_count: job.account_count,
        destinations: job.destinations,
        writes_config: false,
        local_prototype: true,
      },
      steps: syncJobSteps(job.status, job.destinations),
    };
    if (job.status === "completed") {
      const platformLabel = job.platform === "google_ads" ? "Google Ads" : "Meta";
      syncJob.backend_data_check = {
        status: "healthy",
        source: "prototype",
        checked_at: new Date().toISOString(),
        message: `Latest ${platformLabel} sync data is visible in BigQuery and dashboard views.`,
        scope: {
          platform: job.platform,
          selected_account_count: job.account_count,
          selected_accounts_scoped: true,
        },
        latest_sync: {
          status: "success",
          rows_fetched: 3,
          rows_inserted: 3,
          sync_start_date: "2026-05-30",
          sync_end_date: "2026-05-30",
        },
        destinations: {
          bigquery: { status: "verified", raw_rows: 3, unified_rows: 3 },
          looker_studio: { status: "verified", ad_daily_rows: 3, campaign_daily_rows: 2 },
        },
        warnings: [],
      };
    }
    return syncJob;
  }

  function syncJobSteps(status, selectedDestinations) {
    const warehouseStatus = status === "completed" ? "completed" : status === "running" ? "running" : "queued";
    const outputStatus = status === "completed" ? "completed" : "queued";
    const steps = [
      { id: "source_connected", label: "Source connected", status: "completed" },
      { id: "warehouse_sync", label: "Data warehouse sync", status: warehouseStatus },
    ];
    if (selectedDestinations.includes("looker_studio")) {
      steps.push({ id: "dashboard_refresh", label: "Dashboard data refresh", status: outputStatus });
    }
    if (selectedDestinations.includes("ai_report_email")) {
      steps.push({ id: "report_schedule", label: "Report schedule setup", status: outputStatus });
    }
    return steps;
  }

  function buildPreviewYaml(payload) {
    const clientName = payload.client_name || payload.accounts[0]?.account_name || "Onboarding Preview Client";
    const lines = [
      "workspace_id: workspace_demo",
      "defaults:",
      "  timezone: Asia/Taipei",
      "  sync_days_back: 7",
      "  attribution_setting: platform_default",
      "  timezone_setting: platform_account_default",
      "  conversion_action_type: purchase",
      "bigquery:",
      "  project_id: oudseed",
      "  dataset: ads_pipeline",
      "clients:",
      `- client_id: ${slug(clientName)}`,
      `  client_name: ${clientName}`,
      "  enabled: true",
      "  platforms:",
    ];
    if (payload.connector_id === "google_ads") {
      lines.push(
        "    google_ads:",
        "      enabled: true",
        "      accounts:",
      );
      payload.accounts.forEach((account, index) => {
        lines.push(
          `      - customer_id: 000000${String(index + 1).padStart(4, "0")}`,
          `        account_name: ${account.account_name}`,
          "        login_customer_id: null",
          "        report_level: ad",
          "        attribution_setting: platform_default",
          "        timezone_setting: platform_account_default",
        );
      });
    } else {
      lines.push(
        "    meta_ads:",
        "      enabled: true",
        "      accounts:",
      );
      payload.accounts.forEach((account, index) => {
        lines.push(
          `      - ad_account_id: act_preview_${String(index + 1).padStart(4, "0")}`,
          `        account_name: ${account.account_name}`,
          "        report_level: ad",
          "        attribution_setting: platform_default",
          "        timezone_setting: platform_account_default",
          "        conversion_action_type: purchase",
        );
      });
    }
    lines.push(
      "  destinations:",
      "    bigquery:",
      `      enabled: ${payload.destinations.includes("bigquery") || payload.destinations.includes("looker_studio")}`,
      "      project_id: oudseed",
      "      dataset: ads_pipeline",
      "    looker_studio:",
      `      enabled: ${payload.destinations.includes("looker_studio")}`,
      "    ai_report_email:",
      `      enabled: ${payload.destinations.includes("ai_report_email")}`,
      "    google_sheets:",
      `      enabled: ${payload.destinations.includes("google_sheets")}`,
      "      spreadsheet_id: preview_spreadsheet_id",
    );
    if (payload.report_schedule) {
      lines.push(
        "  report_schedules:",
        `  - schedule_id: ${payload.report_schedule.report_type}_email_default`,
        "    enabled: true",
        `    report_type: ${payload.report_schedule.report_type}`,
        `    delivery_day: ${payload.report_schedule.delivery_day}`,
        `    timezone: ${payload.report_schedule.timezone}`,
        "    channel: email",
        "    email_to: recipient@example.com",
        `    depth: ${payload.report_schedule.depth}`,
      );
    }
    return `${lines.join("\n")}\n`;
  }

  function slug(value) {
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "onboarding_preview";
  }
})();
