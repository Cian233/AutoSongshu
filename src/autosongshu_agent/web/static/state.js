// Re-export from split modules for backward compatibility
export { setApiToken, getApiToken } from "./auth.js";
export { byId, escapeHtml, truncate, formatDate, normalizeLines, sanitizeUrl } from "./utils.js";

import { getApiToken } from "./auth.js";

export const state = {
  sessions: [],
  sessionDetails: new Map(),
  authorizations: [],
  knowledgeBases: [],
  knowledgeBaseDetails: new Map(),
  selectedKnowledgeBaseId: null,
  selectedKnowledgeBaseIds: [],
  knowledgeModalOpen: false,
  selectedSessionId: null,
  settingsOpen: false,
  eventSource: null,
  connectionState: "connecting",
  isSubmitting: false,
  artifactRoot: "",
  defaultConfigPath: "",
  defaultGoal: "",
  defaultAuthorizationDraft: null,
  assistantPartExpansion: new Map(),
  messageRenderFreeze: new Map(),
  chatAutoFollow: true,
  chatScrollSessionId: null,
  chatProgrammaticScrollUntil: 0,
  chatTouchStartY: null,
  chatLastScrollTop: 0,
  isDistillingKnowledge: false,
  findings: [],
  findingsSessionId: null,
  steps: [],
  stepsSessionId: null,
  progress: null,
  progressSessionId: null,
  panelExpansion: {
    steps: true,
    findings: true,
    shortcuts: false,
  },
  theme: "system",
};

const DEFAULT_FETCH_TIMEOUT_MS = 12000;

export function togglePanel(panelKey) {
  if (!state.panelExpansion) {
    state.panelExpansion = {};
  }
  state.panelExpansion[panelKey] = !state.panelExpansion[panelKey];
}

export function isAssistantPartExpanded(key, fallback = false) {
  const normalizedKey = String(key || "").trim();
  if (!normalizedKey) {
    return fallback;
  }
  if (!state.assistantPartExpansion.has(normalizedKey)) {
    return fallback;
  }
  return Boolean(state.assistantPartExpansion.get(normalizedKey));
}

export function setAssistantPartExpanded(key, expanded) {
  const normalizedKey = String(key || "").trim();
  if (!normalizedKey) {
    return;
  }
  state.assistantPartExpansion.set(normalizedKey, Boolean(expanded));
}

export function freezeMessageRendering(messageId) {
  const normalizedId = String(messageId || "").trim();
  if (!normalizedId) {
    return;
  }
  state.messageRenderFreeze.set(normalizedId, Number(state.messageRenderFreeze.get(normalizedId) || 0) + 1);
}

export function unfreezeMessageRendering(messageId) {
  const normalizedId = String(messageId || "").trim();
  if (!normalizedId) {
    return 0;
  }
  const nextValue = Number(state.messageRenderFreeze.get(normalizedId) || 0) - 1;
  if (nextValue > 0) {
    state.messageRenderFreeze.set(normalizedId, nextValue);
    return nextValue;
  }
  state.messageRenderFreeze.delete(normalizedId);
  return 0;
}

export function isMessageRenderingFrozen(messageId) {
  return Number(state.messageRenderFreeze.get(String(messageId || "").trim()) || 0) > 0;
}

export async function fetchJson(url, options = {}) {
  const { timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, ...fetchOptions } = options || {};
  const controller =
    typeof AbortController !== "undefined" && !fetchOptions.signal ? new AbortController() : null;
  const normalizedTimeoutMs = Number(timeoutMs);
  const timer =
    controller && Number.isFinite(normalizedTimeoutMs) && normalizedTimeoutMs > 0
      ? window.setTimeout(() => controller.abort(), normalizedTimeoutMs)
      : null;

  let response;
  try {
    // Inject API token if available
    const apiToken = getApiToken();
    if (apiToken) {
      fetchOptions.headers = fetchOptions.headers || {};
      fetchOptions.headers["Authorization"] = `Bearer ${apiToken}`;
    }
    response = await fetch(url, controller ? { ...fetchOptions, signal: controller.signal } : fetchOptions);
  } catch (error) {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
    if (controller?.signal?.aborted) {
      throw new Error("请求超时，请稍后重试。");
    }
    throw error;
  }

  if (timer !== null) {
    window.clearTimeout(timer);
  }

  const text = await response.text();
  let payload = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_) {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload && "detail" in payload
        ? payload.detail
        : typeof payload === "string" && payload
          ? payload
          : response.statusText;
    throw new Error(String(detail || "请求失败"));
  }

  return payload;
}

export function sortSessions() {
  state.sessions.sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")));
}

function fingerprintText(value, edge = 48) {
  const text = String(value ?? "");
  if (!text) {
    return "0";
  }
  if (text.length <= edge * 2) {
    return `${text.length}:${text}`;
  }
  return `${text.length}:${text.slice(0, edge)}:${text.slice(-edge)}`;
}

function stableSerializeValue(value) {
  if (value === null || value === undefined) {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerializeValue(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${key}:${stableSerializeValue(value[key])}`)
      .join(",")}}`;
  }
  return String(value);
}

function summarizeMessagePart(part) {
  const type = String(part?.type || "");
  if (!type) {
    return "unknown";
  }
  if (type === "input_text" || type === "output_text" || type === "reasoning") {
    return `${type}:${fingerprintText(part?.text || "")}`;
  }
  if (type === "tool_call") {
    return `${type}:${String(part?.id || part?.name || "")}:${fingerprintText(stableSerializeValue(part?.arguments || {}))}`;
  }
  if (type === "tool_result") {
    return `${type}:${String(part?.tool_call_id || part?.name || "")}:${fingerprintText(
      stableSerializeValue(Array.isArray(part?.content) ? part.content : []),
    )}`;
  }
  return type;
}

function createMessageRenderSignature(message, content) {
  const tail = content.slice(-3).map((part) => summarizeMessagePart(part)).join("|");
  return [
    String(message?.role || "assistant"),
    String(message?.status || ""),
    String(message?.error || ""),
    String(message?.updated_at || ""),
    String(message?.order_index || ""),
    String(content.length),
    tail,
  ].join("::");
}

function normalizeStoredMessage(message) {
  const role = String(message?.role || "assistant");
  const content = normalizeMessageContent(message?.content || [], role);
  return {
    ...message,
    role,
    content,
    render_signature: createMessageRenderSignature(message, content),
  };
}

export function normalizeSessionDetail(detail) {
  const messages = Array.isArray(detail?.messages)
    ? detail.messages
        .map((message) => normalizeStoredMessage(message))
        .sort(
          (left, right) =>
            Number(left.order_index || 0) - Number(right.order_index || 0) ||
            String(left.created_at || "").localeCompare(String(right.created_at || "")),
        )
    : [];

  return {
    ...detail,
    messages,
  };
}

export function upsertSessionSummary(summary) {
  const summaryId = String(summary.id || "");
  const index = state.sessions.findIndex((item) => String(item.id) === summaryId);
  if (index === -1) {
    state.sessions.push(summary);
  } else {
    state.sessions[index] = { ...state.sessions[index], ...summary };
  }
  sortSessions();

  const detail = state.sessionDetails.get(summaryId);
  if (detail) {
    state.sessionDetails.set(summaryId, { ...detail, ...summary });
  }
}

export function upsertMessage(detail, message) {
  const messages = Array.isArray(detail.messages) ? [...detail.messages] : [];
  const normalizedMessage = normalizeStoredMessage(message);
  const messageId = String(message.id || "");
  const index = messages.findIndex((item) => String(item.id) === messageId);
  if (index === -1) {
    messages.push(normalizedMessage);
  } else {
    messages[index] = { ...messages[index], ...normalizedMessage };
  }
  messages.sort(
    (left, right) =>
      Number(left.order_index || 0) - Number(right.order_index || 0) ||
      String(left.created_at || "").localeCompare(String(right.created_at || "")),
  );
  return { ...detail, messages };
}

export function selectedSession() {
  if (!state.selectedSessionId) {
    return null;
  }
  const sessionId = String(state.selectedSessionId);
  return (
    state.sessionDetails.get(sessionId) ||
    state.sessions.find((item) => String(item.id) === sessionId) ||
    null
  );
}

function appendNormalizedPart(parts, part) {
  if (!part) {
    return;
  }

  const type = String(part.type || "").toLowerCase();
  if (type === "input_text" || type === "output_text" || type === "reasoning") {
    const text = String(part.text || "").trim();
    if (!text) {
      return;
    }

    const last = parts[parts.length - 1];
    if (last && String(last.type || "").toLowerCase() === type) {
      const previousText = String(last.text || "").trim();
      if (text === previousText || previousText.startsWith(text)) {
        return;
      }
      if (text.startsWith(previousText)) {
        last.text = text;
        return;
      }
    }

    parts.push({ type, text });
    return;
  }

  const last = parts[parts.length - 1];
  if (last && type === "tool_call" && String(last.type || "").toLowerCase() === "tool_call") {
    if (String(last.id || "") === String(part.id || "")) {
      parts[parts.length - 1] = part;
      return;
    }
  }

  if (last && type === "tool_result" && String(last.type || "").toLowerCase() === "tool_result") {
    if (
      String(last.tool_call_id || "") === String(part.tool_call_id || "") &&
      String(last.name || "") === String(part.name || "")
    ) {
      parts[parts.length - 1] = part;
      return;
    }
  }

  parts.push(part);
}

function matchScore(existing, incoming) {
  const existingType = String(existing?.type || "").toLowerCase();
  const incomingType = String(incoming?.type || "").toLowerCase();
  if (existingType !== incomingType) {
    return 0;
  }

  if (existingType === "input_text" || existingType === "output_text" || existingType === "reasoning") {
    const existingText = String(existing?.text || "").trim();
    const incomingText = String(incoming?.text || "").trim();
    if (!existingText || !incomingText) {
      return 0;
    }
    if (existingText === incomingText) {
      return 400 + existingText.length;
    }
    if (existingText.startsWith(incomingText) || incomingText.startsWith(existingText)) {
      return 300 + Math.min(existingText.length, incomingText.length);
    }
    return 0;
  }

  if (existingType === "tool_call") {
    return String(existing?.id || "") === String(incoming?.id || "") ? 500 : 0;
  }

  if (existingType === "tool_result") {
    return String(existing?.tool_call_id || "") === String(incoming?.tool_call_id || "") &&
      String(existing?.name || "") === String(incoming?.name || "")
      ? 500
      : 0;
  }

  return JSON.stringify(existing) === JSON.stringify(incoming) ? 100 : 0;
}

function findBestMatchIndex(parts, incoming, startIndex = 0) {
  let bestIndex = -1;
  let bestScore = 0;
  for (let index = Math.max(0, startIndex); index < parts.length; index += 1) {
    const score = matchScore(parts[index], incoming);
    if (score <= bestScore) {
      continue;
    }
    bestIndex = index;
    bestScore = score;
    if (score >= 500) {
      break;
    }
  }
  return bestIndex;
}

function mergeNormalizedPart(existing, incoming) {
    const type = String(existing?.type || "").toLowerCase();
    if (type === "input_text" || type === "output_text" || type === "reasoning") {
      const existingText = String(existing?.text || "").trim();
      const incomingText = String(incoming?.text || "").trim();
      if (incomingText.startsWith(existingText)) {
        return { type, text: incomingText };
      }
      return existingText.length >= incomingText.length ? existing : incoming;
    }
    if (type === "tool_call") {
      const existingArgs = JSON.stringify(existing?.arguments || {});
      const incomingArgs = JSON.stringify(incoming?.arguments || {});
      return existingArgs.length >= incomingArgs.length ? existing : incoming;
    }
    return incoming;
  }

function compactAssistantParts(parts) {
  const compacted = [];
  for (const part of parts) {
    const matchIndex = findBestMatchIndex(compacted, part, 0);
    if (matchIndex !== -1) {
      compacted[matchIndex] = mergeNormalizedPart(compacted[matchIndex], part);
      continue;
    }
    appendNormalizedPart(compacted, part);
  }
  return compacted;
}

export function normalizeMessagePart(part, role = "assistant") {
  if (!part || typeof part !== "object") {
    return null;
  }

  const normalizedRole = String(role || "").toLowerCase();
  const type = String(part.type || "").toLowerCase();

  if (normalizedRole === "user") {
    const text = String(part.text || part.content || "").trim();
    return text ? { type: "input_text", text } : null;
  }

  if (type === "reasoning" || type === "thinking" || type === "thinking_text") {
    const text = String(part.text || part.thinking_text || part.thinking || "").trim();
    return text ? { type: "reasoning", text } : null;
  }

  if (type === "output_text" || type === "text" || type === "progress_text" || type === "input_text") {
    const text = String(part.text || part.content || "").trim();
    return text ? { type: "output_text", text } : null;
  }

  if (type === "tool_call" || type === "tool_use") {
    const argumentsPayload =
      part.arguments && typeof part.arguments === "object"
        ? part.arguments
        : part.input && typeof part.input === "object"
          ? part.input
          : { value: part.arguments ?? part.input ?? "" };
    const fallbackId = `tool:${String(part.name || "tool")}:${JSON.stringify(argumentsPayload)}`;
    return {
      type: "tool_call",
      id: String(part.id || fallbackId),
      name: String(part.name || "tool"),
      arguments: argumentsPayload,
    };
  }

  if (type === "tool_result") {
    const rawContent = Array.isArray(part.content)
      ? part.content
      : Array.isArray(part.output)
        ? part.output
        : [];
    const content = rawContent
      ? rawContent
          .map((item) => {
            if (!item || typeof item !== "object") {
              return { type: "output_text", text: String(item ?? "") };
            }
            const itemType = String(item.type || "").toLowerCase();
            if (itemType === "output_text" || itemType === "text") {
              return { type: "output_text", text: String(item.text || "") };
            }
            return { type: "output_text", text: JSON.stringify(item, null, 2) };
          })
          .filter((item) => String(item.text || "").trim())
      : [];
    return {
      type: "tool_result",
      tool_call_id: String(part.tool_call_id || part.id || ""),
      name: String(part.name || ""),
      content,
    };
  }

  const text = String(part.text || part.content || "").trim();
  return text ? { type: "output_text", text } : null;
}

export function normalizeMessageContent(content, role = "assistant") {
  const items = Array.isArray(content) ? content : content == null ? [] : [content];
  const parts = [];
  for (const item of items) {
    appendNormalizedPart(parts, normalizeMessagePart(item, role));
  }
  return String(role || "").toLowerCase() === "assistant" ? compactAssistantParts(parts) : parts;
}

export function getMessageParts(message) {
  if (Array.isArray(message?.content) && typeof message?.render_signature === "string") {
    return message.content;
  }
  return normalizeMessageContent(message?.content || [], String(message?.role || "assistant"));
}

export function messageText(message) {
  return getMessageParts(message)
    .filter((part) => part.type === "input_text" || part.type === "output_text")
    .map((part) => String(part.text || "").trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

export function getSessionRuntimeSnapshot(session) {
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const assistantMessage = [...messages].reverse().find((message) => String(message?.role || "") === "assistant") || null;
  const parts = assistantMessage ? getMessageParts(assistantMessage) : [];
  const toolStates = new Map();
  let latestToolResultName = "";
  let latestOutputText = "";
  let reasoningCount = 0;

  for (const part of parts) {
    const type = String(part?.type || "").toLowerCase();
    if (type === "reasoning") {
      reasoningCount += 1;
      continue;
    }

    if (type === "output_text") {
      const text = String(part?.text || "").trim();
      if (text) {
        latestOutputText = text;
      }
      continue;
    }

    if (type === "tool_call") {
      const toolCallId = String(part?.id || "");
      const key = toolCallId || `tool:${String(part?.name || "tool")}`;
      const current = toolStates.get(key) || {
        name: String(part?.name || "tool"),
        hasCall: false,
        hasResult: false,
      };
      current.name = String(part?.name || current.name || "tool");
      current.hasCall = true;
      toolStates.set(key, current);
      continue;
    }

    if (type === "tool_result") {
      const toolCallId = String(part?.tool_call_id || "");
      const key = toolCallId || `tool:${String(part?.name || "tool")}`;
      const current = toolStates.get(key) || {
        name: String(part?.name || "tool"),
        hasCall: false,
        hasResult: false,
      };
      current.name = String(part?.name || current.name || "tool");
      current.hasResult = true;
      toolStates.set(key, current);
      latestToolResultName = current.name;
    }
  }

  const toolItems = Array.from(toolStates.values());
  const pendingToolNames = toolItems.filter((item) => !item.hasResult).map((item) => item.name);
  const completedToolNames = toolItems.filter((item) => item.hasResult).map((item) => item.name);

  return {
    assistantStatus: String(assistantMessage?.status || session?.status || ""),
    latestOutputText,
    latestToolName: pendingToolNames[pendingToolNames.length - 1] || latestToolResultName || "",
    latestToolResultName,
    pendingToolNames,
    pendingToolCount: pendingToolNames.length,
    completedToolCount: completedToolNames.length,
    reasoningCount,
    updatedAt: String(assistantMessage?.updated_at || session?.updated_at || session?.created_at || ""),
  };
}

export function renderConnectionState() {
  const map = {
    connected: { label: "已连接", className: "status-connected" },
    reconnecting: { label: "重连中", className: "status-reconnecting" },
    connecting: { label: "连接中", className: "status-reconnecting" },
    disconnected: { label: "已断开", className: "status-error" },
  };
  return map[state.connectionState] || map.disconnected;
}

export function isSessionCompacting(session) {
  return Boolean(session?.is_compacting);
}

export function isSessionBusyStatus(status) {
  return status === "running" || status === "interrupting" || status === "in_progress";
}

export function formatStatusText(status) {
  const map = {
    idle: "已就绪",
    running: "生成中",
    interrupting: "中断中",
    error: "异常",
    failed: "失败",
    completed: "已完成",
    in_progress: "处理中",
  };
  return map[status] || status || "未知";
}

export function statusClass(status) {
  if (isSessionBusyStatus(status)) {
    return "status-running";
  }
  if (status === "error" || status === "failed") {
    return "status-error";
  }
  return "status-idle";
}
