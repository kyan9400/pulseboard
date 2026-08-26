const state = {
  monitors: [],
  incidents: [],
  refreshing: false,
};

const elements = {
  addButton: document.querySelector("#add-button"),
  emptyAddButton: document.querySelector("#empty-add-button"),
  refreshButton: document.querySelector("#refresh-button"),
  settingsButton: document.querySelector("#settings-button"),
  clearKeyButton: document.querySelector("#clear-key-button"),
  monitorDialog: document.querySelector("#monitor-dialog"),
  settingsDialog: document.querySelector("#settings-dialog"),
  monitorForm: document.querySelector("#monitor-form"),
  settingsForm: document.querySelector("#settings-form"),
  apiKey: document.querySelector("#api-key"),
  formError: document.querySelector("#monitor-form-error"),
  monitorGrid: document.querySelector("#monitor-grid"),
  monitorEmpty: document.querySelector("#monitor-empty"),
  incidentList: document.querySelector("#incident-list"),
  incidentEmpty: document.querySelector("#incident-empty"),
  monitorCount: document.querySelector("#monitor-count"),
  overallDot: document.querySelector("#overall-dot"),
  overallLabel: document.querySelector("#overall-label"),
  lastUpdated: document.querySelector("#last-updated"),
  metricTotal: document.querySelector("#metric-total"),
  metricUp: document.querySelector("#metric-up"),
  metricDown: document.querySelector("#metric-down"),
  metricLatency: document.querySelector("#metric-latency"),
  toast: document.querySelector("#toast"),
};

function accessKey() {
  return sessionStorage.getItem("pulseboard-api-key") || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const key = accessKey();
  if (key) headers.set("X-API-Key", key);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    elements.apiKey.value = key;
    elements.settingsDialog.showModal();
    throw new Error("Write access requires a valid API key.");
  }
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch (_error) {
      // The HTTP status remains the useful fallback.
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 3600);
}

function formatDuration(value) {
  if (value === null || value === undefined) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${Math.round(value)} ms`;
}

function formatUptime(value) {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)}%`;
}

function formatMoment(value) {
  if (!value) return "No checks yet";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function statusLabel(status) {
  return {
    up: "Operational",
    down: "Attention",
    pending: "Pending",
    paused: "Paused",
  }[status];
}

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function buildMonitorCard(monitor, index) {
  const article = document.createElement("article");
  article.className = "monitor-card";
  article.dataset.status = monitor.current_status;

  const main = document.createElement("div");
  main.className = "card-main";
  const topline = document.createElement("div");
  topline.className = "card-topline";
  topline.append(textElement("span", "card-sequence", `NODE ${String(index + 1).padStart(2, "0")}`));

  const chip = textElement("span", `status-chip ${monitor.current_status}`, "");
  chip.append(textElement("i", `signal-dot ${monitor.current_status}`, ""));
  chip.append(document.createTextNode(statusLabel(monitor.current_status)));
  topline.append(chip);
  main.append(topline);

  main.append(textElement("h3", "", monitor.name));
  const link = textElement("a", "monitor-url", monitor.url);
  link.href = monitor.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.title = monitor.url;
  main.append(link);

  const telemetry = document.createElement("div");
  telemetry.className = "telemetry";
  const uptime = document.createElement("div");
  uptime.append(textElement("span", "", "24h uptime"));
  uptime.append(textElement("strong", "", formatUptime(monitor.uptime_24h)));
  const latency = document.createElement("div");
  latency.append(textElement("span", "", "Last latency"));
  latency.append(textElement("strong", "", formatDuration(monitor.last_check?.duration_ms)));
  telemetry.append(uptime, latency);
  main.append(telemetry);
  article.append(main);

  const footer = document.createElement("div");
  footer.className = "card-footer";
  footer.append(textElement("span", "", formatMoment(monitor.last_check?.checked_at)));
  const actions = document.createElement("div");
  actions.className = "card-actions";
  const check = textElement("button", "card-action", "Check");
  check.type = "button";
  check.addEventListener("click", () => checkNow(monitor.id, check));
  const toggle = textElement("button", "card-action", monitor.active ? "Pause" : "Resume");
  toggle.type = "button";
  toggle.addEventListener("click", () => toggleMonitor(monitor));
  const remove = textElement("button", "card-action danger", "Remove");
  remove.type = "button";
  remove.addEventListener("click", () => removeMonitor(monitor));
  actions.append(check, toggle, remove);
  footer.append(actions);
  article.append(footer);
  return article;
}

function renderMonitors() {
  elements.monitorGrid.replaceChildren();
  state.monitors.forEach((monitor, index) => {
    elements.monitorGrid.append(buildMonitorCard(monitor, index));
  });
  elements.monitorEmpty.hidden = state.monitors.length !== 0;
  elements.monitorCount.textContent = `${state.monitors.length} ${state.monitors.length === 1 ? "record" : "records"}`;
}

function renderIncidents() {
  elements.incidentList.replaceChildren();
  state.incidents.forEach((incident) => {
    const row = document.createElement("article");
    row.className = "incident-row";
    row.append(textElement("span", `incident-mark${incident.resolved_at ? " resolved" : ""}`, ""));
    const body = document.createElement("div");
    body.className = "incident-body";
    body.append(textElement("strong", "", incident.monitor_name));
    body.append(textElement("span", "", incident.cause));
    const meta = document.createElement("div");
    meta.className = "incident-meta";
    meta.append(textElement("strong", "", incident.resolved_at ? "Resolved" : "Open"));
    meta.append(textElement("span", "", formatMoment(incident.resolved_at || incident.started_at)));
    row.append(body, meta);
    elements.incidentList.append(row);
  });
  elements.incidentEmpty.hidden = state.incidents.length !== 0;
}

function renderMetrics() {
  const up = state.monitors.filter((monitor) => monitor.current_status === "up").length;
  const down = state.monitors.filter((monitor) => monitor.current_status === "down").length;
  const latencies = state.monitors
    .map((monitor) => monitor.last_check?.duration_ms)
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
  let median = null;
  if (latencies.length) {
    const middle = Math.floor(latencies.length / 2);
    median = latencies.length % 2 ? latencies[middle] : (latencies[middle - 1] + latencies[middle]) / 2;
  }
  elements.metricTotal.textContent = state.monitors.length;
  elements.metricUp.textContent = up;
  elements.metricDown.textContent = down;
  elements.metricLatency.textContent = formatDuration(median);

  let overall = "pending";
  let label = "Awaiting signal";
  if (down) {
    overall = "down";
    label = "Service degraded";
  } else if (up) {
    overall = "up";
    label = "All systems nominal";
  }
  elements.overallDot.className = `signal-dot ${overall}`;
  elements.overallLabel.textContent = label;
}

async function refreshData({ quiet = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  elements.refreshButton.disabled = true;
  try {
    [state.monitors, state.incidents] = await Promise.all([
      api("/api/monitors"),
      api("/api/incidents?limit=20"),
    ]);
    renderMetrics();
    renderMonitors();
    renderIncidents();
    elements.lastUpdated.textContent = `${formatMoment(new Date().toISOString())} UTC`;
  } catch (error) {
    if (!quiet) showToast(error.message);
  } finally {
    state.refreshing = false;
    elements.refreshButton.disabled = false;
  }
}

async function checkNow(monitorId, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Running";
  try {
    await api(`/api/monitors/${monitorId}/checks`, { method: "POST" });
    await refreshData();
    showToast("Fresh availability check recorded.");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function toggleMonitor(monitor) {
  try {
    await api(`/api/monitors/${monitor.id}`, {
      method: "PATCH",
      body: JSON.stringify({ active: !monitor.active }),
    });
    await refreshData();
    showToast(monitor.active ? `${monitor.name} paused.` : `${monitor.name} resumed.`);
  } catch (error) {
    showToast(error.message);
  }
}

async function removeMonitor(monitor) {
  if (!window.confirm(`Remove ${monitor.name} and its check history?`)) return;
  try {
    await api(`/api/monitors/${monitor.id}`, { method: "DELETE" });
    await refreshData();
    showToast(`${monitor.name} removed.`);
  } catch (error) {
    showToast(error.message);
  }
}

function openMonitorDialog() {
  elements.formError.textContent = "";
  elements.monitorDialog.showModal();
  window.setTimeout(() => elements.monitorForm.elements.name.focus(), 0);
}

elements.monitorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.formError.textContent = "";
  const submit = elements.monitorForm.querySelector('[type="submit"]');
  submit.disabled = true;
  const form = new FormData(elements.monitorForm);
  const payload = {
    name: form.get("name"),
    url: form.get("url"),
    method: form.get("method"),
    interval_seconds: Number(form.get("interval_seconds")),
    timeout_seconds: Number(form.get("timeout_seconds")),
    expected_status_min: Number(form.get("expected_status_min")),
    expected_status_max: Number(form.get("expected_status_max")),
  };
  try {
    const monitor = await api("/api/monitors", { method: "POST", body: JSON.stringify(payload) });
    await api(`/api/monitors/${monitor.id}/checks`, { method: "POST" });
    elements.monitorForm.reset();
    elements.monitorDialog.close();
    await refreshData();
    showToast(`${monitor.name} is now monitored.`);
  } catch (error) {
    elements.formError.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

elements.settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const key = elements.apiKey.value.trim();
  if (key) sessionStorage.setItem("pulseboard-api-key", key);
  else sessionStorage.removeItem("pulseboard-api-key");
  elements.settingsDialog.close();
  showToast(key ? "Access key enabled for this tab." : "Access key cleared.");
});

elements.clearKeyButton.addEventListener("click", () => {
  sessionStorage.removeItem("pulseboard-api-key");
  elements.apiKey.value = "";
  elements.settingsDialog.close();
  showToast("Access key cleared.");
});

elements.addButton.addEventListener("click", openMonitorDialog);
elements.emptyAddButton.addEventListener("click", openMonitorDialog);
elements.refreshButton.addEventListener("click", () => refreshData());
elements.settingsButton.addEventListener("click", () => {
  elements.apiKey.value = accessKey();
  elements.settingsDialog.showModal();
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.closeDialog}`).close());
});

[elements.monitorDialog, elements.settingsDialog].forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

refreshData();
window.setInterval(() => refreshData({ quiet: true }), 30_000);
