import {
  byId,
  fetchJson,
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
        await fetchJson(`/api/health?_=${Date.now()}`, { timeoutMs: 3000 });
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
  state.sessionDetails.set(detail.id, detail);
  upsertSessionSummary(detail);
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
    const payload = await fetchJson("/api/chat/sessions");
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

  const eventSource = new EventSource("/api/chat/events");
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
    const payload = JSON.parse(event.data);
    upsertSessionSummary(payload.session);
    _scheduleRenderApp();
  });

  eventSource.addEventListener("message.upsert", (event) => {
    const payload = JSON.parse(event.data);
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
    const payload = await fetchJson("/api/bootstrap");
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
        await fetchJson("/api/chat/sessions", {
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
