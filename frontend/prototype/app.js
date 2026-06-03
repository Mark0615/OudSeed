const api = window.OudSeedMockApi;

let sources = [];
let destinations = [];

const state = {
  selectedSourceId: null,
  selectedAccounts: new Set(),
  selectedDestinations: new Set(["looker_studio", "ai_report_email"]),
  destinationCategory: "all",
  reportType: "monthly",
  syncPollTimer: null,
  currentSyncJobId: null,
  connections: [],
  liveSyncReadiness: null,
};

const els = {
  platformSearch: document.querySelector("#platformSearch"),
  runtimePill: document.querySelector("#runtimePill"),
  connectedOnly: document.querySelector("#connectedOnly"),
  platformList: document.querySelector("#platformList"),
  sourceCount: document.querySelector("#sourceCount"),
  selectedSourceTitle: document.querySelector("#selectedSourceTitle"),
  sourceStatusPill: document.querySelector("#sourceStatusPill"),
  heroLogo: document.querySelector("#heroLogo"),
  heroTitle: document.querySelector("#heroTitle"),
  heroText: document.querySelector("#heroText"),
  connectButton: document.querySelector("#connectButton"),
  accountSearch: document.querySelector("#accountSearch"),
  selectAllAccountsButton: document.querySelector("#selectAllAccountsButton"),
  accountMasterCheckbox: document.querySelector("#accountMasterCheckbox"),
  accountRows: document.querySelector("#accountRows"),
  accountSelectionCount: document.querySelector("#accountSelectionCount"),
  destinationGrid: document.querySelector("#destinationGrid"),
  destinationSelectionCount: document.querySelector("#destinationSelectionCount"),
  emailSettings: document.querySelector("#emailSettings"),
  monthlyDeliveryField: document.querySelector("#monthlyDeliveryField"),
  weeklyDeliveryField: document.querySelector("#weeklyDeliveryField"),
  monthlyDeliveryDay: document.querySelector("#monthlyDeliveryDay"),
  weeklyDeliveryDay: document.querySelector("#weeklyDeliveryDay"),
  reportDepth: document.querySelector("#reportDepth"),
  reportTimezone: document.querySelector("#reportTimezone"),
  summaryText: document.querySelector("#summaryText"),
  finishButton: document.querySelector("#finishButton"),
  connectionResult: document.querySelector("#connectionResult"),
  connectionList: document.querySelector("#connectionList"),
  connectionListCount: document.querySelector("#connectionListCount"),
  connectionStatus: document.querySelector("#connectionStatus"),
  handoffSummary: document.querySelector("#handoffSummary"),
  payloadPreview: document.querySelector("#payloadPreview"),
  nextActions: document.querySelector("#nextActions"),
  developerStatus: document.querySelector("#developerStatus"),
  configPreview: document.querySelector("#configPreview"),
  authModal: document.querySelector("#authModal"),
  closeAuthButton: document.querySelector("#closeAuthButton"),
  grantAccessButton: document.querySelector("#grantAccessButton"),
  modalLogo: document.querySelector("#modalLogo"),
  authTitle: document.querySelector("#authTitle"),
  authDescription: document.querySelector("#authDescription"),
  modalNote: document.querySelector("#modalNote"),
  resetButton: document.querySelector("#resetButton"),
  toast: document.querySelector("#toast"),
};

function isAvailable(item) {
  return item.status === "available";
}

function selectedSource() {
  return sources.find((source) => source.id === state.selectedSourceId) || null;
}

function selectedSourceAccounts() {
  return selectedSource()?.accounts || [];
}

function visibleAccounts() {
  const source = selectedSource();
  const query = els.accountSearch.value.trim().toLowerCase();
  if (!source || !source.connected) {
    return [];
  }
  return selectedSourceAccounts().filter((account) => {
    return account.name.toLowerCase().includes(query) || account.id.toLowerCase().includes(query);
  });
}

async function hydrateData() {
  const [{ connectors }, destinationResponse, connectionResponse] = await Promise.all([
    api.listConnectors(),
    api.listDestinations(),
    api.listAccountConnections(),
  ]);
  sources = connectors.map((connector) => ({
    ...connector,
    accounts: sources.find((source) => source.id === connector.id)?.accounts || [],
  }));
  destinations = destinationResponse.destinations;
  state.connections = connectionResponse.connections || [];
}

function renderSources() {
  const query = els.platformSearch.value.trim().toLowerCase();
  const onlyConnected = els.connectedOnly.checked;
  const filtered = sources.filter((source) => {
    const matchesQuery =
      source.name.toLowerCase().includes(query) || source.label.toLowerCase().includes(query);
    const matchesConnection = !onlyConnected || source.connected;
    return matchesQuery && matchesConnection;
  });

  els.sourceCount.textContent = `${filtered.length} shown`;
  const realMetaEnabled = sources.some((source) => source.id === "meta_ads" && source.data_mode === "real_meta_api");
  if (realMetaEnabled) {
    els.runtimePill.textContent = "Local API + Real Meta";
  }
  els.platformList.innerHTML =
    filtered
      .map((source) => {
        const selected = source.id === state.selectedSourceId ? "selected" : "";
        const unavailable = isAvailable(source) ? "" : "disabled";
        const accountCount = source.connected_account_count || selectedSourceAccounts().length;
        const connected = source.connected ? `<span class="mini-pill">Connected</span>` : "";
        return `
          <button class="platform-item ${selected}" type="button" data-source-id="${source.id}" ${unavailable}>
            <span class="platform-logo ${source.color}">${source.logo}</span>
            <span class="platform-copy">
              <strong>${source.label}</strong>
              <small>${source.connected ? `${accountCount} accounts available` : source.note}</small>
            </span>
            ${connected}
          </button>
        `;
      })
      .join("") || `<div class="empty-card">No matching platforms.</div>`;

  document.querySelectorAll("[data-source-id]").forEach((button) => {
    button.addEventListener("click", () => selectSource(button.dataset.sourceId));
  });
}

function renderSourceHero() {
  const source = selectedSource();
  const hasSource = Boolean(source);
  els.connectButton.disabled = !hasSource || !isAvailable(source);

  if (!source) {
    els.selectedSourceTitle.textContent = "Select a platform";
    els.sourceStatusPill.textContent = "Not connected";
    els.sourceStatusPill.className = "status-pill";
    els.heroLogo.className = "hero-logo";
    els.heroLogo.textContent = "OS";
    els.heroTitle.textContent = "Start with a data source";
    els.heroText.textContent =
      "Meta Ads is the current MVP path. Google Ads and LINE Ads are shown here so the user flow already matches the future product.";
    els.connectButton.textContent = "Connect";
    return;
  }

  els.selectedSourceTitle.textContent = source.label;
  els.sourceStatusPill.textContent = source.connected
    ? "Connected"
    : isAvailable(source)
      ? "Needs authorization"
      : "Coming soon";
  els.sourceStatusPill.className = `status-pill ${
    source.connected ? "connected" : isAvailable(source) ? "pending" : "disabled"
  }`;
  els.heroLogo.className = `hero-logo ${source.color}`;
  els.heroLogo.textContent = source.logo;
  els.heroTitle.textContent = source.connected
    ? `${source.label} connected`
    : `Connect your ${source.label} account`;
  els.heroText.textContent = source.connected
    ? "Choose which ad accounts should be synced into the selected destinations."
    : isAvailable(source)
      ? "Authorize read access first. The real product will open the platform OAuth flow here."
      : "This connector is visible in the prototype but not part of the current MVP backend.";
  els.connectButton.textContent = source.connected ? "Reconnect" : "Connect";
}

function renderAccounts() {
  const source = selectedSource();
  const accounts = visibleAccounts();
  const enabled = Boolean(source && source.connected);

  els.accountSearch.disabled = !enabled;
  els.selectAllAccountsButton.disabled = !enabled || accounts.length === 0;
  els.accountMasterCheckbox.disabled = !enabled || accounts.length === 0;

  if (!source) {
    els.accountSelectionCount.textContent = "No source selected";
    els.accountRows.innerHTML = `<tr><td colspan="4" class="empty-state">Connect a platform to load ad accounts.</td></tr>`;
    return;
  }

  if (!source.connected) {
    els.accountSelectionCount.textContent = "Authorization required";
    els.accountRows.innerHTML = `<tr><td colspan="4" class="empty-state">Authorize ${source.label} before selecting accounts.</td></tr>`;
    return;
  }

  const selectedCount = [...state.selectedAccounts].filter((id) => {
    return selectedSourceAccounts().some((account) => account.id === id);
  }).length;
  els.accountSelectionCount.textContent = `${selectedCount} selected`;

  if (accounts.length === 0) {
    els.accountRows.innerHTML = `<tr><td colspan="4" class="empty-state">No accounts match your search.</td></tr>`;
    return;
  }

  els.accountRows.innerHTML = accounts
    .map((account) => {
      const checked = state.selectedAccounts.has(account.id) ? "checked" : "";
      return `
        <tr>
          <td><input class="account-checkbox" type="checkbox" data-account-id="${account.id}" ${checked} /></td>
          <td>${account.name}</td>
          <td><code>${account.id}</code></td>
          <td><span class="account-status">${account.status}</span></td>
        </tr>
      `;
    })
    .join("");

  const visibleIds = accounts.map((account) => account.id);
  els.accountMasterCheckbox.checked =
    visibleIds.length > 0 && visibleIds.every((id) => state.selectedAccounts.has(id));

  document.querySelectorAll("[data-account-id]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      toggleAccount(checkbox.dataset.accountId, checkbox.checked);
    });
  });
}

function renderDestinations() {
  const filtered = destinations.filter((destination) => {
    return state.destinationCategory === "all" || destination.category === state.destinationCategory;
  });

  els.destinationGrid.innerHTML = filtered
    .map((destination) => {
      const selected = state.selectedDestinations.has(destination.id) ? "selected" : "";
      const disabled = isAvailable(destination) ? "" : "disabled";
      return `
        <button class="destination-card ${selected}" type="button" data-destination-id="${destination.id}" ${disabled}>
          <span class="destination-icon">${destination.icon}</span>
          <span>
            <strong>${destination.name}</strong>
            <small>${destination.subtitle}</small>
          </span>
        </button>
      `;
    })
    .join("");

  document.querySelectorAll("[data-destination-id]").forEach((button) => {
    button.addEventListener("click", () => toggleDestination(button.dataset.destinationId));
  });

  els.destinationSelectionCount.textContent = `${state.selectedDestinations.size} selected`;
}

function renderStepper() {
  const source = selectedSource();
  const hasAccounts = state.selectedAccounts.size > 0;
  const hasDestinations = state.selectedDestinations.size > 0;
  const stepState = {
    source: Boolean(source),
    auth: Boolean(source && source.connected),
    accounts: hasAccounts,
    destinations: hasAccounts && hasDestinations,
  };

  document.querySelectorAll("[data-step]").forEach((step) => {
    const key = step.dataset.step;
    step.classList.toggle("complete", stepState[key]);
    step.classList.toggle("active", !stepState[key] && firstIncompleteStep(stepState) === key);
  });
}

function firstIncompleteStep(stepState) {
  return ["source", "auth", "accounts", "destinations"].find((key) => !stepState[key]) || "destinations";
}

function renderSummary() {
  const source = selectedSource();
  const accountCount = state.selectedAccounts.size;
  const destinationNames = destinations
    .filter((destination) => state.selectedDestinations.has(destination.id))
    .map((destination) => destination.name);
  const ready = Boolean(source && source.connected && accountCount > 0 && destinationNames.length > 0);

  if (!source) {
    els.summaryText.textContent = "Choose a source to continue.";
  } else if (!source.connected) {
    els.summaryText.textContent = `${source.label} needs authorization.`;
  } else if (accountCount === 0) {
    els.summaryText.textContent = `Select at least one ${source.label} ad account.`;
  } else {
    els.summaryText.textContent = `${source.label}: ${accountCount} account${
      accountCount > 1 ? "s" : ""
    } to ${destinationNames.join(", ")}.`;
  }

  els.finishButton.disabled = !ready;
}

function renderAll() {
  renderSources();
  renderSourceHero();
  renderAccounts();
  renderDestinations();
  renderEmailSettings();
  renderConnections();
  renderStepper();
  renderSummary();
}

async function selectSource(sourceId) {
  const source = sources.find((item) => item.id === sourceId);
  if (!source) {
    return;
  }
  state.selectedSourceId = sourceId;
  state.selectedAccounts.clear();
  clearConnectionResult();
  els.accountSearch.value = "";
  renderAll();

  if (!isAvailable(source)) {
    showToast(`${source.label} is not enabled in this MVP yet.`);
    return;
  }

  if (!source.connected) {
    await api.startOAuth(source.id);
    openAuthModal(source);
  }
}

function toggleAccount(accountId, checked) {
  clearConnectionResult();
  if (checked) {
    state.selectedAccounts.add(accountId);
  } else {
    state.selectedAccounts.delete(accountId);
  }
  renderAccounts();
  renderStepper();
  renderSummary();
}

function toggleDestination(destinationId) {
  const destination = destinations.find((item) => item.id === destinationId);
  if (!destination || !isAvailable(destination)) {
    return;
  }
  clearConnectionResult();
  if (state.selectedDestinations.has(destinationId)) {
    state.selectedDestinations.delete(destinationId);
  } else {
    state.selectedDestinations.add(destinationId);
  }
  renderDestinations();
  renderEmailSettings();
  renderStepper();
  renderSummary();
}

function renderEmailSettings() {
  const enabled = state.selectedDestinations.has("ai_report_email");
  els.emailSettings.hidden = !enabled;
  els.monthlyDeliveryField.hidden = state.reportType !== "monthly";
  els.weeklyDeliveryField.hidden = state.reportType !== "weekly";
  document.querySelectorAll("[data-report-type]").forEach((button) => {
    button.classList.toggle("active", button.dataset.reportType === state.reportType);
  });
}

function selectAllVisibleAccounts() {
  visibleAccounts().forEach((account) => state.selectedAccounts.add(account.id));
  renderAccounts();
  renderStepper();
  renderSummary();
}

function openAuthModal(source) {
  els.modalLogo.className = `modal-logo ${source.color}`;
  els.modalLogo.textContent = source.logo;
  els.authTitle.textContent = `Connect your ${source.label} account`;
  els.authDescription.textContent =
    `Grant ${source.label} access so OudSeed can show available ad accounts and sync selected performance data.`;
  els.grantAccessButton.textContent = `Grant ${source.label} Access`;
  els.modalNote.textContent = "Prototype only: this simulates OAuth and does not store tokens.";
  els.authModal.classList.add("open");
  els.authModal.setAttribute("aria-hidden", "false");
}

function closeAuthModal() {
  els.authModal.classList.remove("open");
  els.authModal.setAttribute("aria-hidden", "true");
}

async function completeAuthorization() {
  const source = selectedSource();
  if (!source) {
    return;
  }
  await api.completeOAuth(source.id);
  const [{ connectors }, { accounts }] = await Promise.all([
    api.listConnectors(),
    api.listAccounts(source.id),
  ]);
  sources = connectors.map((connector) => ({
    ...connector,
    accounts: connector.id === source.id
      ? accounts
      : sources.find((existingSource) => existingSource.id === connector.id)?.accounts || [],
  }));
  closeAuthModal();
  renderAll();
  showToast(`${source.label} connected. Select ad accounts to continue.`);
}

async function resetDemo() {
  await api.reset();
  state.selectedSourceId = null;
  state.selectedAccounts.clear();
  state.selectedDestinations = new Set(["looker_studio", "ai_report_email"]);
  state.destinationCategory = "all";
  state.reportType = "monthly";
  state.liveSyncReadiness = null;
  els.platformSearch.value = "";
  els.connectedOnly.checked = false;
  els.accountSearch.value = "";
  els.monthlyDeliveryDay.value = "1";
  els.weeklyDeliveryDay.value = "monday";
  els.reportDepth.value = "standard";
  els.reportTimezone.value = "Asia/Taipei";
  document.querySelectorAll("[data-category]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.category === "all");
  });
  closeAuthModal();
  clearConnectionResult();
  await hydrateData();
  renderAll();
  showToast("Demo reset.");
}

async function createConnection() {
  const payload = buildConnectionPayload();
  if (!payload) {
    return;
  }
  stopSyncPolling();
  const result = await api.createConnection(payload);
  const readinessResponse = await api.liveSyncReadiness().catch(() => null);
  state.liveSyncReadiness = readinessResponse?.live_sync_readiness || null;
  state.currentSyncJobId = result.first_sync_job?.sync_job_id || null;
  renderConnectionResult(payload, result, state.liveSyncReadiness);
  await refreshConnections();
  if (result.first_sync_job?.sync_job_id) {
    pollSyncJob(result.first_sync_job.sync_job_id);
  }
  showToast("Connection ready. Checking sync status.");
}

async function refreshConnections() {
  const response = await api.listAccountConnections();
  state.connections = response.connections || [];
  renderConnections();
}

function buildConnectionPayload() {
  const source = selectedSource();
  if (!source) {
    return null;
  }
  const accounts = selectedSourceAccounts().filter((account) => state.selectedAccounts.has(account.id));
  const payload = {
    workspace_id: "workspace_demo",
    connector_id: source.id,
    authorization_id: `auth_${source.id}_demo`,
    client_name: accounts[0]?.name || "Onboarding Preview Client",
    accounts: accounts.map((account) => ({
      external_account_id: account.id,
      account_name: account.name,
    })),
    destinations: [...state.selectedDestinations],
  };

  if (state.selectedDestinations.has("ai_report_email")) {
    payload.report_schedule = {
      report_type: state.reportType,
      delivery_day: state.reportType === "monthly"
        ? Number(els.monthlyDeliveryDay.value || 1)
        : els.weeklyDeliveryDay.value,
      timezone: els.reportTimezone.value,
      depth: els.reportDepth.value,
    };
  }

  return payload;
}

function renderConnectionResult(payload, result, liveSyncReadiness) {
  const summary = result.config_preview.summary;
  const source = selectedSource();
  const selectedAccounts = selectedSourceAccounts().filter((account) => state.selectedAccounts.has(account.id));
  const destinationNames = destinations
    .filter((destination) => summary.destinations.includes(destination.id))
    .map((destination) => destination.name);
  els.connectionResult.hidden = false;
  els.connectionStatus.textContent = userSyncStatus(result.first_sync_job?.status || result.next_sync_status);
  els.handoffSummary.innerHTML = renderSelectedAccountPreview(source, selectedAccounts, summary);
  els.payloadPreview.textContent = JSON.stringify(sanitizePayloadForDisplay(payload), null, 2);
  els.nextActions.innerHTML = renderUserSetupPreview(
    result.destination_handoff,
    payload,
    selectedAccounts,
    destinationNames
  );
  els.developerStatus.innerHTML = renderDeveloperStatus(
    result.first_sync_job,
    result.local_config_export,
    liveSyncReadiness
  );
  els.configPreview.textContent = result.config_preview.yaml_text;
}

function renderConnections() {
  const connections = state.connections || [];
  els.connectionListCount.textContent = connections.length === 0
    ? "No connections"
    : `${connections.length} connected`;
  if (connections.length === 0) {
    els.connectionList.innerHTML = `<div class="empty-state">Finish setup to see connected account groups here.</div>`;
    return;
  }

  els.connectionList.innerHTML = connections
    .map((connection) => {
      const destinationNames = (connection.destinations || []).map(destinationLabel).join(", ");
      const reportSchedule = connection.report_schedule
        ? `${connection.report_schedule.report_type} · ${connection.report_schedule.timezone}`
        : "Not scheduled";
      return `
        <article class="connection-card">
          <div>
            <strong>${formatCount(connection.account_count)} account${connection.account_count === 1 ? "" : "s"}</strong>
            <span>${destinationNames || "No destinations"}</span>
          </div>
          <div>
            <span>Report</span>
            <strong>${reportSchedule}</strong>
          </div>
          <div>
            <span>Status</span>
            <strong>${connection.first_sync_job_id ? "Ready" : "Draft"}</strong>
          </div>
        </article>
      `;
    })
    .join("");
}

function clearConnectionResult() {
  stopSyncPolling();
  state.currentSyncJobId = null;
  state.liveSyncReadiness = null;
  els.connectionResult.hidden = true;
  els.connectionStatus.textContent = "Not queued";
  els.handoffSummary.innerHTML = "";
  els.payloadPreview.textContent = "";
  els.nextActions.innerHTML = "";
  els.developerStatus.innerHTML = "";
  els.configPreview.textContent = "";
}

function sanitizePayloadForDisplay(payload) {
  return {
    ...payload,
    authorization_id: "auth_redacted",
    accounts: (payload.accounts || []).map((account, index) => ({
      ...account,
      external_account_id: `selected_account_${String(index + 1).padStart(4, "0")}`,
    })),
  };
}

function renderSelectedAccountPreview(source, selectedAccounts, summary) {
  const accountList = selectedAccounts.length
    ? selectedAccounts
        .map((account) => {
          const meta = [account.currency, account.timezone].filter(Boolean).join(" · ");
          return `
            <li>
              <strong>${escapeHtml(account.name)}</strong>
              <span>${escapeHtml(meta || account.status || "Ready")}</span>
            </li>
          `;
        })
        .join("")
    : `<li><strong>${formatCount(summary.account_count)} account${summary.account_count === 1 ? "" : "s"}</strong><span>Selected</span></li>`;
  return `
    <div><span>Data source</span><strong>${escapeHtml(source?.label || "Meta Ads")} connected</strong></div>
    <div class="account-preview-card">
      <span>Selected ad accounts</span>
      <ul>${accountList}</ul>
    </div>
  `;
}

function renderUserSetupPreview(destinationHandoff, payload, selectedAccounts, destinationNames) {
  if (!destinationHandoff) {
    return `<p class="muted-copy">Finish setup to prepare your selected destinations.</p>`;
  }
  const destinationsMarkup = Object.entries(destinationHandoff.destinations || {})
    .map(([destinationId, handoff]) => {
      return `
        <article class="handoff-destination">
          <strong>${destinationLabel(destinationId)}</strong>
          <span>${userDestinationStatus(destinationId, handoff)}</span>
          <p>${userDestinationCopy(destinationId, handoff, payload)}</p>
        </article>
      `;
    })
    .join("");
  const accountNames = selectedAccounts.map((account) => account.name);
  const accountSummary = accountNames.length > 0
    ? accountNames.slice(0, 3).map(escapeHtml).join(", ") + (accountNames.length > 3 ? ` and ${accountNames.length - 3} more` : "")
    : "Selected ad accounts";
  return `
    <div class="handoff-destinations">${destinationsMarkup}</div>
    ${renderReportSchedulePreview(payload)}
    <div class="setup-next-step">
      <strong>What happens next</strong>
      <p>${accountSummary} is ready to import into ${escapeHtml(destinationNames.join(", ") || "the selected destinations")}. After the first data sync, dashboard and report outputs become available.</p>
    </div>
  `;
}

function renderDeveloperStatus(syncJob, localConfigExport, liveSyncReadiness) {
  return `
    ${renderSyncJob(syncJob)}
    ${renderLocalConfigExport(localConfigExport)}
    ${renderLiveSyncReadiness(liveSyncReadiness)}
  `;
}

function renderReportSchedulePreview(payload) {
  if (!payload.report_schedule) {
    return "";
  }
  const schedule = payload.report_schedule;
  const delivery = schedule.report_type === "weekly"
    ? `Every ${schedule.delivery_day}`
    : `Monthly on day ${schedule.delivery_day}`;
  return `
    <article class="report-preview-card">
      <div>
        <strong>AI report schedule</strong>
        <span>${escapeHtml(delivery)} · ${escapeHtml(schedule.timezone || "Asia/Taipei")}</span>
      </div>
      <small>${escapeHtml(schedule.depth || "standard")} depth</small>
    </article>
  `;
}

function renderLocalConfigExport(localConfigExport) {
  if (!localConfigExport) {
    return "";
  }
  const accountCount = Number(localConfigExport.account_count || 0);
  const exported = localConfigExport.status === "exported";
  const failed = localConfigExport.status === "failed";
  const status = exported ? "Ready" : failed ? "Needs attention" : "Unavailable";
  const path = localConfigExport.output_path
    ? `<code>${escapeHtml(localConfigExport.output_path)}</code>`
    : "Local sync file";
  const verb = exported ? "was generated" : "is not ready";
  return `
    <article class="handoff-destination local-sync-card ${exported ? "ready" : "pending"}">
      <strong>Local sync file</strong>
      <span>${status}</span>
      <p>${path} ${verb} for ${formatCount(accountCount)} selected account${accountCount === 1 ? "" : "s"}.</p>
    </article>
  `;
}

function renderLiveSyncReadiness(readiness) {
  if (!readiness) {
    return "";
  }
  const failedChecks = (readiness.checks || []).filter((check) => !check.ok);
  const summary = readiness.summary || {};
  const accountCount = Number(summary.enabled_meta_account_count || 0);
  const details = readiness.ready
    ? `${formatCount(accountCount)} selected Meta account${accountCount === 1 ? "" : "s"} ready for the guarded live sync path.`
    : failedChecks.slice(0, 3).map((check) => escapeHtml(readinessCheckLabel(check.id))).join(", ") || "Readiness has not passed yet.";
  return `
    <article class="handoff-destination local-sync-card ${readiness.ready ? "ready" : "pending"}">
      <strong>Live sync readiness</strong>
      <span>${readiness.ready ? "Passed" : "Needs attention"}</span>
      <p>${details}</p>
      ${readiness.writes_bigquery ? "<small>Next live sync writes to BigQuery.</small>" : ""}
    </article>
  `;
}

function renderSyncJob(syncJob) {
  if (!syncJob) {
    return "";
  }
  const stepsMarkup = (syncJob.steps || [])
    .map((step) => {
      return `
        <li class="${step.status}">
          <span>${step.label}</span>
          <strong>${syncStepLabel(step.status)}</strong>
        </li>
      `;
    })
    .join("");
  return `
    <div class="sync-status-card" id="syncStatusCard">
      <div class="sync-status-header">
        <div>
          <strong id="syncStatusTitle">${userSyncStatus(syncJob.status)}</strong>
          <span id="syncStatusMessage">${syncJob.message || ""}</span>
        </div>
        <span id="syncProgressText">${syncJob.progress_percent || 0}%</span>
      </div>
      <div class="sync-progress" aria-hidden="true">
        <span id="syncProgressBar" style="width: ${syncJob.progress_percent || 0}%"></span>
      </div>
      <ol class="sync-step-list" id="syncStepList">${stepsMarkup}</ol>
      <div id="syncExecutionStatus">${renderSyncExecution(syncJob.sync_execution)}</div>
      <div id="backendDataCheck">${renderBackendDataCheck(syncJob.backend_data_check)}</div>
      <div id="emailReportAction">${renderEmailReportAction(syncJob)}</div>
    </div>
  `;
}

function renderSyncExecution(syncExecution) {
  if (!syncExecution) {
    return "";
  }
  if (syncExecution.status === "success") {
    return `
      <div class="sync-execution success">
        <strong>Source data synced</strong>
        <span>${formatCount(syncExecution.account_count)} account${syncExecution.account_count === 1 ? "" : "s"} · ${syncExecution.runner || "sync runner"}</span>
      </div>
    `;
  }
  if (syncExecution.status === "failed") {
    return `
      <div class="sync-execution failed">
        <strong>Source sync failed</strong>
        <span>${syncExecution.message || "Unable to sync selected account data."}</span>
      </div>
    `;
  }
  return "";
}

function renderEmailReportAction(syncJob) {
  if (!syncJob || !(syncJob.summary?.destinations || []).includes("ai_report_email")) {
    return "";
  }
  const delivery = syncJob.email_delivery;
  if (delivery?.status === "sent") {
    return `
      <div class="email-action sent">
        <strong>Report email sent</strong>
        <span>${delivery.report_type || "monthly"} report · ${delivery.period_start_date || ""}</span>
      </div>
    `;
  }
  if (delivery?.status === "sending") {
    return `
      <div class="email-action sending">
        <strong>Sending report email</strong>
        <span>${delivery.message || "Please keep this page open."}</span>
      </div>
    `;
  }
  if (delivery?.status === "failed" || delivery?.status === "unavailable") {
    return `
      <div class="email-action failed">
        <strong>${emailDeliveryTitle(delivery.status)}</strong>
        <span>${delivery.message || "Unable to send report email."}</span>
      </div>
    `;
  }
  const disabled = syncJob.status === "completed" ? "" : "disabled";
  return `
    <div class="email-action">
      <div>
        <strong>AI report email</strong>
        <span>Send the latest report to the configured recipient.</span>
      </div>
      <button class="secondary-button" type="button" id="sendEmailButton" ${disabled}>Send report email</button>
    </div>
  `;
}

function renderBackendDataCheck(dataCheck) {
  if (!dataCheck) {
    return "";
  }
  const latest = dataCheck.latest_sync || {};
  const bigquery = dataCheck.destinations?.bigquery;
  const looker = dataCheck.destinations?.looker_studio;
  const scope = dataCheck.scope || {};
  return `
    <div class="backend-check ${dataCheck.status}">
      <div class="backend-check-header">
        <strong>${backendCheckTitle(dataCheck.status)}</strong>
        <span>${dataCheck.source || "backend"}</span>
      </div>
      <p>${dataCheck.message || ""}</p>
      <div class="backend-check-grid">
        <div>
          <span>Checked accounts</span>
          <strong>${formatCount(scope.selected_account_count)}</strong>
          <small>${scope.selected_accounts_scoped ? "selected scope" : "latest sync scope"}</small>
        </div>
        <div>
          <span>Latest sync</span>
          <strong>${latest.status || "unknown"}</strong>
          <small>${backendSyncPeriod(latest)}</small>
        </div>
        <div>
          <span>Rows synced</span>
          <strong>${formatCount(latest.rows_inserted)}</strong>
          <small>${formatCount(latest.rows_fetched)} fetched</small>
        </div>
        <div>
          <span>BigQuery</span>
          <strong>${bigquery?.status || "not checked"}</strong>
          <small>${formatCount(bigquery?.unified_rows)} unified rows</small>
        </div>
        <div>
          <span>Dashboard views</span>
          <strong>${looker?.status || "not checked"}</strong>
          <small>${formatCount(looker?.campaign_daily_rows)} campaign rows</small>
        </div>
      </div>
    </div>
  `;
}

function destinationLabel(destinationId) {
  const destination = destinations.find((item) => item.id === destinationId);
  return destination?.name || destinationId;
}

function userSyncStatus(status) {
  if (status === "queued") {
    return "First sync queued";
  }
  if (status === "running") {
    return "Syncing data";
  }
  if (status === "ready_for_sync") {
    return "Setup ready";
  }
  if (status === "completed") {
    return "Sync completed";
  }
  if (status === "failed") {
    return "Sync failed";
  }
  return status || "Ready";
}

function syncStepLabel(status) {
  return {
    completed: "Done",
    failed: "Failed",
    running: "Running",
    queued: "Waiting",
    ready_for_sync: "Ready",
  }[status] || status;
}

async function pollSyncJob(syncJobId) {
  try {
    const response = await api.getSyncJob(syncJobId);
    updateSyncJob(response.sync_job);
    if (!["completed", "failed", "ready_for_sync"].includes(response.sync_job.status)) {
      state.syncPollTimer = window.setTimeout(() => pollSyncJob(syncJobId), 1100);
    } else if (response.sync_job.status === "completed") {
      showToast("First sync completed.");
    } else if (response.sync_job.status === "ready_for_sync") {
      showToast("Setup ready for live sync.");
    } else {
      showToast("First sync failed.");
    }
  } catch (error) {
    showToast(error.message || "Unable to load sync status.");
  }
}

function updateSyncJob(syncJob) {
  const title = document.querySelector("#syncStatusTitle");
  const message = document.querySelector("#syncStatusMessage");
  const progressText = document.querySelector("#syncProgressText");
  const progressBar = document.querySelector("#syncProgressBar");
  const stepList = document.querySelector("#syncStepList");
  const summary = document.querySelector("#firstSyncSummary");
  if (summary) {
    summary.textContent = userSyncStatus(syncJob.status);
  }
  els.connectionStatus.textContent = userSyncStatus(syncJob.status);
  if (title) {
    title.textContent = userSyncStatus(syncJob.status);
  }
  if (message) {
    message.textContent = syncJob.message || "";
  }
  if (progressText) {
    progressText.textContent = `${syncJob.progress_percent || 0}%`;
  }
  if (progressBar) {
    progressBar.style.width = `${syncJob.progress_percent || 0}%`;
  }
  if (stepList) {
    stepList.innerHTML = (syncJob.steps || [])
      .map((step) => {
        return `
          <li class="${step.status}">
            <span>${step.label}</span>
            <strong>${syncStepLabel(step.status)}</strong>
          </li>
        `;
      })
      .join("");
  }
  const backendDataCheck = document.querySelector("#backendDataCheck");
  if (backendDataCheck) {
    backendDataCheck.innerHTML = renderBackendDataCheck(syncJob.backend_data_check);
  }
  const syncExecutionStatus = document.querySelector("#syncExecutionStatus");
  if (syncExecutionStatus) {
    syncExecutionStatus.innerHTML = renderSyncExecution(syncJob.sync_execution);
  }
  const emailReportAction = document.querySelector("#emailReportAction");
  if (emailReportAction) {
    emailReportAction.innerHTML = renderEmailReportAction(syncJob);
  }
}

function stopSyncPolling() {
  if (state.syncPollTimer) {
    window.clearTimeout(state.syncPollTimer);
    state.syncPollTimer = null;
  }
}

async function sendReportEmail() {
  if (!state.currentSyncJobId) {
    showToast("No sync job is ready for email.");
    return;
  }
  const button = document.querySelector("#sendEmailButton");
  if (button) {
    button.disabled = true;
    button.textContent = "Sending...";
  }
  try {
    const response = await api.sendReportEmail(state.currentSyncJobId);
    const emailReportAction = document.querySelector("#emailReportAction");
    if (emailReportAction) {
      emailReportAction.innerHTML = renderEmailReportAction({
        status: "completed",
        summary: { destinations: ["ai_report_email"] },
        email_delivery: response.email_delivery,
      });
    }
    showToast(response.ok ? "Report email sent." : response.email_delivery?.message || "Report email unavailable.");
  } catch (error) {
    showToast(error.message || "Unable to send report email.");
    if (button) {
      button.disabled = false;
      button.textContent = "Send report email";
    }
  }
}

function emailDeliveryTitle(status) {
  if (status === "unavailable") {
    return "Email sending unavailable";
  }
  return "Report email failed";
}

function userDestinationStatus(destinationId, handoff) {
  if (destinationId === "looker_studio" && handoff.status === "handoff_required") {
    return "Dashboard pending";
  }
  if (destinationId === "ai_report_email") {
    return "Report schedule ready";
  }
  if (destinationId === "bigquery") {
    return "Warehouse ready";
  }
  if (handoff.status === "not_productized") {
    return "Coming soon";
  }
  return "Ready";
}

function backendCheckTitle(status) {
  if (status === "healthy") {
    return "Backend data verified";
  }
  if (status === "no_data") {
    return "No synced data yet";
  }
  if (status === "unavailable") {
    return "Backend check unavailable";
  }
  return "Backend data check";
}

function backendSyncPeriod(latest) {
  if (!latest?.sync_start_date || !latest?.sync_end_date) {
    return "No period available";
  }
  if (latest.sync_start_date === latest.sync_end_date) {
    return latest.sync_start_date;
  }
  return `${latest.sync_start_date} to ${latest.sync_end_date}`;
}

function formatCount(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "0";
  }
  return Number(value).toLocaleString("en-US");
}

function readinessCheckLabel(checkId) {
  return {
    local_sync_explicitly_enabled: "Local sync mode",
    local_config_export_path_configured: "Local sync file path",
    local_config_artifact_exists: "Local sync file",
    local_config_artifact_valid: "Local sync file validation",
    enabled_meta_accounts_present: "Selected Meta accounts",
    meta_access_token_configured: "Meta access token",
    bigquery_project_configured: "BigQuery project",
    bigquery_dataset_configured: "BigQuery dataset",
    sync_platform_filter_allows_meta: "Meta sync filter",
  }[checkId] || checkId || "Readiness check";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function userDestinationCopy(destinationId, handoff, payload) {
  if (destinationId === "looker_studio") {
    return "Your dashboard can be opened after the first data sync finishes.";
  }
  if (destinationId === "ai_report_email") {
    const schedule = payload.report_schedule || handoff;
    return `AI reports are set to ${schedule.report_type || "monthly"} delivery in ${schedule.timezone || "Asia/Taipei"}.`;
  }
  if (destinationId === "bigquery") {
    return "Selected ad account data will sync into the reporting warehouse.";
  }
  if (destinationId === "google_sheets") {
    return "Google Sheets export is not enabled in this MVP yet.";
  }
  return "This destination is ready after the first sync.";
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.classList.remove("show");
  }, 2200);
}

function bindEvents() {
  els.platformSearch.addEventListener("input", renderSources);
  els.connectedOnly.addEventListener("change", renderSources);
  els.accountSearch.addEventListener("input", renderAccounts);
  els.selectAllAccountsButton.addEventListener("click", selectAllVisibleAccounts);
  els.accountMasterCheckbox.addEventListener("change", () => {
    if (els.accountMasterCheckbox.checked) {
      selectAllVisibleAccounts();
    } else {
      visibleAccounts().forEach((account) => state.selectedAccounts.delete(account.id));
      renderAccounts();
      renderStepper();
      renderSummary();
    }
  });
  els.connectButton.addEventListener("click", () => {
    const source = selectedSource();
    if (source && isAvailable(source)) {
      openAuthModal(source);
    }
  });
  els.closeAuthButton.addEventListener("click", closeAuthModal);
  els.authModal.addEventListener("click", (event) => {
    if (event.target === els.authModal) {
      closeAuthModal();
    }
  });
  els.grantAccessButton.addEventListener("click", completeAuthorization);
  els.resetButton.addEventListener("click", resetDemo);
  els.finishButton.addEventListener("click", createConnection);
  document.addEventListener("click", (event) => {
    if (event.target?.id === "sendEmailButton") {
      sendReportEmail();
    }
  });

  document.querySelectorAll("[data-report-type]").forEach((button) => {
    button.addEventListener("click", () => {
      state.reportType = button.dataset.reportType;
      clearConnectionResult();
      renderEmailSettings();
      renderSummary();
    });
  });

  [els.monthlyDeliveryDay, els.weeklyDeliveryDay, els.reportDepth, els.reportTimezone].forEach((input) => {
    input.addEventListener("change", clearConnectionResult);
    input.addEventListener("input", clearConnectionResult);
  });

  document.querySelectorAll("[data-category]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.destinationCategory = tab.dataset.category;
      document.querySelectorAll("[data-category]").forEach((item) => {
        item.classList.toggle("active", item === tab);
      });
      renderDestinations();
    });
  });
}

async function init() {
  bindEvents();
  els.runtimePill.textContent = api.mode();
  await hydrateData();
  renderAll();
}

init();
