import {
  byId,
  fetchJson,
  getApiToken,
  messageText,
  normalizeSessionDetail,
  normalizeLines,
  state,
  upsertMessage,
  upsertSessionSummary,
  sortSessions,
} from "./state.js";
import { renderMarkdown } from "./markdown.js";
import {
  collectSelectedKnowledgeBaseIds,
  collectAuthorizationDraft,
  fillAuthorizationDraft,
  getDefaultAuthorizationDraft,
  renderApp,
  renderAuthorizations,
  setSelectedKnowledgeBaseIds,
  setAuthorizationFeedback,
} from "./render.js";

// ── API Endpoints ─────────────────────────────────────────────────
const API = {
  HEALTH: "/api/health",
  BOOTSTRAP: "/api/bootstrap",
  SESSIONS: "/api/chat/sessions",
  COMMANDS: "/api/commands",
  EVENTS: "/api/chat/events",
  AUTHORIZATIONS: "/api/authorizations",
  KNOWLEDGE_BASES: "/api/knowledge/bases",
  session: (id) => `/api/chat/sessions/${encodeURIComponent(id)}`,
  sessionMessages: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/messages`,
  sessionInterrupt: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/interrupt`,
  sessionFork: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/fork`,
  sessionKnowledge: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/knowledge-documents`,
  sessionTrajectory: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/trajectory`,
  sessionMemoryStatus: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/memory-status`,
  sessionFindings: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/findings`,
  approvalRespond: (id) => `/api/chat/approvals/${encodeURIComponent(id)}/respond`,
  approvalCancel: (id) => `/api/chat/approvals/${encodeURIComponent(id)}/cancel`,
  knowledgeBase: (id) => `/api/knowledge/bases/${encodeURIComponent(id)}`,
  knowledgeDocuments: (id) => `/api/knowledge/bases/${encodeURIComponent(id)}/documents`,
  knowledgeDocumentUpload: (id) => `/api/knowledge/bases/${encodeURIComponent(id)}/documents/upload`,
  knowledgeDocument: (baseId, docId) => `/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/${encodeURIComponent(docId)}`,
  CONFIG: "/api/chat/config",
  CONFIG_RELOAD: "/api/chat/config/reload",
};

const bootstrapDefaults = window.__AUTOSONGSHU_BOOTSTRAP__ || {};
const API_RECOVERY_TIMEOUT_MS = 15000;
const API_RECOVERY_RETRY_MS = 500;
const MIN_RENDER_INTERVAL_MS = 16;
const FORCE_RENDER_EVENT_TYPES = new Set(["tool_use", "tool_result", "completed", "error", "failed"]);
let renderScheduled = false;
let lastRenderTime = 0;
let perfEnabled = false;
let realtimeResyncNeeded = false;
let recoveryPromise = null;
let currentApprovalRequestId = null;

function showApprovalModal(request) {
  const modal = byId("approval-modal");
  if (!modal || !request) {
    return;
  }
  currentApprovalRequestId = request.request_id;
  const setText = (id, text) => {
    const el = byId(id);
    if (el) el.textContent = text;
  };
  setText("approval-tool-name", request.tool_name || "-");
  setText("approval-arguments", JSON.stringify(request.arguments || {}, null, 2));
  setText("approval-request-id", request.request_id || "-");
  setText("approval-session-id", request.session_id || "-");
  setText("approval-timeout-seconds", String(request.timeout_seconds || 300));
  const riskBadge = byId("approval-risk-badge");
  if (riskBadge) {
    const level = String(request.risk_level || "medium").toLowerCase();
    riskBadge.textContent = level === "critical" ? "严重风险" : level === "high" ? "高风险" : level === "medium" ? "中等风险" : "低风险";
    riskBadge.classList.remove("is-medium", "is-high", "is-critical");
    if (level === "medium") {
      riskBadge.classList.add("is-medium");
    } else if (level === "high") {
      riskBadge.classList.add("is-high");
    } else if (level === "critical") {
      riskBadge.classList.add("is-critical");
    }
  }
  // Reset scope selection to default
  const onceRadio = modal.querySelector('input[name="approval-scope"][value="once"]');
  if (onceRadio) {
    onceRadio.checked = true;
  }
  const alwaysAllowCheckbox = byId("approval-always-allow");
  if (alwaysAllowCheckbox) {
    alwaysAllowCheckbox.checked = false;
  }
  modal.hidden = false;
  document.body.classList.add("modal-open");
}

function hideApprovalModal() {
  const modal = byId("approval-modal");
  if (modal) {
    modal.hidden = true;
  }
  currentApprovalRequestId = null;
  document.body.classList.remove("modal-open");
}

async function respondToApproval(approved) {
  if (!currentApprovalRequestId) {
    return;
  }
  const rememberCheckbox = byId("approval-remember-session");
  const remember_for_session = rememberCheckbox ? rememberCheckbox.checked : false;
  const alwaysAllowCheckbox = byId("approval-always-allow");
  const always_allow = alwaysAllowCheckbox ? alwaysAllowCheckbox.checked : false;
  try {
    await fetchJson(`/api/chat/approvals/${encodeURIComponent(currentApprovalRequestId)}/respond`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, reason: "", remember_for_session, always_allow }),
    });
  } catch (error) {
    window.alert(`审批响应失败：${String(error.message || error)}`);
    return;
  }
  hideApprovalModal();
}

export function setPerformanceMonitoring(enabled) {
  perfEnabled = Boolean(enabled);
}

function readValue(id) {
  return byId(id)?.value ?? "";
}

function readTrimmedValue(id) {
  return readValue(id).trim();
}

function setValue(id, value) {
  const node = byId(id);
  if (node) {
    node.value = value;
  }
}

export async function getConfig(configPath) {
  try {
    const url = configPath ? `${API.CONFIG}?config_path=${encodeURIComponent(configPath)}` : API.CONFIG;
    return await fetchJson(url);
  } catch (error) {
    window.alert(`获取配置失败：${String(error.message || error)}`);
    return null;
  }
}

export async function reloadConfig(configPath) {
  try {
    const body = configPath ? { config_path: configPath } : {};
    return await fetchJson(API.CONFIG_RELOAD, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    window.alert(`配置热更新失败：${String(error.message || error)}`);
    return null;
  }
}

function readChecked(id, fallback = false) {
  const node = byId(id);
  return node ? Boolean(node.checked) : fallback;
}

function focusById(id) {
  byId(id)?.focus();
}

function _scheduleRenderApp({ force = false, eventType = "" } = {}) {
  if (force || FORCE_RENDER_EVENT_TYPES.has(eventType)) {
    if (renderScheduled) {
      renderScheduled = false;
    }
    renderApp();
    lastRenderTime = performance.now();
    return;
  }

  if (renderScheduled) {
    return;
  }

  const now = performance.now();
  const elapsed = now - lastRenderTime;
  if (elapsed < MIN_RENDER_INTERVAL_MS) {
    renderScheduled = true;
    requestAnimationFrame(() => {
      if (renderScheduled) {
        renderScheduled = false;
        renderApp();
        lastRenderTime = performance.now();
      }
    });
    return;
  }

  renderApp();
  lastRenderTime = now;
}

export function scheduleRenderApp(options) {
  _scheduleRenderApp(options);
}

function scheduleRealtimeResync() {
  if (!realtimeResyncNeeded) {
    return;
  }
  realtimeResyncNeeded = false;
  refreshData({ suppressRecovery: true }).catch(() => {
    realtimeResyncNeeded = true;
  });
}

export async function loadFindings(sessionId) {
  try {
    const data = await fetchJson(API.sessionFindings(sessionId));
    if (data && Array.isArray(data.findings)) {
      state.findings = data.findings;
      state.findingsSessionId = sessionId;
    }
  } catch (e) {
    console.warn("Failed to load findings:", e);
  }
}

export async function loadSteps(sessionId) {
  try {
    const data = await fetchJson(API.sessionTrajectory(sessionId));
    if (data && Array.isArray(data.steps)) {
      state.steps = data.steps;
      state.stepsSessionId = sessionId;
    }
  } catch (e) {
    console.warn("Failed to load steps:", e);
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isTransientTransportError(error) {
  const message = String(error?.message || error || "");
  return /networkerror|failed to fetch|fetch resource|load failed|request timed out|请求超时/i.test(message);
}

function closeRealtimeConnection() {
  if (!state.eventSource) {
    return;
  }
  state.eventSource.close();
  state.eventSource = null;
}

async function recoverServerConnection({ refresh = true } = {}) {
  if (recoveryPromise) {
    return recoveryPromise;
  }

  recoveryPromise = (async () => {
    realtimeResyncNeeded = true;
    state.connectionState = "reconnecting";
    closeRealtimeConnection();
    _scheduleRenderApp();

    const deadline = Date.now() + API_RECOVERY_TIMEOUT_MS;
    let lastError = new Error("服务暂时不可用");

    while (Date.now() < deadline) {
      try {
        await fetchJson(`${API.HEALTH}?_=${Date.now()}`, { timeoutMs: 3000 });
        connectRealtime();
        if (refresh) {
          await refreshData({ suppressRecovery: true });
        }
        return;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error || "服务暂时不可用"));
        await sleep(API_RECOVERY_RETRY_MS);
      }
    }

    throw lastError;
  })();

  try {
    await recoveryPromise;
  } finally {
    recoveryPromise = null;
  }
}

function scheduleServerRecovery(options = {}) {
  recoverServerConnection(options).catch(() => {});
}

export async function refreshAuthorizations(selectedId = "") {
  const payload = await fetchJson("/api/authorizations");
  renderAuthorizations(payload.authorizations || []);
  if (selectedId) {
    setValue("authorization-profile", selectedId);
  }
}

export function applyAuthorizationById(id) {
  const normalizedId = String(id || "");
  const record = state.authorizations.find((item) => String(item.id) === normalizedId);
  if (!record) {
    return;
  }
  fillAuthorizationDraft(record);
  setAuthorizationFeedback(`已载入授权配置：${record.name}`, "success");
}

export async function saveAuthorizationRecord() {
  const draft = collectAuthorizationDraft();
  if (!draft.name || !draft.authorization || !draft.start_url) {
    setAuthorizationFeedback("请至少填写评估名称、授权编号和起始 URL。", "error");
    return;
  }

  try {
    setAuthorizationFeedback("正在保存授权配置…");
    const created = await fetchJson("/api/authorizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    await refreshAuthorizations(String(created.id));
    setAuthorizationFeedback(`已保存到授权配置库：${created.name}`, "success");
  } catch (error) {
    setAuthorizationFeedback(`保存失败：${String(error.message || error)}`, "error");
  }
}

export async function refreshKnowledgeBases({ loadDetail = true } = {}) {
  const payload = await fetchJson("/api/knowledge/bases");
  state.knowledgeBases = payload.items || [];
  if (state.selectedKnowledgeBaseIds.length) {
    const existingIds = new Set(state.knowledgeBases.map((item) => String(item.id)));
    setSelectedKnowledgeBaseIds(state.selectedKnowledgeBaseIds.filter((item) => existingIds.has(String(item))));
  }
  if (state.selectedKnowledgeBaseId && !state.knowledgeBases.some((item) => String(item.id) === String(state.selectedKnowledgeBaseId))) {
    state.selectedKnowledgeBaseId = null;
  }
  if (!state.selectedKnowledgeBaseId && state.knowledgeBases.length) {
    state.selectedKnowledgeBaseId = String(state.knowledgeBases[0].id);
  }
  if (loadDetail && state.selectedKnowledgeBaseId) {
    await loadKnowledgeBaseDetail(state.selectedKnowledgeBaseId);
  }
  renderApp();
  return state.knowledgeBases;
}

export async function loadKnowledgeBaseDetail(knowledgeBaseId) {
  if (!knowledgeBaseId) {
    return null;
  }
  const detail = await fetchJson(`/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}`);
  state.knowledgeBaseDetails.set(knowledgeBaseId, detail);
  renderApp();
  return detail;
}

export async function createKnowledgeBaseRecord(payload) {
  const created = await fetchJson("/api/knowledge/bases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.selectedKnowledgeBaseId = created.id;
  await refreshKnowledgeBases({ loadDetail: true });
  return created;
}

export async function deleteKnowledgeBaseRecord(knowledgeBaseId) {
  await fetchJson(`/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}`, {
    method: "DELETE",
  });
  if (state.selectedKnowledgeBaseId === knowledgeBaseId) {
    state.selectedKnowledgeBaseId = null;
  }
  state.knowledgeBaseDetails.delete(knowledgeBaseId);
  setSelectedKnowledgeBaseIds(collectSelectedKnowledgeBaseIds().filter((item) => item !== knowledgeBaseId));
  await refreshKnowledgeBases({ loadDetail: true });
}

export async function saveKnowledgeDocumentRecord(knowledgeBaseId, payload = {}) {
  const { title = "", source = "", content = "", file = null } = payload;
  if (file) {
    const form = new FormData();
    if (title) {
      form.set("title", title);
    }
    if (source) {
      form.set("source", source);
    }
    form.set("file", file);
    await fetchJson(`/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/documents/upload`, {
      method: "POST",
      body: form,
      timeoutMs: 30000,
    });
  } else {
    await fetchJson(`/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        source,
        source_type: "text",
        content,
      }),
      timeoutMs: 30000,
    });
  }
  await loadKnowledgeBaseDetail(knowledgeBaseId);
  await refreshKnowledgeBases({ loadDetail: false });
}

export async function deleteKnowledgeDocumentRecord(knowledgeBaseId, documentId) {
  await fetchJson(
    `/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
    },
  );
  await loadKnowledgeBaseDetail(knowledgeBaseId);
  await refreshKnowledgeBases({ loadDetail: false });
}

export async function loadSession(sessionId, { render = true, suppressRecovery = false } = {}) {
  try {
    const detail = normalizeSessionDetail(await fetchJson(`/api/chat/sessions/${encodeURIComponent(sessionId)}`));
    const normalizedId = String(sessionId);
    state.sessionDetails.set(normalizedId, detail);
    if (Array.isArray(detail.knowledge_base_ids)) {
      setSelectedKnowledgeBaseIds(detail.knowledge_base_ids);
    }
    upsertSessionSummary(detail);
    await loadFindings(sessionId);
    await loadSteps(sessionId);
    if (render && String(state.selectedSessionId) === normalizedId) {
      // Use force: true to bypass the render throttle since we just loaded a new session
      scheduleRenderApp({ force: true });
    }
    return detail;
  } catch (error) {
    if (!suppressRecovery && isTransientTransportError(error)) {
      await recoverServerConnection({ refresh: false });
      return loadSession(sessionId, { render, suppressRecovery: true });
    }
    throw error;
  }
}

export async function interruptSession(sessionId) {
  const detail = normalizeSessionDetail(
    await fetchJson(`/api/chat/sessions/${encodeURIComponent(sessionId)}/interrupt`, {
      method: "POST",
    }),
  );
  // Only update the summary-level data; do NOT overwrite state.sessionDetails
  // with the HTTP response snapshot.  The interrupt API generates detail_dict()
  // *before* conversation.interrupt() completes, so the snapshot contains stale
  // message statuses (e.g. "in_progress").  The actual final state arrives
  // asynchronously via SSE (message.upsert → status="failed"), and we must
  // let those SSE events win the race.
  upsertSessionSummary(detail);
  renderApp();
  return detail;
}

export async function forkSession(sessionId, messageIndex = -1) {
  const detail = normalizeSessionDetail(
    await fetchJson(API.sessionFork(sessionId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_index: messageIndex }),
    }),
  );
  state.sessionDetails.set(detail.id, detail);
  upsertSessionSummary(detail);
  state.selectedSessionId = detail.id;
  state.findings = [];
  state.findingsSessionId = null;
  state.steps = [];
  state.stepsSessionId = null;
  await loadSession(detail.id, { render: false });
  renderApp();
  return detail;
}

export async function createKnowledgeDocumentFromSession(sessionId, payload = {}) {
  const knowledgeBaseId = String(payload.knowledgeBaseId || "").trim();
  const result = await fetchJson(`/api/chat/sessions/${encodeURIComponent(sessionId)}/knowledge-documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      knowledge_base_id: knowledgeBaseId || null,
    }),
    timeoutMs: 45000,
  });

  const targetKnowledgeBaseId = String(result?.knowledge_base_id || knowledgeBaseId || "").trim();
  if (targetKnowledgeBaseId) {
    state.selectedKnowledgeBaseId = targetKnowledgeBaseId;
    await loadKnowledgeBaseDetail(targetKnowledgeBaseId);
    await refreshKnowledgeBases({ loadDetail: false });
  } else {
    renderApp();
  }
  return result;
}

export async function refreshData({ suppressRecovery = false } = {}) {
  try {
    const payload = await fetchJson(API.SESSIONS);
    state.sessions = payload.sessions || [];
    sortSessions();

    if (state.selectedSessionId) {
      const selectedId = String(state.selectedSessionId);
      const exists = state.sessions.some((item) => String(item.id) === selectedId);
      if (exists) {
        await loadSession(selectedId, { render: false, suppressRecovery });
      } else {
        state.selectedSessionId = state.sessions[0]?.id ? String(state.sessions[0].id) : null;
        if (state.selectedSessionId) {
          await loadSession(state.selectedSessionId, { render: false, suppressRecovery });
        }
      }
    } else if (state.sessions.length) {
      state.selectedSessionId = String(state.sessions[0].id);
      await loadSession(state.selectedSessionId, { render: false, suppressRecovery });
    }

    renderApp();
  } catch (error) {
    if (!suppressRecovery && isTransientTransportError(error)) {
      await recoverServerConnection({ refresh: true });
      return;
    }
    throw error;
  }
}

export function connectRealtime() {
  closeRealtimeConnection();

  state.connectionState = "connecting";
  renderApp();

  const token = getApiToken();
  const eventsUrl = token
    ? `${API.EVENTS}?token=${encodeURIComponent(token)}`
    : API.EVENTS;
  const eventSource = new EventSource(eventsUrl);
  state.eventSource = eventSource;

  eventSource.addEventListener("open", () => {
    const shouldResync = realtimeResyncNeeded || state.connectionState === "reconnecting";
    state.connectionState = "connected";
    _scheduleRenderApp();
    if (shouldResync) {
      scheduleRealtimeResync();
    }
  });

  eventSource.addEventListener("connected", () => {
    const shouldResync = realtimeResyncNeeded || state.connectionState === "reconnecting";
    state.connectionState = "connected";
    _scheduleRenderApp();
    if (shouldResync) {
      scheduleRealtimeResync();
    }
  });

  eventSource.addEventListener("session.upsert", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse SSE event data:", parseError);
      return;
    }
    upsertSessionSummary(payload.session);
    _scheduleRenderApp();
  });

  eventSource.addEventListener("message.upsert", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse SSE event data:", parseError);
      return;
    }
    const sessionId = payload.session_id;

    const detail = state.sessionDetails.get(sessionId);
    if (detail) {
      state.sessionDetails.set(sessionId, upsertMessage(detail, payload.message));
    } else if (sessionId === state.selectedSessionId) {
      loadSession(sessionId).catch(() => {});
      return;
    }

    if (sessionId === state.selectedSessionId) {
      const message = payload.message;
      const content = Array.isArray(message?.content) ? message.content : [];
      const lastPart = content[content.length - 1];
      const eventType = String(lastPart?.type || "").toLowerCase();
      _scheduleRenderApp({ eventType });
    }
  });

  eventSource.addEventListener("message.compacted", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse SSE event data:", parseError);
      return;
    }
    const sessionId = payload.session_id;
    const deletedIds = Array.isArray(payload.deleted_message_ids)
      ? payload.deleted_message_ids.map((id) => String(id))
      : [];

    if (!deletedIds.length || sessionId !== state.selectedSessionId) {
      return;
    }

    const detail = state.sessionDetails.get(sessionId);
    if (!detail || !Array.isArray(detail.messages)) {
      return;
    }

    const removedSet = new Set(deletedIds);
    const filtered = detail.messages.filter((msg) => !removedSet.has(String(msg.id)));
    state.sessionDetails.set(sessionId, { ...detail, messages: filtered });
    _scheduleRenderApp({ force: true });
  });

  eventSource.addEventListener("finding.upsert", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse finding.upsert event:", parseError);
      return;
    }
    const sessionId = payload.session_id;
    if (sessionId !== state.selectedSessionId) return;
    if (Array.isArray(payload.findings)) {
      state.findings = payload.findings;
      state.findingsSessionId = sessionId;
      _scheduleRenderApp();
    }
  });

  eventSource.addEventListener("step.upsert", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse step.upsert event:", parseError);
      return;
    }
    const sessionId = payload.session_id;
    if (sessionId !== state.selectedSessionId) return;
    if (payload.step) {
      // Avoid duplicates by checking index
      const existing = state.steps.findIndex(s => s.index === payload.step.index);
      if (existing >= 0) {
        state.steps[existing] = payload.step;
      } else {
        state.steps.push(payload.step);
      }
      state.stepsSessionId = sessionId;
      _scheduleRenderApp();
    }
  });

  eventSource.addEventListener("progress.update", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse progress.update event:", parseError);
      return;
    }
    const sessionId = payload.session_id;
    if (sessionId !== state.selectedSessionId) return;
    if (payload.progress) {
      state.progress = payload.progress;
      state.progressSessionId = sessionId;
      _scheduleRenderApp();
    }
  });

  eventSource.addEventListener("approval.request", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (parseError) {
      console.warn("Failed to parse SSE event data:", parseError);
      return;
    }
    showApprovalModal(payload);
  });

  eventSource.addEventListener("approval.response", (event) => {
    hideApprovalModal();
  });

  eventSource.onerror = () => {
    if (state.eventSource !== eventSource) {
      return;
    }
    state.connectionState = "reconnecting";
    realtimeResyncNeeded = true;
    _scheduleRenderApp();
    scheduleServerRecovery({ refresh: true });
  };
}

export async function bootstrap({ suppressRecovery = false } = {}) {
  try {
    const payload = await fetchJson(API.BOOTSTRAP);
    state.defaultConfigPath = payload.default_config_path || bootstrapDefaults.defaultConfigPath;
    state.defaultGoal = payload.default_goal || bootstrapDefaults.defaultGoal;
    state.defaultAuthorizationDraft =
      payload.default_authorization_draft || bootstrapDefaults.defaultAuthorizationDraft;
    state.artifactRoot = payload.artifact_root || "";
    state.knowledgeBases = payload.knowledge_bases || [];
    state.knowledgeBaseDetails = new Map();
    state.selectedKnowledgeBaseId = state.knowledgeBases[0]?.id || null;
    setSelectedKnowledgeBaseIds([]);
    state.sessions = payload.chat_sessions || [];
    sortSessions();

    setValue("config-path", state.defaultConfigPath);
    fillAuthorizationDraft(getDefaultAuthorizationDraft());
    setValue("skill-dirs", "");
    renderAuthorizations(payload.authorizations || []);
    setAuthorizationFeedback("新会话会使用这里的默认配置。");
    if (state.selectedKnowledgeBaseId) {
      await loadKnowledgeBaseDetail(state.selectedKnowledgeBaseId);
    }

    if (state.sessions.length) {
      state.selectedSessionId = String(state.sessions[0].id);
      await loadSession(state.selectedSessionId, { render: false, suppressRecovery });
    }

    renderApp();
  } catch (error) {
    if (!suppressRecovery && isTransientTransportError(error)) {
      await recoverServerConnection({ refresh: false });
      return bootstrap({ suppressRecovery: true });
    }
    throw error;
  }
}

export async function submitMessage(event) {
  event.preventDefault();
  if (state.isSubmitting) {
    return;
  }

  const content = readTrimmedValue("goal");
  if (!content) {
    focusById("goal");
    return;
  }

  state.isSubmitting = true;
  renderApp();

  try {
    let detail;
    if (state.selectedSessionId) {
      detail = normalizeSessionDetail(
        await fetchJson(`/api/chat/sessions/${encodeURIComponent(state.selectedSessionId)}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        }),
      );
    } else {
      detail = normalizeSessionDetail(
        await fetchJson(API.SESSIONS, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config_path: readTrimmedValue("config-path"),
            message: content,
            engagement_name: readTrimmedValue("engagement-name") || null,
            authorization: readTrimmedValue("authorization-code") || null,
            start_url: readTrimmedValue("start-url") || null,
            allowed_hosts: normalizeLines(readValue("allowed-hosts")),
            allow_subdomains: readChecked("allow-subdomains", true),
            engagement_notes: readTrimmedValue("engagement-notes") || null,
            skill_dirs: normalizeLines(readValue("skill-dirs")),
            knowledge_base_ids: collectSelectedKnowledgeBaseIds(),
          }),
        }),
      );
      state.selectedSessionId = detail.id;
      state.findings = [];
      state.findingsSessionId = null;
      state.steps = [];
      state.stepsSessionId = null;
    }

    state.sessionDetails.set(detail.id, detail);
    upsertSessionSummary(detail);
    setValue("goal", "");
    renderApp();
  } catch (error) {
    if (isTransientTransportError(error)) {
      try {
        await recoverServerConnection({ refresh: true });
        return;
      } catch (recoveryError) {
        error = recoveryError;
      }
    }
    const root = byId("chat-thread");
    if (root) {
      root.innerHTML = `
        <article class="message assistant message-failed">
          <div class="message-label-row">
            <span class="message-label">助手</span>
          </div>
          <div class="message-bubble">
            <div class="markdown-body">${renderMarkdown(`发送失败：${String(error.message || error)}`)}</div>
          </div>
        </article>
      `;
    }
    window.alert(`发送失败：${String(error.message || error)}`);
  } finally {
    state.isSubmitting = false;
    renderApp();
  }
}

export function wireApprovalButtons() {
  const approveButton = byId("approval-approve-button");
  const denyButton = byId("approval-deny-button");
  const backdrop = byId("approval-backdrop");
  if (approveButton) {
    approveButton.addEventListener("click", () => {
      respondToApproval(true);
    });
  }
  if (denyButton) {
    denyButton.addEventListener("click", () => {
      respondToApproval(false);
    });
  }
  if (backdrop) {
    backdrop.addEventListener("click", () => {
      if (currentApprovalRequestId) {
        fetchJson(`/api/chat/approvals/${encodeURIComponent(currentApprovalRequestId)}/cancel`, {
          method: "POST",
        }).catch(() => {});
      }
      hideApprovalModal();
    });
  }
}

let loadedCommands = null;

async function loadCommands() {
  if (loadedCommands) {
    return loadedCommands;
  }
  try {
    const payload = await fetchJson(API.COMMANDS);
    loadedCommands = payload.commands || [];
    return loadedCommands;
  } catch {
    return [];
  }
}

function showCommandSuggestions(commands, filter) {
  const container = byId("command-suggestions");
  if (!container) {
    return;
  }
  const filtered = commands.filter((cmd) => {
    const name = String(cmd.name || "").toLowerCase();
    const aliases = Array.isArray(cmd.aliases) ? cmd.aliases.map((a) => String(a).toLowerCase()) : [];
    const q = String(filter || "").toLowerCase();
    return name.startsWith(q) || aliases.some((a) => a.startsWith(q));
  });
  if (!filtered.length) {
    container.hidden = true;
    return;
  }
  container.innerHTML = filtered
    .map(
      (cmd, idx) =>
        `<button class="command-suggestion-item${idx === 0 ? " selected" : ""}" data-command-name="${escapeHtml(cmd.name)}" type="button">
          <span class="command-suggestion-name">${escapeHtml(cmd.name)}</span>
          <span class="command-suggestion-desc">${escapeHtml(cmd.description || "")}</span>
        </button>`,
    )
    .join("");
  container.hidden = false;
}

function hideCommandSuggestions() {
  const container = byId("command-suggestions");
  if (container) {
    container.hidden = true;
  }
}

export async function wireCommandAutocomplete() {
  const textarea = byId("goal");
  const suggestionsContainer = byId("command-suggestions");
  if (!textarea) {
    return;
  }
  const commands = await loadCommands();
  let selectedIndex = 0;

  textarea.addEventListener("input", async () => {
    const text = textarea.value || "";
    const cursorPos = textarea.selectionStart || 0;
    const beforeCursor = text.slice(0, cursorPos);
    // Only show suggestions when / is at the start of the input
    const slashMatch = beforeCursor.match(/^\/[a-zA-Z]*$/);
    if (slashMatch) {
      const filter = slashMatch[0];
      showCommandSuggestions(commands, filter);
      selectedIndex = 0;
    } else {
      hideCommandSuggestions();
    }
  });

  textarea.addEventListener("keydown", (event) => {
    if (!suggestionsContainer || suggestionsContainer.hidden) {
      return;
    }
    const items = Array.from(suggestionsContainer.querySelectorAll(".command-suggestion-item"));
    if (!items.length) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
      items.forEach((item, idx) => item.classList.toggle("selected", idx === selectedIndex));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      items.forEach((item, idx) => item.classList.toggle("selected", idx === selectedIndex));
    } else if (event.key === "Enter" && !event.shiftKey) {
      const selectedItem = items[selectedIndex];
      if (selectedItem) {
        event.preventDefault();
        const commandName = selectedItem.dataset.commandName || "";
        const text = textarea.value || "";
        const cursorPos = textarea.selectionStart || 0;
        const beforeCursor = text.slice(0, cursorPos);
        const afterCursor = text.slice(cursorPos);
        const slashMatch = beforeCursor.match(/^\/[a-zA-Z]*$/);
        if (slashMatch) {
          const newText = beforeCursor.slice(0, -slashMatch[0].length) + commandName + " " + afterCursor;
          textarea.value = newText;
          const newCursorPos = beforeCursor.length - slashMatch[0].length + commandName.length + 1;
          textarea.setSelectionRange(newCursorPos, newCursorPos);
        }
        hideCommandSuggestions();
      }
    } else if (event.key === "Escape") {
      hideCommandSuggestions();
    }
  });

  suggestionsContainer?.addEventListener("click", (event) => {
    const item = event.target.closest(".command-suggestion-item");
    if (!item) {
      return;
    }
    const commandName = item.dataset.commandName || "";
    const text = textarea.value || "";
    const cursorPos = textarea.selectionStart || 0;
    const beforeCursor = text.slice(0, cursorPos);
    const afterCursor = text.slice(cursorPos);
    const slashMatch = beforeCursor.match(/^\/[a-zA-Z]*$/);
    if (slashMatch) {
      const newText = beforeCursor.slice(0, -slashMatch[0].length) + commandName + " " + afterCursor;
      textarea.value = newText;
      const newCursorPos = beforeCursor.length - slashMatch[0].length + commandName.length + 1;
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    }
    hideCommandSuggestions();
    textarea.focus();
  });

  document.addEventListener("click", (event) => {
    if (!suggestionsContainer) {
      return;
    }
    if (!suggestionsContainer.contains(event.target) && event.target !== textarea) {
      hideCommandSuggestions();
    }
  });
}

export async function regenerateMessage(sessionId) {
  if (!sessionId) {
    return;
  }

  const detail = state.sessionDetails.get(String(sessionId));
  if (!detail || !Array.isArray(detail.messages)) {
    return;
  }

  const activeMessages = detail.messages.filter((msg) => !msg.compacted);
  if (!activeMessages.length) {
    return;
  }

  // Find the last user message content
  let lastUserContent = "";
  for (let i = activeMessages.length - 1; i >= 0; i--) {
    if (activeMessages[i].role === "user") {
      lastUserContent = messageText(activeMessages[i]);
      break;
    }
  }
  if (!lastUserContent) {
    return;
  }

  state.isSubmitting = true;
  _scheduleRenderApp();

  try {
    const response = normalizeSessionDetail(
      await fetchJson(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: lastUserContent }),
      }),
    );
    state.sessionDetails.set(response.id, response);
    upsertSessionSummary(response);
    renderApp();
  } catch (error) {
    if (isTransientTransportError(error)) {
      try {
        await recoverServerConnection({ refresh: true });
        return;
      } catch (recoveryError) {
        error = recoveryError;
      }
    }
    window.alert(`重新生成失败：${String(error.message || error)}`);
  } finally {
    state.isSubmitting = false;
    renderApp();
  }
}

export async function exportSession(sessionId, format = "markdown") {
  if (!sessionId) {
    return;
  }

  try {
    const url = `/api/chat/sessions/${encodeURIComponent(sessionId)}/export?format=${encodeURIComponent(format)}`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Export failed: ${response.status} ${response.statusText}`);
    }

    const contentDisposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = contentDisposition.match(/filename="?([^";\n]+)"?/);
    const fallbackTitle = (state.sessionDetails.get(String(sessionId))?.title || "session").replace(/[^a-zA-Z0-9\u4e00-\u9fff _-]/g, "_");
    const fallbackDate = new Date().toISOString().slice(0, 10);
    const filename = filenameMatch ? filenameMatch[1] : `session_${fallbackTitle}_${fallbackDate}.md`;

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(blobUrl);
  } catch (error) {
    window.alert(`导出失败：${String(error.message || error)}`);
  }
}
