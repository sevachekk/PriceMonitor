const state = {
  token: localStorage.getItem("pm_admin_token") || "",
  apiBaseUrl: deriveApiBaseUrl(),
  currentUser: null,
  section: "dashboard",
  datasets: {
    dashboard: null,
    sources: [],
    jobs: [],
    alerts: [],
    logs: [],
    users: [],
    settings: [],
    backups: [],
  },
  views: {
    sources: { query: "", page: 1, pageSize: 8 },
    jobs: { query: "", page: 1, pageSize: 8 },
    alerts: { query: "", page: 1, pageSize: 8 },
    logs: { query: "", page: 1, pageSize: 12 },
    users: { query: "", page: 1, pageSize: 8 },
    settings: { query: "", page: 1, pageSize: 8 },
    backups: { query: "", page: 1, pageSize: 8 },
  },
};

const sectionTitles = {
  dashboard: "Обзор",
  sources: "Источники",
  jobs: "Задания",
  alerts: "Правила",
  logs: "Логи",
  users: "Пользователи",
  settings: "Платформа",
};

const elements = {};

function normalizeApiBaseUrl(value) {
  const normalized = String(value || "").trim();
  return normalized.replace(/\/+$/, "");
}

function deriveApiBaseUrl() {
  const configured = normalizeApiBaseUrl(
    (window.ADMIN_CONSOLE_CONFIG && window.ADMIN_CONSOLE_CONFIG.apiBaseUrl) || "",
  );
  if (configured) {
    return configured;
  }
  if (window.location.protocol.startsWith("http")) {
    if (window.location.port === "8081") {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return "";
  }
  return "http://localhost:8000";
}

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  bootstrapFromConfig();
});

function cacheElements() {
  elements.loginView = document.getElementById("loginView");
  elements.appView = document.getElementById("appView");
  elements.loginForm = document.getElementById("loginForm");
  elements.consoleTitle = document.getElementById("consoleTitle");
  elements.currentUserName = document.getElementById("currentUserName");
  elements.currentUserRole = document.getElementById("currentUserRole");
  elements.sectionTitle = document.getElementById("sectionTitle");
  elements.toast = document.getElementById("toast");
  elements.dashboardStats = document.getElementById("dashboardStats");
  elements.dashboardLogs = document.getElementById("dashboardLogs");
  elements.sourcesTable = document.getElementById("sourcesTable");
  elements.jobsTable = document.getElementById("jobsTable");
  elements.alertsTable = document.getElementById("alertsTable");
  elements.logsTable = document.getElementById("logsTable");
  elements.usersTable = document.getElementById("usersTable");
  elements.settingsTable = document.getElementById("settingsTable");
  elements.backupsTable = document.getElementById("backupsTable");
  elements.logsLimit = document.getElementById("logsLimit");
  elements.logDetailsModal = document.getElementById("logDetailsModal");
  elements.logDetailsContent = document.getElementById("logDetailsContent");
  elements.closeLogDetailsModalButton = document.getElementById("closeLogDetailsModalButton");
  elements.sourceForm = document.getElementById("sourceForm");
  elements.jobForm = document.getElementById("jobForm");
  elements.jobAlertPicker = document.getElementById("jobAlertPicker");
  elements.alertForm = document.getElementById("alertForm");
  elements.userForm = document.getElementById("userForm");
  elements.settingForm = document.getElementById("settingForm");
  elements.sections = {
    dashboard: document.getElementById("dashboardSection"),
    sources: document.getElementById("sourcesSection"),
    jobs: document.getElementById("jobsSection"),
    alerts: document.getElementById("alertsSection"),
    logs: document.getElementById("logsSection"),
    users: document.getElementById("usersSection"),
    settings: document.getElementById("settingsSection"),
  };
}

function bindEvents() {
  elements.loginForm.addEventListener("submit", handleLogin);
  elements.sourceForm.addEventListener("submit", submitSourceForm);
  elements.jobForm.addEventListener("submit", submitJobForm);
  elements.alertForm.addEventListener("submit", submitAlertForm);
  elements.userForm.addEventListener("submit", submitUserForm);
  elements.settingForm.addEventListener("submit", submitSettingForm);

  document.getElementById("refreshButton").addEventListener("click", (event) =>
    safeRun(refreshActiveSection, event.currentTarget, "Обновляем..."),
  );
  document.getElementById("logoutButton").addEventListener("click", logout);
  document.getElementById("reloadLogsButton").addEventListener("click", (event) =>
    safeRun(loadLogs, event.currentTarget, "Загружаем..."),
  );
  document.getElementById("exportLogsButton").addEventListener("click", (event) =>
    safeRun(exportLogs, event.currentTarget, "Готовим..."),
  );
  document.getElementById("createBackupButton").addEventListener("click", (event) =>
    safeRun(createBackup, event.currentTarget, "Создаём..."),
  );
  elements.closeLogDetailsModalButton.addEventListener("click", closeLogDetailsModal);
  elements.logDetailsModal.addEventListener("click", (event) => {
    if (event.target === elements.logDetailsModal) {
      closeLogDetailsModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.logDetailsModal.classList.contains("hidden")) {
      closeLogDetailsModal();
    }
  });

  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      safeRun(async () => setSection(button.dataset.section));
    });
  });

  document.querySelectorAll("[data-reset-form]").forEach((button) => {
    button.addEventListener("click", () => resetForm(button.dataset.resetForm));
  });
}

async function bootstrapFromConfig() {
  elements.consoleTitle.textContent =
    (window.ADMIN_CONSOLE_CONFIG && window.ADMIN_CONSOLE_CONFIG.appTitle) ||
    "Панель управления Price Monitor";

  if (!state.token) {
    showLogin();
    return;
  }

  try {
    await initializeSession();
  } catch (error) {
    logout();
    toast(error.message || "Сессия истекла, войдите снова.", "error");
  }
}

async function initializeSession() {
  const me = await api("/admin-api/auth/me");
  state.currentUser = me;
  showApp();
  applyRoleVisibility();
  renderUserIdentity();
  setSection(state.section);

  const startupTasks = [
    { label: "обзор", run: loadDashboard },
    { label: "источники", run: loadSources },
    { label: "задания", run: loadJobs },
    { label: "правила", run: loadAlerts },
    { label: "логи", run: loadLogs },
  ];

  if (isSuperAdmin()) {
    startupTasks.push(
      { label: "пользователи", run: loadUsers },
      { label: "платформа", run: loadSettings },
    );
  }

  const results = await Promise.allSettled(startupTasks.map((task) => task.run()));
  const failedSections = results
    .map((result, index) => ({ result, label: startupTasks[index].label }))
    .filter(({ result }) => result.status === "rejected");

  if (failedSections.length) {
    console.error(
      "Admin console startup partially failed",
      failedSections.map(({ label, result }) => ({
        section: label,
        error: result.reason,
      })),
    );
    toast(
      `Вход выполнен, но не удалось загрузить: ${failedSections.map(({ label }) => label).join(", ")}.`,
      "error",
    );
    updateStatus("Панель загружена частично");
    return;
  }

  updateStatus("Панель готова к работе");
}

async function handleLogin(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  const formData = new FormData(event.currentTarget);
  updateStatus("Выполняем вход...");

  const payload = {
    username: String(formData.get("username") || "").trim(),
    password: String(formData.get("password") || ""),
  };

  setButtonLoading(submitButton, true, "Входим...");
  try {
    const response = await api("/admin-api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
      skipAuth: true,
    });
    state.token = response.access_token;
    localStorage.setItem("pm_admin_token", state.token);
    await initializeSession();
    toast("Авторизация выполнена.", "success");
  } catch (error) {
    toast(error.message || "Не удалось авторизоваться.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

function showLogin() {
  elements.loginView.classList.remove("hidden");
  elements.appView.classList.add("hidden");
  updateStatus("Ожидание авторизации");
}

function showApp() {
  elements.loginView.classList.add("hidden");
  elements.appView.classList.remove("hidden");
}

function logout() {
  state.token = "";
  state.currentUser = null;
  localStorage.removeItem("pm_admin_token");
  showLogin();
}

function isSuperAdmin() {
  return state.currentUser && state.currentUser.role === "super_admin";
}

function applyRoleVisibility() {
  document.querySelectorAll(".super-admin-only").forEach((node) => {
    node.classList.toggle("hidden", !isSuperAdmin());
  });

  if (!isSuperAdmin() && (state.section === "users" || state.section === "settings")) {
    state.section = "dashboard";
  }
}

function renderUserIdentity() {
  elements.currentUserName.textContent =
    state.currentUser.full_name || state.currentUser.username;
  elements.currentUserRole.textContent = formatRole(state.currentUser.role);
}

function setSection(section) {
  state.section = section;
  Object.entries(elements.sections).forEach(([key, sectionEl]) => {
    sectionEl.classList.toggle("hidden", key !== section);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === section);
  });
  elements.sectionTitle.textContent = sectionTitles[section] || "Панель";
  updateStatus(`Раздел: ${elements.sectionTitle.textContent}`);
}

async function refreshActiveSection() {
  switch (state.section) {
    case "dashboard":
      await loadDashboard();
      break;
    case "sources":
      await loadSources();
      break;
    case "jobs":
      await loadJobs();
      break;
    case "alerts":
      await loadAlerts();
      break;
    case "logs":
      await loadLogs();
      break;
    case "users":
      await loadUsers();
      break;
    case "settings":
      await loadSettings();
      break;
    case "backups":
      renderBackupsTable();
      break;
    default:
      await loadDashboard();
  }
}

async function api(path, options = {}) {
  const url = `${state.apiBaseUrl}${path}`;
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(options.headers || {}),
  };

  if (state.apiBaseUrl.includes("ngrok")) {
    headers["ngrok-skip-browser-warning"] = "true";
  }

  if (!options.skipAuth && state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(url, {
    method: options.method || "GET",
    headers,
    body: options.body,
  });

  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = { raw: text };
    }
  }

  if (
    typeof data.raw === "string" &&
    /ngrok|browser warning|visit site/i.test(data.raw)
  ) {
    throw new Error("Ngrok вернул страницу-предупреждение вместо API-ответа.");
  }

  if (!response.ok) {
    throw new Error(data.detail || data.text || data.raw || `HTTP ${response.status}`);
  }
  return data;
}

async function loadDashboard() {
  updateStatus("Загружаем обзор...");
  state.datasets.dashboard = await api("/admin-api/dashboard");
  renderDashboard();
}

function renderDashboard() {
  const dashboard = state.datasets.dashboard;
  if (!dashboard) {
    return;
  }

  const stats = [
    ["Источники", dashboard.sources_total],
    ["Задания", dashboard.jobs_total],
    ["Правила", dashboard.alerts_total],
    ["Пользователи", dashboard.users_total],
    ["Блокировки", dashboard.blocked_sources_total],
  ];

  elements.dashboardStats.innerHTML = stats
    .map(
      ([label, value]) => `
        <article class="stat-card">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </article>
      `,
    )
    .join("");

  elements.dashboardLogs.innerHTML = renderCompactLogsTable(dashboard.last_job_runs || []);
  updateStatus("Обзор обновлён");
}

function getViewState(sectionKey) {
  return state.views[sectionKey];
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLowerCase();
}

function buildSearchBlob(parts) {
  return normalizeSearchText(
    parts
      .flatMap((part) => {
        if (part === null || part === undefined) return [];
        if (Array.isArray(part)) return part;
        if (typeof part === "object") return [JSON.stringify(part)];
        return [part];
      })
      .join(" "),
  );
}

function buildPaginationButtons(sectionKey, currentPage, totalPages) {
  if (totalPages <= 1) {
    return "";
  }

  const pages = [];
  for (let page = 1; page <= totalPages; page += 1) {
    pages.push(`
      <button
        class="pagination-button ${page === currentPage ? "active" : ""}"
        type="button"
        onclick="changeCollectionPage('${sectionKey}', ${page})"
      >
        ${page}
      </button>
    `);
  }

  return `
    <div class="table-pagination">
      <button
        class="pagination-button"
        type="button"
        onclick="changeCollectionPage('${sectionKey}', ${currentPage - 1})"
        ${currentPage === 1 ? "disabled" : ""}
      >
        Назад
      </button>
      <div class="pagination-pages">${pages.join("")}</div>
      <button
        class="pagination-button"
        type="button"
        onclick="changeCollectionPage('${sectionKey}', ${currentPage + 1})"
        ${currentPage === totalPages ? "disabled" : ""}
      >
        Вперёд
      </button>
    </div>
  `;
}

function captureSearchFocus(host) {
  const activeElement = document.activeElement;
  if (!activeElement || !host.contains(activeElement) || !activeElement.matches('input[type="search"]')) {
    return null;
  }

  return {
    start: typeof activeElement.selectionStart === "number" ? activeElement.selectionStart : activeElement.value.length,
    end: typeof activeElement.selectionEnd === "number" ? activeElement.selectionEnd : activeElement.value.length,
  };
}

function restoreSearchFocus(host, focusState) {
  if (!focusState) {
    return;
  }

  const searchInput = host.querySelector('input[type="search"]');
  if (!searchInput) {
    return;
  }

  searchInput.focus();
  if (typeof searchInput.setSelectionRange === "function") {
    const maxPosition = searchInput.value.length;
    searchInput.setSelectionRange(
      Math.min(focusState.start, maxPosition),
      Math.min(focusState.end, maxPosition),
    );
  }
}

function setHostHtmlPreservingSearchFocus(host, html) {
  const focusState = captureSearchFocus(host);
  host.innerHTML = html;
  restoreSearchFocus(host, focusState);
}

function renderPaginatedTable({
  sectionKey,
  host,
  headers,
  items,
  rowBuilder,
  searchBuilder,
  searchPlaceholder,
}) {
  const view = getViewState(sectionKey);
  const query = normalizeSearchText(view.query);
  const filteredItems = query
    ? items.filter((item) => searchBuilder(item).includes(query))
    : items;

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / view.pageSize));
  if (view.page > totalPages) {
    view.page = totalPages;
  }

  const startIndex = (view.page - 1) * view.pageSize;
  const pagedItems = filteredItems.slice(startIndex, startIndex + view.pageSize);
  const rows = pagedItems.map((item) => rowBuilder(item));
  const summaryText = filteredItems.length
    ? `Показано ${pagedItems.length} из ${filteredItems.length}`
    : query
      ? "Ничего не найдено"
      : "Нет данных";

  setHostHtmlPreservingSearchFocus(host, `
    <div class="table-toolbar">
      <label class="table-search">
        <span>Поиск</span>
        <input
          type="search"
          value="${escapeHtml(view.query)}"
          placeholder="${escapeHtml(searchPlaceholder)}"
          oninput="updateCollectionSearch('${sectionKey}', this.value)"
        />
      </label>
      <div class="table-summary">${escapeHtml(summaryText)}</div>
    </div>
    ${renderTable(headers, rows, query ? "Ничего не найдено" : "Нет данных")}
    ${buildPaginationButtons(sectionKey, view.page, totalPages)}
  `);
}

function rerenderSectionTable(sectionKey) {
  switch (sectionKey) {
    case "sources":
      renderSourcesTable();
      break;
    case "jobs":
      renderJobsTable();
      break;
    case "alerts":
      renderAlertsTable();
      break;
    case "logs":
      setHostHtmlPreservingSearchFocus(elements.logsTable, renderLogsTable(state.datasets.logs));
      if (state.datasets.dashboard) {
        elements.dashboardLogs.innerHTML = renderCompactLogsTable((state.datasets.dashboard.last_job_runs || []).slice(0, 5));
      }
      break;
    case "users":
      renderUsersTable();
      break;
    case "settings":
      renderSettingsTable();
      break;
    case "backups":
      renderBackupsTable();
      break;
    default:
      break;
  }
}

window.updateCollectionSearch = function updateCollectionSearch(sectionKey, value) {
  const view = getViewState(sectionKey);
  view.query = value;
  view.page = 1;
  rerenderSectionTable(sectionKey);
};

window.changeCollectionPage = function changeCollectionPage(sectionKey, nextPage) {
  const view = getViewState(sectionKey);
  view.page = Math.max(1, nextPage);
  rerenderSectionTable(sectionKey);
};

function formatAlertShort(alert) {
  const target = [alert.product_id ? `Товар ${alert.product_id}` : null, alert.competitor_id ? `Конкурент ${alert.competitor_id}` : "Все конкуренты"]
    .filter(Boolean)
    .join(" • ");
  return `#${alert.id} • ${alert.type} • ${target}`;
}

function formatJobAlertList(alertIds) {
  if (!Array.isArray(alertIds) || !alertIds.length) {
    return "Все активные";
  }

  const labels = alertIds.map((alertId) => {
    const alert = getAlertById(alertId);
    return alert ? formatAlertShort(alert) : `#${alertId}`;
  });

  return rawHtml(`
    <div class="stacked-tags">
      ${labels.map((label) => `<span class="inline-tag">${escapeHtml(label)}</span>`).join("")}
    </div>
  `);
}

function getAlertById(alertId) {
  return state.datasets.alerts.find((alert) => alert.id === alertId) || null;
}

function renderJobAlertPicker(selectedIds = []) {
  const normalizedSelectedIds = new Set((selectedIds || []).map((id) => Number(id)).filter(Number.isFinite));
  elements.jobForm.dataset.selectedAlertIds = JSON.stringify([...normalizedSelectedIds]);

  const alertOptions = state.datasets.alerts
    .map(
      (alert) => `
        <label class="selection-chip">
          <input
            type="checkbox"
            name="job_alert_ids"
            value="${alert.id}"
            ${normalizedSelectedIds.has(alert.id) ? "checked" : ""}
          />
          <span>${escapeHtml(formatAlertShort(alert))}</span>
        </label>
      `,
    )
    .join("");

  elements.jobAlertPicker.innerHTML = alertOptions || `<p class="field-hint">Сначала создайте хотя бы одно правило мониторинга.</p>`;
}

function collectSelectedJobAlertIds() {
  return [...elements.jobAlertPicker.querySelectorAll('input[name="job_alert_ids"]:checked')]
    .map((input) => Number(input.value))
    .filter(Number.isFinite);
}

async function loadSources() {
  state.datasets.sources = await api("/admin-api/sources");
  renderSourcesTable();
}

function renderSourcesTable() {
  renderPaginatedTable({
    sectionKey: "sources",
    host: elements.sourcesTable,
    headers: [
      "ID",
      "Название",
      "Базовый URL",
      "Запросов/мин",
      "Порог / Блокировка",
      "Статус",
      "Последняя ошибка",
      "Действия",
    ],
    items: state.datasets.sources,
    searchPlaceholder: "Название, URL или ошибка",
    searchBuilder: (source) =>
      buildSearchBlob([
        source.id,
        source.name,
        source.base_url,
        source.last_error,
        source.enabled ? "активен" : "отключён",
      ]),
    rowBuilder: (source) => [
      source.id,
      source.name,
      source.base_url,
      source.requests_per_minute,
      `${source.failure_threshold} / ${source.block_duration_minutes} мин`,
      source.blocked_until
        ? `До ${formatDate(source.blocked_until)}`
        : source.enabled
          ? "Активен"
          : "Отключён",
      source.last_error || "—",
      renderActionButtons([
        { label: "Редактировать", action: `editSource(${source.id}, this)` },
        { label: "Удалить", action: `deleteSource(${source.id}, this)`, danger: true },
      ]),
    ],
  });
}

async function submitSourceForm(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  setButtonLoading(submitButton, true, "Сохраняем...");
  try {
    const formData = new FormData(event.currentTarget);
    const sourceId = formData.get("sourceId");
    const payload = {
      name: String(formData.get("name") || "").trim(),
      base_url: String(formData.get("base_url") || "").trim(),
      enabled: formData.get("enabled") === "on",
      requests_per_minute: Number(formData.get("requests_per_minute")),
      failure_threshold: Number(formData.get("failure_threshold")),
      block_duration_minutes: Number(formData.get("block_duration_minutes")),
      notes: String(formData.get("notes") || "").trim() || null,
    };
    await api(sourceId ? `/admin-api/sources/${sourceId}` : "/admin-api/sources", {
      method: sourceId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetForm("source");
    await Promise.all([loadSources(), loadDashboard(), loadLogs()]);
    toast("Источник сохранён.", "success");
  } catch (error) {
    toast(error.message || "Не удалось сохранить источник.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

window.editSource = function editSource(sourceId, button) {
  setButtonLoading(button, true, "Открываем...");
  const source = state.datasets.sources.find((item) => item.id === sourceId);
  if (!source) {
    setButtonLoading(button, false);
    return;
  }
  const form = elements.sourceForm;
  form.sourceId.value = source.id;
  form.name.value = source.name;
  form.base_url.value = source.base_url;
  form.requests_per_minute.value = source.requests_per_minute;
  form.failure_threshold.value = source.failure_threshold;
  form.block_duration_minutes.value = source.block_duration_minutes;
  form.notes.value = source.notes || "";
  form.enabled.checked = source.enabled;
  setSection("sources");
  window.setTimeout(() => setButtonLoading(button, false), 250);
};

window.deleteSource = async function deleteSource(sourceId, button) {
  try {
    if (!confirm("Удалить источник и связанные записи?")) return;
    setButtonLoading(button, true, "Удаляем...");
    await api(`/admin-api/sources/${sourceId}`, { method: "DELETE" });
    await Promise.all([loadSources(), loadDashboard(), loadLogs()]);
    toast("Источник удалён.", "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить источник.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

async function loadJobs() {
  state.datasets.jobs = await api("/admin-api/jobs");
  renderJobAlertPicker(collectSelectedJobAlertIds());
  renderJobsTable();
}

function renderJobsTable() {
  renderPaginatedTable({
    sectionKey: "jobs",
    host: elements.jobsTable,
    headers: [
      "ID",
      "Название",
      "Интервал",
      "Правила",
      "Повторы / Задержка",
      "Последний запуск",
      "Статус",
      "Действия",
    ],
    items: state.datasets.jobs,
    searchPlaceholder: "Название, описание или правило",
    searchBuilder: (job) => {
      const ruleLabels = (job.alert_ids || []).map((alertId) => formatAlertShort(getAlertById(alertId) || { id: alertId, type: "unknown", product_id: null, competitor_id: null }));
      return buildSearchBlob([
        job.id,
        job.name,
        job.description,
        job.alert_ids,
        ruleLabels,
        job.last_status,
      ]);
    },
    rowBuilder: (job) => [
      job.id,
      job.name,
      `${job.schedule_minutes} мин`,
      formatJobAlertList(job.alert_ids),
      `${job.retry_attempts} / ${job.request_delay_ms} мс`,
      formatDate(job.last_run_at),
      formatJobStatus(job.last_status),
      renderActionButtons([
        { label: "Запустить", action: `runJob(${job.id}, this)` },
        { label: "Редактировать", action: `editJob(${job.id}, this)` },
        { label: "Удалить", action: `deleteJob(${job.id}, this)`, danger: true },
      ]),
    ],
  });
}

async function submitJobForm(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  setButtonLoading(submitButton, true, "Сохраняем...");
  try {
    const formData = new FormData(event.currentTarget);
    const jobId = formData.get("jobId");
    const payload = {
      name: String(formData.get("name") || "").trim(),
      description: String(formData.get("description") || "").trim() || null,
      enabled: formData.get("enabled") === "on",
      schedule_minutes: Number(formData.get("schedule_minutes")),
      alert_ids: collectSelectedJobAlertIds(),
      limit_products_per_run: nullableNumber(formData.get("limit_products_per_run")),
      retry_attempts: Number(formData.get("retry_attempts")),
      retry_backoff_seconds: Number(formData.get("retry_backoff_seconds")),
      request_delay_ms: Number(formData.get("request_delay_ms")),
    };
    await api(jobId ? `/admin-api/jobs/${jobId}` : "/admin-api/jobs", {
      method: jobId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetForm("job");
    await Promise.all([loadJobs(), loadDashboard(), loadLogs()]);
    toast("Задание сохранено.", "success");
  } catch (error) {
    toast(error.message || "Не удалось сохранить задание.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

window.editJob = function editJob(jobId, button) {
  setButtonLoading(button, true, "Открываем...");
  const job = state.datasets.jobs.find((item) => item.id === jobId);
  if (!job) {
    setButtonLoading(button, false);
    return;
  }
  const form = elements.jobForm;
  form.jobId.value = job.id;
  form.name.value = job.name;
  form.description.value = job.description || "";
  form.schedule_minutes.value = job.schedule_minutes;
  form.limit_products_per_run.value = job.limit_products_per_run || "";
  form.retry_attempts.value = job.retry_attempts;
  form.retry_backoff_seconds.value = job.retry_backoff_seconds;
  form.request_delay_ms.value = job.request_delay_ms;
  form.enabled.checked = job.enabled;
  renderJobAlertPicker(job.alert_ids || []);
  setSection("jobs");
  window.setTimeout(() => setButtonLoading(button, false), 250);
};

window.runJob = async function runJob(jobId, button) {
  setButtonLoading(button, true, "Запускаем...");
  try {
    const result = await api(`/admin-api/jobs/${jobId}/run`, { method: "POST" });
    await Promise.all([loadJobs(), loadDashboard(), loadLogs()]);
    toast(`Задание выполнено: сохранено цен ${result.prices_saved}.`, "success");
  } catch (error) {
    toast(error.message || "Не удалось выполнить задание.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

window.deleteJob = async function deleteJob(jobId, button) {
  try {
    if (!confirm("Удалить это задание?")) return;
    setButtonLoading(button, true, "Удаляем...");
    await api(`/admin-api/jobs/${jobId}`, { method: "DELETE" });
    await Promise.all([loadJobs(), loadDashboard(), loadLogs()]);
    toast("Задание удалено.", "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить задание.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

async function loadAlerts() {
  state.datasets.alerts = await api("/admin-api/alerts");
  renderJobAlertPicker(
    JSON.parse(elements.jobForm.dataset.selectedAlertIds || "[]"),
  );
  renderJobsTable();
  renderAlertsTable();
}

function renderAlertsTable() {
  renderPaginatedTable({
    sectionKey: "alerts",
    host: elements.alertsTable,
    headers: ["ID", "Товар", "Конкурент", "Тип", "Активно", "Получатели", "Действия"],
    items: state.datasets.alerts,
    searchPlaceholder: "ID, товар, конкурент или тип",
    searchBuilder: (alert) =>
      buildSearchBlob([
        alert.id,
        alert.product_id,
        alert.competitor_id,
        alert.type,
        alert.enabled ? "да" : "нет",
        alert.recipients,
        alert.params,
      ]),
    rowBuilder: (alert) => [
      alert.id,
      alert.product_id || "—",
      alert.competitor_id || "—",
      alert.type,
      alert.enabled ? "Да" : "Нет",
      Array.isArray(alert.recipients) ? alert.recipients.length : 0,
      renderActionButtons([
        { label: "Редактировать", action: `editAlert(${alert.id}, this)` },
        { label: "Удалить", action: `deleteAlert(${alert.id}, this)`, danger: true },
      ]),
    ],
  });
}

async function submitAlertForm(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  setButtonLoading(submitButton, true, "Сохраняем...");
  try {
    const formData = new FormData(event.currentTarget);
    const alertId = formData.get("alertId");
    const payload = {
      product_id: nullableNumber(formData.get("product_id")),
      competitor_id: nullableNumber(formData.get("competitor_id")),
      type: String(formData.get("type")),
      params: parseJsonField(String(formData.get("params") || "{}")),
      recipients: parseJsonField(String(formData.get("recipients") || "[]"), []),
      enabled: formData.get("enabled") === "on",
    };
    await api(alertId ? `/admin-api/alerts/${alertId}` : "/admin-api/alerts", {
      method: alertId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetForm("alert");
    await Promise.all([loadAlerts(), loadDashboard(), loadLogs()]);
    toast("Правило сохранено.", "success");
  } catch (error) {
    toast(error.message || "Не удалось сохранить правило.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

window.editAlert = function editAlert(alertId, button) {
  setButtonLoading(button, true, "Открываем...");
  const alert = state.datasets.alerts.find((item) => item.id === alertId);
  if (!alert) {
    setButtonLoading(button, false);
    return;
  }
  const form = elements.alertForm;
  form.alertId.value = alert.id;
  form.product_id.value = alert.product_id || "";
  form.competitor_id.value = alert.competitor_id || "";
  form.type.value = alert.type;
  form.params.value = JSON.stringify(alert.params || {}, null, 2);
  form.recipients.value = JSON.stringify(alert.recipients || [], null, 2);
  form.enabled.checked = alert.enabled;
  setSection("alerts");
  window.setTimeout(() => setButtonLoading(button, false), 250);
};

window.deleteAlert = async function deleteAlert(alertId, button) {
  try {
    if (!confirm("Удалить правило мониторинга?")) return;
    setButtonLoading(button, true, "Удаляем...");
    await api(`/admin-api/alerts/${alertId}`, { method: "DELETE" });
    await Promise.all([loadAlerts(), loadDashboard(), loadLogs()]);
    toast("Правило удалено.", "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить правило.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

async function loadLogs() {
  const limit = Number(elements.logsLimit.value || 100);
  state.datasets.logs = await api(`/admin-api/logs?limit=${limit}`);
  state.views.logs.page = 1;
  setHostHtmlPreservingSearchFocus(elements.logsTable, renderLogsTable(state.datasets.logs));
  if (state.datasets.dashboard) {
    elements.dashboardLogs.innerHTML = renderCompactLogsTable((state.datasets.dashboard.last_job_runs || []).slice(0, 5));
  }
}

function renderCompactLogsTable(logs) {
  return renderTable(
    ["Когда", "Уровень", "Действие", "Сущность", "Кто", "Сообщение", "Детали"],
    logs.map((log) => [
      formatDate(log.created_at),
      log.level,
      log.action,
      `${log.entity_type}${log.entity_id ? `:${log.entity_id}` : ""}`,
      log.actor_username || log.actor_user_id || "Система",
      log.message,
      renderLogDetails(log.details),
    ]),
  );
}

function getFilteredLogs(logs = state.datasets.logs) {
  const view = getViewState("logs");
  const query = normalizeSearchText(view.query);
  if (!query) {
    return logs;
  }
  return logs.filter((log) =>
    buildSearchBlob([
      log.created_at,
      log.level,
      log.action,
      log.entity_type,
      log.entity_id,
      log.actor_username,
      log.actor_user_id,
      log.message,
      log.details,
    ]).includes(query),
  );
}

function renderLogsTable(logs) {
  const view = getViewState("logs");
  const query = normalizeSearchText(view.query);
  const filteredLogs = getFilteredLogs(logs);

  const totalPages = Math.max(1, Math.ceil(filteredLogs.length / view.pageSize));
  if (view.page > totalPages) {
    view.page = totalPages;
  }

  const startIndex = (view.page - 1) * view.pageSize;
  const pagedLogs = filteredLogs.slice(startIndex, startIndex + view.pageSize);

  return `
    <div class="table-toolbar">
      <label class="table-search">
        <span>Поиск</span>
        <input
          type="search"
          value="${escapeHtml(view.query)}"
          placeholder="Действие, пользователь, сущность или сообщение"
          oninput="updateCollectionSearch('logs', this.value)"
        />
      </label>
      <div class="table-summary">${escapeHtml(filteredLogs.length ? `Показано ${pagedLogs.length} из ${filteredLogs.length}` : query ? "Ничего не найдено" : "Нет данных")}</div>
    </div>
    ${renderTable(
      ["Когда", "Уровень", "Действие", "Сущность", "Кто", "Сообщение", "Детали"],
      pagedLogs.map((log) => [
        formatDate(log.created_at),
        log.level,
        log.action,
        `${log.entity_type}${log.entity_id ? `:${log.entity_id}` : ""}`,
        log.actor_username || log.actor_user_id || "Система",
        log.message,
        renderLogDetails(log.details),
      ]),
      query ? "Ничего не найдено" : "Нет данных",
    )}
    ${buildPaginationButtons("logs", view.page, totalPages)}
  `;
}

function renderLogDetails(details) {
  const hasDetails =
    details !== null &&
    details !== undefined &&
    (!Array.isArray(details) || details.length > 0) &&
    (typeof details !== "object" || Array.isArray(details) || Object.keys(details).length > 0);

  if (!hasDetails) {
    return rawHtml(`<span class="log-detail-empty">Нет деталей</span>`);
  }

  const encoded = encodeURIComponent(JSON.stringify(details));
  return rawHtml(`
    <button
      class="action-button details-button"
      type="button"
      data-details="${escapeHtml(encoded)}"
      onclick="openLogDetails(this.dataset.details)"
    >
      Показать детали
    </button>
  `);
}

window.openLogDetails = function openLogDetails(encodedDetails) {
  try {
    const decoded = decodeURIComponent(encodedDetails);
    const parsed = JSON.parse(decoded);
    elements.logDetailsContent.textContent = JSON.stringify(parsed, null, 2);
    elements.logDetailsModal.classList.remove("hidden");
    document.body.classList.add("modal-open");
  } catch (error) {
    toast("Не удалось показать детали события.", "error");
  }
};

function closeLogDetailsModal() {
  elements.logDetailsModal.classList.add("hidden");
  elements.logDetailsContent.textContent = "";
  document.body.classList.remove("modal-open");
}

async function exportLogs() {
  const logs = getFilteredLogs();
  if (!logs.length) {
    throw new Error("Нет логов для экспорта.");
  }

  const exportPayload = logs.map((log) => ({
    created_at: log.created_at,
    level: log.level,
    action: log.action,
    entity_type: log.entity_type,
    entity_id: log.entity_id,
    actor_username: log.actor_username || null,
    actor_user_id: log.actor_user_id || null,
    message: log.message,
    details: log.details || {},
  }));

  const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.href = url;
  link.download = `price-monitor-logs-${stamp}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  toast(`Экспортировано логов: ${exportPayload.length}`, "success");
}

async function loadUsers() {
  if (!isSuperAdmin()) return;
  state.datasets.users = await api("/admin-api/users");
  renderUsersTable();
}

function renderUsersTable() {
  renderPaginatedTable({
    sectionKey: "users",
    host: elements.usersTable,
    headers: ["ID", "Логин", "Полное имя", "Роль", "Активен", "Последний вход", "Действия"],
    items: state.datasets.users,
    searchPlaceholder: "Логин, имя или роль",
    searchBuilder: (user) =>
      buildSearchBlob([
        user.id,
        user.username,
        user.full_name,
        user.role,
        user.is_active ? "да" : "нет",
      ]),
    rowBuilder: (user) => [
      user.id,
      user.username,
      user.full_name || "—",
      formatRole(user.role),
      user.is_active ? "Да" : "Нет",
      formatDate(user.last_login_at),
      renderActionButtons([
        { label: "Редактировать", action: `editUser(${user.id}, this)` },
        { label: "Удалить", action: `deleteUser(${user.id}, this)`, danger: true },
      ]),
    ],
  });
}

async function submitUserForm(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  setButtonLoading(submitButton, true, "Сохраняем...");
  try {
    const formData = new FormData(event.currentTarget);
    const userId = formData.get("userId");
    const payload = {
      full_name: String(formData.get("full_name") || "").trim() || null,
      role: String(formData.get("role")),
      is_active: formData.get("is_active") === "on",
    };
    const password = String(formData.get("password") || "");
    if (password) {
      payload.password = password;
    }
    if (!userId) {
      payload.username = String(formData.get("username") || "").trim();
    }

    await api(userId ? `/admin-api/users/${userId}` : "/admin-api/users", {
      method: userId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetForm("user");
    await Promise.all([loadUsers(), loadDashboard(), loadLogs()]);
    toast("Пользователь сохранён.", "success");
  } catch (error) {
    toast(error.message || "Не удалось сохранить пользователя.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

window.editUser = function editUser(userId, button) {
  setButtonLoading(button, true, "Открываем...");
  const user = state.datasets.users.find((item) => item.id === userId);
  if (!user) {
    setButtonLoading(button, false);
    return;
  }
  const form = elements.userForm;
  form.userId.value = user.id;
  form.username.value = user.username;
  form.username.disabled = true;
  form.full_name.value = user.full_name || "";
  form.password.value = "";
  form.role.value = user.role;
  form.is_active.checked = user.is_active;
  setSection("users");
  window.setTimeout(() => setButtonLoading(button, false), 250);
};

window.deleteUser = async function deleteUser(userId, button) {
  try {
    if (!confirm("Удалить пользователя панели?")) return;
    setButtonLoading(button, true, "Удаляем...");
    await api(`/admin-api/users/${userId}`, { method: "DELETE" });
    await Promise.all([loadUsers(), loadDashboard(), loadLogs()]);
    toast("Пользователь удалён.", "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить пользователя.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

async function loadSettings() {
  if (!isSuperAdmin()) return;
  const [settingsResponse, backupsResponse] = await Promise.all([
    api("/api/v1/service-settings?page=1&page_size=200"),
    api("/api/v1/backups?page=1&page_size=200"),
  ]);
  state.datasets.settings = settingsResponse.items || [];
  state.datasets.backups = backupsResponse.items || [];
  renderSettingsTable();
  renderBackupsTable();
}

function renderSettingsTable() {
  renderPaginatedTable({
    sectionKey: "settings",
    host: elements.settingsTable,
    headers: ["ID", "Ключ", "Описание", "Значение", "Обновлено", "Действия"],
    items: state.datasets.settings,
    searchPlaceholder: "Ключ, описание или JSON",
    searchBuilder: (setting) =>
      buildSearchBlob([
        setting.id,
        setting.key,
        setting.description,
        setting.value,
      ]),
    rowBuilder: (setting) => [
      setting.id,
      setting.key,
      setting.description || "—",
      rawHtml(`<code>${escapeHtml(JSON.stringify(setting.value || {}, null, 2))}</code>`),
      formatDate(setting.updated_at),
      renderActionButtons([
        { label: "Редактировать", action: `editSetting(${setting.id}, this)` },
        { label: "Удалить", action: `deleteSetting(${setting.id}, this)`, danger: true },
      ]),
    ],
  });
}

function renderBackupsTable() {
  renderPaginatedTable({
    sectionKey: "backups",
    host: elements.backupsTable,
    headers: ["Имя файла", "Создано", "Размер", "Действия"],
    items: state.datasets.backups,
    searchPlaceholder: "Имя файла резервной копии",
    searchBuilder: (backup) =>
      buildSearchBlob([
        backup.backup_name,
        backup.created_at,
        backup.size_bytes,
      ]),
    rowBuilder: (backup) => [
      backup.backup_name,
      formatDate(backup.created_at),
      formatFileSize(backup.size_bytes),
      renderActionButtons([
        { label: "Восстановить", action: `restoreBackup('${escapeJsString(backup.backup_name)}', this)` },
        { label: "Удалить", action: `deleteBackup('${escapeJsString(backup.backup_name)}', this)`, danger: true },
      ]),
    ],
  });
}

async function createBackup() {
  const response = await api("/api/v1/backups", { method: "POST" });
  await Promise.all([loadSettings(), loadLogs()]);
  toast(`Резервная копия создана: ${response.backup.backup_name}`, "success");
}

window.restoreBackup = async function restoreBackup(backupName, button) {
  try {
    if (!confirm(`Восстановить систему из копии ${backupName}? Перед восстановлением будет создана страховочная копия.`)) return;
    setButtonLoading(button, true, "Восстанавливаем...");
    const encodedName = encodeURIComponent(backupName);
    const response = await api(`/api/v1/backups/${encodedName}/restore`, { method: "POST" });
    await Promise.all([loadSettings(), loadDashboard(), loadLogs()]);
    toast(
      `Восстановление завершено из ${response.restored_from}. Страховочная копия: ${response.safety_backup.backup_name}.`,
      "success",
    );
  } catch (error) {
    toast(error.message || "Не удалось восстановить резервную копию.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

window.deleteBackup = async function deleteBackup(backupName, button) {
  try {
    if (!confirm(`Удалить резервную копию ${backupName}?`)) return;
    setButtonLoading(button, true, "Удаляем...");
    const encodedName = encodeURIComponent(backupName);
    await api(`/api/v1/backups/${encodedName}`, { method: "DELETE" });
    await Promise.all([loadSettings(), loadLogs()]);
    toast(`Резервная копия удалена: ${backupName}`, "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить резервную копию.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

async function submitSettingForm(event) {
  event.preventDefault();
  const submitButton = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  setButtonLoading(submitButton, true, "Сохраняем...");
  try {
    const formData = new FormData(event.currentTarget);
    const payload = {
      key: String(formData.get("key") || "").trim(),
      description: String(formData.get("description") || "").trim() || null,
      value: parseJsonField(String(formData.get("value") || "{}")),
    };
    await api("/admin-api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    resetForm("setting");
    await Promise.all([loadSettings(), loadDashboard(), loadLogs()]);
    toast("Настройка сохранена.", "success");
  } catch (error) {
    toast(error.message || "Не удалось сохранить настройку.", "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

window.editSetting = function editSetting(settingId, button) {
  setButtonLoading(button, true, "Открываем...");
  const setting = state.datasets.settings.find((item) => item.id === settingId);
  if (!setting) {
    setButtonLoading(button, false);
    return;
  }
  const form = elements.settingForm;
  form.settingId.value = setting.id;
  form.key.value = setting.key;
  form.key.readOnly = true;
  form.description.value = setting.description || "";
  form.value.value = JSON.stringify(setting.value || {}, null, 2);
  setSection("settings");
  window.setTimeout(() => setButtonLoading(button, false), 250);
};

window.deleteSetting = async function deleteSetting(settingId, button) {
  try {
    if (!confirm("Удалить настройку?")) return;
    setButtonLoading(button, true, "Удаляем...");
    await api(`/admin-api/settings/${settingId}`, { method: "DELETE" });
    await Promise.all([loadSettings(), loadDashboard(), loadLogs()]);
    toast("Настройка удалена.", "success");
  } catch (error) {
    toast(error.message || "Не удалось удалить настройку.", "error");
  } finally {
    setButtonLoading(button, false);
  }
};

function resetForm(name) {
  const forms = {
    source: elements.sourceForm,
    job: elements.jobForm,
    alert: elements.alertForm,
    user: elements.userForm,
    setting: elements.settingForm,
  };
  const form = forms[name];
  if (!form) return;
  form.reset();
  if (form.sourceId) form.sourceId.value = "";
  if (form.jobId) form.jobId.value = "";
  if (form.alertId) form.alertId.value = "";
  if (form.userId) form.userId.value = "";
  if (form.settingId) form.settingId.value = "";
  if (form.username) form.username.disabled = false;
  if (form.key) form.key.readOnly = false;
  if (name === "job") {
    form.dataset.selectedAlertIds = "[]";
    renderJobAlertPicker([]);
  }
  if (name === "alert") {
    form.params.value = "{}";
    form.recipients.value = "[]";
  }
  if (name === "setting") {
    form.value.value = "{}";
  }
}

function parseJsonField(value, fallback = {}) {
  const trimmed = value.trim();
  if (!trimmed) {
    return fallback;
  }
  return JSON.parse(trimmed);
}

function rawHtml(value) {
  return { __html: value };
}

function escapeJsString(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r");
}

function nullableNumber(value) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).trim();
  if (!normalized) return null;
  return Number(normalized);
}

function renderTable(headers, rows, emptyText = "Нет данных") {
  return `
    <table>
      <thead>
        <tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>
      </thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map(
                  (row) => `
                    <tr>${row
                      .map((cell) => `<td>${cell && typeof cell === "object" && "__html" in cell ? cell.__html : escapeHtml(String(cell))}</td>`)
                      .join("")}</tr>
                  `,
                )
                .join("")
            : `<tr><td colspan="${headers.length}">${escapeHtml(emptyText)}</td></tr>`
        }
      </tbody>
    </table>
  `;
}

function renderActionButtons(buttons) {
  return rawHtml(`
    <div class="table-actions">
      ${buttons
        .map(
          (button) => `
            <button class="action-button ${button.danger ? "danger" : ""}" type="button" onclick="${button.action}">
              <span class="button-label">${escapeHtml(button.label)}</span>
            </button>
          `,
        )
        .join("")}
    </div>
  `);
}

function updateStatus(message) {
  void message;
}

function toast(message, variant = "success") {
  elements.toast.textContent = message;
  elements.toast.className = `toast ${variant}`;
  elements.toast.classList.remove("hidden");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 3200);
}

async function safeRun(task, button = null, loadingText = "Загрузка...") {
  setButtonLoading(button, true, loadingText);
  try {
    await task();
  } catch (error) {
    toast(error.message || "Операция завершилась ошибкой.", "error");
  } finally {
    setButtonLoading(button, false);
  }
}

function setButtonLoading(button, isLoading, loadingText = "Загрузка...") {
  if (!(button instanceof HTMLElement)) {
    return;
  }

  if (!button.dataset.originalLabel) {
    const labelNode = button.querySelector(".button-label");
    button.dataset.originalLabel = labelNode ? labelNode.textContent.trim() : button.textContent.trim();
  }

  const labelNode = button.querySelector(".button-label");
  if (isLoading) {
    button.disabled = true;
    button.classList.add("is-loading");
    if (labelNode) {
      labelNode.textContent = loadingText;
    } else {
      button.textContent = loadingText;
    }
    return;
  }

  button.disabled = false;
  button.classList.remove("is-loading");
  if (labelNode) {
    labelNode.textContent = button.dataset.originalLabel;
  } else if (button.dataset.originalLabel) {
    button.textContent = button.dataset.originalLabel;
  }
}

function formatRole(role) {
  if (role === "super_admin") return "Супер-админ";
  if (role === "operator") return "Оператор";
  return role || "—";
}

function formatJobStatus(status) {
  const mapping = {
    idle: "Ожидание",
    success: "Успешно",
    partial_error: "Частично с ошибками",
    failed: "Ошибка",
    running: "Выполняется",
  };
  return mapping[status] || status || "—";
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatFileSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} Б`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} КБ`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} МБ`;
  return `${(value / 1024 ** 3).toFixed(1)} ГБ`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
