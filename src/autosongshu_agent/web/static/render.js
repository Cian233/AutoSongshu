import {
  byId,
  escapeHtml,
  formatDate,
  formatStatusText,
  getSessionRuntimeSnapshot,
  getMessageParts,
  isAssistantPartExpanded,
  isMessageRenderingFrozen,
  isSessionCompacting,
  isSessionBusyStatus,
  messageText,
  renderConnectionState,
  selectedSession,
  state,
  statusClass,
  truncate,
} from "./state.js";
import { renderCodeBlock, renderJsonBlock, renderMarkdown, getCachedMarkdown } from "./markdown.js";

const bootstrap = window.__AUTOSONGSHU_BOOTSTRAP__ || {};
const CHAT_AUTOFOLLOW_THRESHOLD_PX = 40;
const CHAT_TOUCH_RELEASE_DELTA_PX = 8;
const CHAT_PROGRAMMATIC_SCROLL_GUARD_MS = 180;

function setNodeText(target, value) {
  if (!target) {
    return;
  }
  target.textContent = value;
}

function setNodeValue(target, value) {
  if (!target) {
    return;
  }
  target.value = value;
}

function setNodeChecked(target, value) {
  if (!target) {
    return;
  }
  target.checked = value;
}

function readNodeValue(id) {
  return byId(id)?.value ?? "";
}

function readNodeLines(id) {
  return readNodeValue(id)
    .split(/\r?\n/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeIdList(values) {
  const normalized = [];
  const seen = new Set();
  for (const value of values || []) {
    const item = String(value || "").trim();
    if (!item || seen.has(item)) {
      continue;
    }
    seen.add(item);
    normalized.push(item);
  }
  return normalized;
}

const SESSION_GROUP_ORDER = ["today", "yesterday", "week", "month", "earlier"];

function startOfLocalDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function sessionGroupKey(timestamp) {
  const value = new Date(timestamp || "");
  if (Number.isNaN(value.getTime())) {
    return "earlier";
  }

  const today = startOfLocalDay(new Date());
  const target = startOfLocalDay(value);
  const diffDays = Math.floor((today - target) / 86400000);

  if (diffDays <= 0) {
    return "today";
  }
  if (diffDays === 1) {
    return "yesterday";
  }
  if (diffDays < 7) {
    return "week";
  }
  if (diffDays < 30) {
    return "month";
  }
  return "earlier";
}

function sessionGroupLabel(key) {
  const labels = {
    today: "今天",
    yesterday: "昨天",
    week: "7 天内",
    month: "30 天内",
    earlier: "更早",
  };
  return labels[key] || labels.earlier;
}

function groupSessionsByDate(sessions) {
  const buckets = new Map(SESSION_GROUP_ORDER.map((key) => [key, []]));

  for (const session of sessions) {
    const key = sessionGroupKey(session.updated_at || session.created_at);
    buckets.get(key)?.push(session);
  }

  return SESSION_GROUP_ORDER.map((key) => ({
    key,
    label: sessionGroupLabel(key),
    items: buckets.get(key) || [],
  })).filter((group) => group.items.length);
}

function sessionTrailingMarkup(session, isActive) {
  const status = String(session.status || "");
  if (isSessionCompacting(session) && !isSessionBusyStatus(status)) {
    return `<span class="session-item-badge is-compacting">压缩中</span>`;
  }
  if (status === "interrupting") {
    return `<span class="session-item-badge is-running">中断中</span>`;
  }
  if (isSessionBusyStatus(status)) {
    return `<span class="session-item-badge is-running">进行中</span>`;
  }
  if (status === "error" || status === "failed") {
    return `<span class="session-item-badge is-error">异常</span>`;
  }
  if (isActive) {
    return `<span class="session-item-more" aria-hidden="true">⋯</span>`;
  }
  return `<span class="session-item-dot ${escapeHtml(statusClass(status))}" aria-hidden="true"></span>`;
}

function runtimeHeadline(session, snapshot) {
  const status = String(session?.status || "");
  if (isSessionCompacting(session) && !isSessionBusyStatus(status)) {
    return "正在压缩记忆，整理更早的上下文";
  }
  if (status === "interrupting") {
    return "正在尝试中断当前执行";
  }
  if (status === "error" || status === "failed") {
    return "本轮执行发生异常";
  }
  if (isSessionBusyStatus(status)) {
    if (snapshot.pendingToolCount && snapshot.latestToolName) {
      return `正在执行 ${truncate(snapshot.latestToolName, 34)}`;
    }
    if (snapshot.completedToolCount) {
      return "工具已返回，正在整理结果";
    }
    if (snapshot.reasoningCount) {
      return "正在分析任务并规划下一步";
    }
    return "模型正在处理当前请求";
  }
  if (snapshot.completedToolCount) {
    return "本轮已完成，可以继续追问";
  }
  return "会话已就绪";
}

function runtimeDetail(session, snapshot) {
  const detailParts = [];
  const connection = renderConnectionState();
  detailParts.push(connection.label);
  if (isSessionCompacting(session) && !isSessionBusyStatus(session?.status)) {
    detailParts.push("后台正在压缩记忆，不影响继续输入");
  }

  if (snapshot.pendingToolCount) {
    detailParts.push(`待返回 ${snapshot.pendingToolCount} 个工具结果`);
  }
  if (snapshot.completedToolCount) {
    detailParts.push(`已完成 ${snapshot.completedToolCount} 次工具调用`);
  }
  if (!snapshot.pendingToolCount && snapshot.latestToolResultName) {
    detailParts.push(`最近工具 ${truncate(snapshot.latestToolResultName, 28)}`);
  }
  if (!snapshot.completedToolCount && snapshot.latestOutputText) {
    detailParts.push(truncate(snapshot.latestOutputText, 48));
  }
  if (snapshot.updatedAt) {
    detailParts.push(`更新于 ${formatDate(snapshot.updatedAt)}`);
  }

  return detailParts.join(" · ");
}

function toolResultText(part) {
  return (part?.content || [])
    .filter((item) => String(item?.type || "").toLowerCase() === "output_text")
    .map((item) => String(item?.text || "").trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

function assistantPartKey(messageId, kind, identifier) {
  return `${String(messageId || "message")}:${kind}:${String(identifier || "part")}`;
}

function assistantPartOpenAttr(key, fallback = false) {
  return isAssistantPartExpanded(key, fallback) ? "open" : "";
}

function toolStatusLabel(toolItem, message) {
  if (toolItem.toolResult) {
    if (toolItem.toolResult.error) {
      return "失败";
    }
    return "已返回";
  }
  if (message?.status === "in_progress") {
    return "运行中";
  }
  if (message?.status === "failed") {
    return "已中断";
  }
  return "等待结果";
}

function toolStatusClass(toolItem, message) {
  if (toolItem.toolResult) {
    if (toolItem.toolResult.error) {
      return "is-error";
    }
    return "is-success";
  }
  if (message?.status === "in_progress") {
    return "is-running";
  }
  if (message?.status === "failed") {
    return "is-error";
  }
  return "is-pending";
}

function toolIconMeta(name) {
  const normalizedName = String(name || "tool").toLowerCase();
  if (normalizedName.startsWith("browser_")) {
    return {
      variant: "browser",
      label: "浏览器",
      svg: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="14" rx="3" stroke="currentColor" stroke-width="1.8"/>
          <path d="M3.5 9H20.5" stroke="currentColor" stroke-width="1.8"/>
          <circle cx="6.5" cy="7" r="1" fill="currentColor"/>
          <circle cx="9.5" cy="7" r="1" fill="currentColor"/>
        </svg>
      `,
    };
  }
  if (normalizedName.startsWith("sandbox_") || normalizedName.includes("python") || normalizedName.includes("shell")) {
    return {
      variant: "sandbox",
      label: "沙箱",
      svg: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="4" width="17" height="16" rx="3" stroke="currentColor" stroke-width="1.8"/>
          <path d="M7 9L10 12L7 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M12.5 15H17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      `,
    };
  }
  if (
    normalizedName.startsWith("http_") ||
    normalizedName.includes("request") ||
    normalizedName.includes("fetch") ||
    normalizedName.includes("curl")
  ) {
    return {
      variant: "network",
      label: "网络",
      svg: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/>
          <path d="M4.5 12H19.5" stroke="currentColor" stroke-width="1.8"/>
          <path d="M12 4.5C14.5 7 15.8 9.5 15.8 12C15.8 14.5 14.5 17 12 19.5C9.5 17 8.2 14.5 8.2 12C8.2 9.5 9.5 7 12 4.5Z" stroke="currentColor" stroke-width="1.8"/>
        </svg>
      `,
    };
  }
  if (
    normalizedName.includes("file") ||
    normalizedName.includes("artifact") ||
    normalizedName.startsWith("fs_") ||
    normalizedName.includes("read") ||
    normalizedName.includes("write")
  ) {
    return {
      variant: "file",
      label: "文件",
      svg: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M7 4.5H13L17.5 9V18.5C17.5 19.0523 17.0523 19.5 16.5 19.5H7.5C6.94772 19.5 6.5 19.0523 6.5 18.5V5.5C6.5 4.94772 6.94772 4.5 7.5 4.5Z" stroke="currentColor" stroke-width="1.8"/>
          <path d="M13 4.5V9H17.5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
        </svg>
      `,
    };
  }
  if (normalizedName.includes("search") || normalizedName.includes("scan") || normalizedName.includes("find")) {
    return {
      variant: "search",
      label: "搜索",
      svg: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="5.5" stroke="currentColor" stroke-width="1.8"/>
          <path d="M15.5 15.5L19 19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      `,
    };
  }
  return {
    variant: "default",
    label: "工具",
    svg: `
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M14.5 6.5A4 4 0 0 0 9 11L5 15V19H9L13 15A4 4 0 0 0 17.5 9.5L14 13L11 10L14.5 6.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
      </svg>
    `,
  };
}

function buildAssistantTimelineItems(message) {
  const parts = getMessageParts(message);
  const items = [];
  const toolIndexes = new Map();
  let reasoningCount = 0;
  let outputCount = 0;

  for (const part of parts) {
    if (part.type === "reasoning") {
      items.push({
        type: "reasoning",
        key: assistantPartKey(message?.id, "reasoning", reasoningCount),
        part,
        index: reasoningCount,
      });
      reasoningCount += 1;
      continue;
    }

    if (part.type === "tool_call") {
      const toolCallId = String(part.id || assistantPartKey(message?.id, "tool", items.length));
      const existingIndex = toolIndexes.get(toolCallId);
      if (typeof existingIndex === "number") {
        items[existingIndex] = { ...items[existingIndex], toolCall: part, name: part.name || items[existingIndex].name };
        continue;
      }
      toolIndexes.set(toolCallId, items.length);
      items.push({
        type: "tool",
        key: assistantPartKey(message?.id, "tool", toolCallId),
        toolCallId,
        name: part.name || "tool",
        toolCall: part,
        toolResult: null,
      });
      continue;
    }

    if (part.type === "tool_result") {
      const toolCallId = String(part.tool_call_id || "");
      let existingIndex = toolIndexes.get(toolCallId);

      if (typeof existingIndex !== "number" && part.name) {
        for (let i = items.length - 1; i >= 0; i--) {
          const item = items[i];
          if (item.type === "tool" && !item.toolResult && item.name === part.name) {
            existingIndex = i;
            if (toolCallId) {
              toolIndexes.set(toolCallId, i);
            }
            break;
          }
        }
      }

      if (typeof existingIndex === "number") {
        items[existingIndex] = {
          ...items[existingIndex],
          name: part.name || items[existingIndex].name,
          toolResult: part,
        };
        continue;
      }

      const fallbackId = toolCallId || assistantPartKey(message?.id, "tool-result", items.length);
      toolIndexes.set(fallbackId, items.length);
      items.push({
        type: "tool",
        key: assistantPartKey(message?.id, "tool", fallbackId),
        toolCallId: fallbackId,
        name: part.name || "tool",
        toolCall: null,
        toolResult: part,
      });
      continue;
    }

    items.push({
      type: "output",
      key: assistantPartKey(message?.id, "output", outputCount),
      part,
      index: outputCount,
    });
    outputCount += 1;
  }

  return items;
}

function renderReasoningPart(part, partKey, isOpen) {
  const preview = truncate(part.text, 68) || "思考内容";
  return `
    <details class="assistant-part assistant-part-reasoning" data-assistant-part-key="${escapeHtml(partKey)}" ${assistantPartOpenAttr(partKey, isOpen)}>
      <summary>
        <span class="assistant-part-heading-copy">
          <span class="assistant-part-kicker">思考过程</span>
          <span class="assistant-part-title">${escapeHtml(preview)}</span>
        </span>
      </summary>
      <div class="assistant-part-body markdown-body">${renderMarkdown(part.text)}</div>
    </details>
  `;
}

function renderToolPart(toolItem, message) {
  const icon = toolIconMeta(toolItem.name);
  const statusLabel = toolStatusLabel(toolItem, message);
  const statusClassName = toolStatusClass(toolItem, message);
  const argumentsBlock = toolItem.toolCall
    ? renderToolArguments(toolItem.toolCall)
    : `<div class="assistant-part-empty">等待调用参数</div>`;
  const resultBlock = toolItem.toolResult
    ? renderToolResult(toolItem)
    : `<div class="assistant-part-empty">工具结果尚未返回</div>`;

  return `
    <details class="assistant-part assistant-part-tool assistant-part-tool-${escapeHtml(icon.variant)}" data-assistant-part-key="${escapeHtml(toolItem.key)}" ${assistantPartOpenAttr(toolItem.key, false)}>
      <summary>
        <span class="assistant-part-heading">
          <span class="assistant-part-icon assistant-part-icon-${escapeHtml(icon.variant)}" aria-hidden="true">
            ${icon.svg}
          </span>
          <span class="assistant-part-heading-copy">
            <span class="assistant-part-kicker">${escapeHtml(icon.label)}</span>
            <span class="assistant-part-title">${escapeHtml(toolItem.name || "工具")}</span>
          </span>
        </span>
        <span class="assistant-part-status ${escapeHtml(statusClassName)}">${escapeHtml(statusLabel)}</span>
      </summary>
      <div class="assistant-part-body assistant-part-tool-body">
        <section class="assistant-part-section">
          <div class="assistant-part-section-title">调用参数</div>
          ${argumentsBlock}
        </section>
        <section class="assistant-part-section">
          <div class="assistant-part-section-title">返回结果</div>
          ${resultBlock}
        </section>
      </div>
    </details>
  `;
}

function tryParseJsonText(rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function inferCodeLanguageFromPath(path) {
  const normalizedPath = String(path || "").trim().toLowerCase();
  if (!normalizedPath) {
    return "text";
  }
  if (normalizedPath.endsWith(".py")) {
    return "python";
  }
  if (normalizedPath.endsWith(".json")) {
    return "json";
  }
  if (normalizedPath.endsWith(".js") || normalizedPath.endsWith(".mjs") || normalizedPath.endsWith(".cjs")) {
    return "javascript";
  }
  if (normalizedPath.endsWith(".ts") || normalizedPath.endsWith(".tsx")) {
    return "typescript";
  }
  if (normalizedPath.endsWith(".html") || normalizedPath.endsWith(".htm")) {
    return "html";
  }
  if (normalizedPath.endsWith(".css")) {
    return "css";
  }
  if (normalizedPath.endsWith(".sh") || normalizedPath.endsWith(".bash")) {
    return "bash";
  }
  return "text";
}

function hasVisibleValue(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

function formatEditModeLabel(mode) {
  return String(mode || "").toLowerCase() === "replace_lines" ? "按行替换" : "精确替换";
}

function formatLineRange(startLine, endLine) {
  if (!startLine || !endLine) {
    return "";
  }
  return startLine === endLine ? `第 ${startLine} 行` : `第 ${startLine}-${endLine} 行`;
}

function renderToolMetaChips(entries) {
  const visibleEntries = entries.filter((entry) => hasVisibleValue(entry?.value));
  if (!visibleEntries.length) {
    return "";
  }
  return `
    <div class="assistant-part-tool-meta">
      ${visibleEntries
        .map(
          (entry) => `
            <span class="assistant-part-tool-meta-chip">
              <span>${escapeHtml(entry.label || "")}</span>
              <strong>${escapeHtml(String(entry.value))}</strong>
            </span>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderToolNote(text, tone = "muted") {
  if (!String(text || "").trim()) {
    return "";
  }
  return `<div class="assistant-part-tool-note${tone ? ` is-${escapeHtml(tone)}` : ""}">${escapeHtml(text)}</div>`;
}

function renderToolCodeCard(title, content, language, options = {}) {
  const { allowEmpty = false, emptyLabel = "空内容", subtitle = "" } = options;
  const normalizedContent = typeof content === "string" ? content : String(content ?? "");
  const hasContent = normalizedContent.length > 0;
  if (!hasContent && !allowEmpty) {
    return "";
  }

  const body = hasContent
    ? renderCodeBlock(normalizedContent, language, title)
    : `<div class="assistant-part-empty assistant-part-empty-compact">${escapeHtml(emptyLabel)}</div>`;

  return `
    <section class="assistant-part-tool-card">
      <div class="assistant-part-tool-card-head">
        <strong>${escapeHtml(title)}</strong>
        ${subtitle ? `<span>${escapeHtml(subtitle)}</span>` : ""}
      </div>
      ${body}
    </section>
  `;
}

function renderToolStructuredBlock(metaMarkup, bodyMarkup, noteMarkup = "") {
  return `
    <div class="assistant-part-tool-structured">
      ${metaMarkup}
      ${bodyMarkup}
      ${noteMarkup}
    </div>
  `;
}

function parseSandboxMultieditArguments(argumentsValue) {
  if (Array.isArray(argumentsValue?.edits)) {
    return argumentsValue.edits.filter((item) => item && typeof item === "object");
  }
  if (typeof argumentsValue?.edits_json !== "string") {
    return [];
  }
  const parsed = tryParseJsonText(argumentsValue.edits_json);
  return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") : [];
}

function renderSandboxWriteArguments(argumentsValue) {
  const snippetLanguage = inferCodeLanguageFromPath(argumentsValue.path);
  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: argumentsValue.path },
    { label: "方式", value: "整文件写入" },
  ]);
  const bodyMarkup = renderToolCodeCard("写入内容", String(argumentsValue.content || ""), snippetLanguage, {
    allowEmpty: Object.prototype.hasOwnProperty.call(argumentsValue, "content"),
    emptyLabel: "写入空文件",
  });
  const noteMarkup = renderToolNote("write_file 会直接创建新文件，或覆盖已有文件的全部内容。", "info");
  return renderToolStructuredBlock(metaMarkup, bodyMarkup, noteMarkup);
}

function renderSandboxSingleEditArguments(argumentsValue) {
  const snippetLanguage = inferCodeLanguageFromPath(argumentsValue.path);
  const oldSnippet =
    typeof argumentsValue.old_text === "string" && argumentsValue.old_text.length
      ? argumentsValue.old_text
      : typeof argumentsValue.expected_old_text === "string"
        ? argumentsValue.expected_old_text
        : "";
  const oldLabel = typeof argumentsValue.old_text === "string" && argumentsValue.old_text.length ? "原片段" : "当前片段";
  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: argumentsValue.path },
    {
      label: "模式",
      value: formatEditModeLabel(
        argumentsValue.start_line && argumentsValue.end_line ? "replace_lines" : "replace_text",
      ),
    },
    { label: "范围", value: formatLineRange(argumentsValue.start_line, argumentsValue.end_line) },
    { label: "策略", value: argumentsValue.replace_all ? "全部替换" : "" },
  ]);

  const bodyMarkup = `
    <div class="assistant-part-tool-card-list">
      ${renderToolCodeCard(oldLabel, String(oldSnippet || ""), snippetLanguage, {
        allowEmpty: typeof argumentsValue.expected_old_text === "string",
        emptyLabel: "匹配空内容",
      })}
      ${renderToolCodeCard("替换为", String(argumentsValue.new_text || ""), snippetLanguage, {
        allowEmpty: Object.prototype.hasOwnProperty.call(argumentsValue, "new_text"),
        emptyLabel: "删除这段内容",
      })}
      ${
        argumentsValue.max_diff_chars && Number(argumentsValue.max_diff_chars) !== 12000
          ? renderJsonBlock("其他参数", { max_diff_chars: argumentsValue.max_diff_chars })
          : ""
      }
    </div>
  `;

  return renderToolStructuredBlock(metaMarkup, bodyMarkup);
}

function renderSandboxMultieditArguments(argumentsValue) {
  const snippetLanguage = inferCodeLanguageFromPath(argumentsValue.path);
  const edits = parseSandboxMultieditArguments(argumentsValue);
  if (!edits.length) {
    return renderJsonBlock("参数", argumentsValue);
  }

  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: argumentsValue.path },
    { label: "修改数", value: `${edits.length} 处` },
  ]);

  const bodyMarkup = `
    <div class="assistant-part-tool-change-list">
      ${edits
        .map((edit, index) => {
          const oldSnippet =
            typeof edit.old_text === "string" && edit.old_text.length
              ? edit.old_text
              : typeof edit.expected_old_text === "string"
                ? edit.expected_old_text
                : "";
          const lineRange = formatLineRange(edit.start_line, edit.end_line);
          const cardMeta = renderToolMetaChips([
            { label: "模式", value: formatEditModeLabel(lineRange ? "replace_lines" : "replace_text") },
            { label: "范围", value: lineRange },
            { label: "策略", value: edit.replace_all ? "全部替换" : "" },
          ]);

          return `
            <article class="assistant-part-tool-change-card">
              <div class="assistant-part-tool-change-head">
                <strong>修改 ${index + 1}</strong>
                <span>${escapeHtml(lineRange || "精确片段")}</span>
              </div>
              ${cardMeta}
              <div class="assistant-part-tool-card-list">
                ${renderToolCodeCard(
                  typeof edit.old_text === "string" && edit.old_text.length ? "原片段" : "当前片段",
                  String(oldSnippet || ""),
                  snippetLanguage,
                  {
                    allowEmpty: typeof edit.expected_old_text === "string",
                    emptyLabel: "匹配空内容",
                  },
                )}
                ${renderToolCodeCard("替换为", String(edit.new_text || ""), snippetLanguage, {
                  allowEmpty: Object.prototype.hasOwnProperty.call(edit, "new_text"),
                  emptyLabel: "删除这段内容",
                })}
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;

  return renderToolStructuredBlock(metaMarkup, bodyMarkup);
}

function renderToolArguments(toolCall) {
  const toolName = String(toolCall?.name || "");
  const argumentsValue = toolCall?.arguments || {};

  if (toolName === "sandbox_run_python" && typeof argumentsValue.code === "string") {
    const remainingArguments = { ...argumentsValue };
    delete remainingArguments.code;

    const codeBlock = renderMarkdown(`\`\`\`python\n${argumentsValue.code.replace(/\n$/, "")}\n\`\`\``);
    const extrasBlock = Object.keys(remainingArguments).length
      ? `
          <div class="assistant-part-tool-arguments-extra">
            <div class="assistant-part-section-title">其他参数</div>
            ${renderJsonBlock("参数", remainingArguments)}
          </div>
        `
      : "";

    return `
      <div class="assistant-part-tool-arguments">
        <div class="assistant-part-tool-arguments-code markdown-body">${codeBlock}</div>
        ${extrasBlock}
      </div>
    `;
  }

  if (toolName === "sandbox_write_file") {
    return renderSandboxWriteArguments(argumentsValue);
  }

  if (toolName === "sandbox_edit_file") {
    return renderSandboxSingleEditArguments(argumentsValue);
  }

  if (toolName === "sandbox_multiedit_file") {
    return renderSandboxMultieditArguments(argumentsValue);
  }

  if (typeof argumentsValue.value === "string") {
    return `
      <div class="assistant-part-tool-arguments">
        <div class="assistant-part-tool-arguments-code markdown-body">${renderMarkdown(argumentsValue.value)}</div>
      </div>
    `;
  }

  return renderJsonBlock("参数", argumentsValue);
}

function parseToolResultPayload(toolItem) {
  const resultText = toolResultText(toolItem?.toolResult);
  const parsed = tryParseJsonText(resultText);
  return parsed && typeof parsed === "object" ? parsed : null;
}

function renderSandboxEditResult(toolItem) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload || Array.isArray(payload)) {
    return null;
  }
  if (payload.ok === false && payload.error) {
    return renderToolStructuredBlock("", "", renderToolNote(payload.error, "danger"));
  }

  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: payload.relative_path || payload.path },
    { label: "模式", value: formatEditModeLabel(payload.edit_mode) },
    { label: "状态", value: payload.changed ? "已更新" : "无变化" },
    { label: "影响", value: hasVisibleValue(payload.replaced_count) ? `${payload.replaced_count} 处` : "" },
    { label: "范围", value: formatLineRange(payload.start_line, payload.end_line) },
  ]);
  const bodyMarkup = payload.changed
    ? renderToolCodeCard("变更预览", String(payload.diff || ""), "diff", {
        allowEmpty: true,
        emptyLabel: "没有可展示的差异",
      })
    : `<div class="assistant-part-empty">本次编辑没有改动文件内容。</div>`;
  const noteMarkup = payload.diff_truncated ? renderToolNote("Diff 过长，前端只展示了截断后的预览。", "info") : "";

  return renderToolStructuredBlock(metaMarkup, bodyMarkup, noteMarkup);
}

function renderSandboxWriteResult(toolItem) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload || Array.isArray(payload)) {
    return null;
  }
  if (payload.ok === false && payload.error) {
    return renderToolStructuredBlock("", "", renderToolNote(payload.error, "danger"));
  }

  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: payload.relative_path || payload.path },
    { label: "状态", value: "已写入" },
    { label: "大小", value: hasVisibleValue(payload.size_bytes) ? `${payload.size_bytes} B` : "" },
  ]);
  const bodyMarkup = `<div class="assistant-part-empty assistant-part-empty-compact">文件内容已写入 sandbox 工作区。</div>`;
  const noteMarkup = renderToolNote("这是整文件写入操作，所以不会提供 diff 预览。", "info");
  return renderToolStructuredBlock(metaMarkup, bodyMarkup, noteMarkup);
}

function renderSandboxMultieditResult(toolItem) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload || Array.isArray(payload)) {
    return null;
  }
  if (payload.ok === false && payload.error) {
    return renderToolStructuredBlock("", "", renderToolNote(payload.error, "danger"));
  }

  const edits = Array.isArray(payload.edits) ? payload.edits : [];
  const metaMarkup = renderToolMetaChips([
    { label: "文件", value: payload.relative_path || payload.path },
    { label: "状态", value: payload.changed ? "已更新" : "无变化" },
    { label: "修改数", value: hasVisibleValue(payload.edit_count) ? `${payload.edit_count} 处` : `${edits.length} 处` },
  ]);
  const changesMarkup = edits.length
    ? `
        <div class="assistant-part-tool-change-list">
          ${edits
            .map((edit) => {
              const lineRange = formatLineRange(edit.start_line, edit.end_line);
              return `
                <article class="assistant-part-tool-change-card">
                  <div class="assistant-part-tool-change-head">
                    <strong>修改 ${Number(edit.index) || 0}</strong>
                    <span>${escapeHtml(lineRange || formatEditModeLabel(edit.edit_mode))}</span>
                  </div>
                  ${renderToolMetaChips([
                    { label: "模式", value: formatEditModeLabel(edit.edit_mode) },
                    { label: "范围", value: lineRange },
                    { label: "影响", value: hasVisibleValue(edit.replaced_count) ? `${edit.replaced_count} 处` : "" },
                    { label: "状态", value: edit.changed ? "已应用" : "无变化" },
                  ])}
                </article>
              `;
            })
            .join("")}
        </div>
      `
    : "";
  const diffMarkup = payload.changed
    ? renderToolCodeCard("合并后的变更预览", String(payload.diff || ""), "diff", {
        allowEmpty: true,
        emptyLabel: "没有可展示的差异",
      })
    : `<div class="assistant-part-empty">本次多点编辑没有改动文件内容。</div>`;
  const noteMarkup = payload.diff_truncated ? renderToolNote("Diff 过长，前端只展示了截断后的预览。", "info") : "";

  return renderToolStructuredBlock(metaMarkup, `${changesMarkup}${diffMarkup}`, noteMarkup);
}

function renderToolResult(toolItem) {
  const toolName = String(toolItem?.name || "");
  if (toolName === "sandbox_write_file") {
    const specialized = renderSandboxWriteResult(toolItem);
    if (specialized) {
      return specialized;
    }
  }
  if (toolName === "sandbox_edit_file") {
    const specialized = renderSandboxEditResult(toolItem);
    if (specialized) {
      return specialized;
    }
  }
  if (toolName === "sandbox_multiedit_file") {
    const specialized = renderSandboxMultieditResult(toolItem);
    if (specialized) {
      return specialized;
    }
  }

  const resultText = toolResultText(toolItem?.toolResult);
  return renderCodeBlock(resultText || JSON.stringify(toolItem?.toolResult?.content || [], null, 2), "text", "结果");
}

function renderReasoningBody(part) {
  return getCachedMarkdown(part?.text || "");
}

function renderAssistantPartBodyShell(className, content = "", hidden = false) {
  return `<div class="${className}" data-assistant-part-body${hidden ? " hidden" : ""}>${content}</div>`;
}

function renderAssistantReasoningPart(messageId, part, partKey, defaultOpen) {
  const preview = truncate(part.text, 68) || "思考内容";
  const expanded = isAssistantPartExpanded(partKey, defaultOpen);
  return `
    <details
      class="assistant-part assistant-part-reasoning"
      data-message-id="${escapeHtml(messageId)}"
      data-assistant-part-key="${escapeHtml(partKey)}"
      ${expanded ? 'open data-ignore-toggle="true"' : ""}
    >
      <summary>
        <span class="assistant-part-heading-copy">
          <span class="assistant-part-kicker">思考过程</span>
          <span class="assistant-part-title">${escapeHtml(preview)}</span>
        </span>
      </summary>
      ${renderAssistantPartBodyShell(
        "assistant-part-body markdown-body",
        expanded ? renderReasoningBody(part) : "",
        !expanded,
      )}
    </details>
  `;
}

function renderAssistantToolBody(toolItem) {
  const argumentsBlock = toolItem.toolCall
    ? renderToolArguments(toolItem.toolCall)
    : `<div class="assistant-part-empty">等待调用参数</div>`;
  const resultBlock = toolItem.toolResult
    ? renderToolResult(toolItem)
    : `<div class="assistant-part-empty">等待结果</div>`;

  return `
    <section class="assistant-part-section">
      <div class="assistant-part-section-title">调用参数</div>
      ${argumentsBlock}
    </section>
    <section class="assistant-part-section">
      <div class="assistant-part-section-title">返回结果</div>
      ${resultBlock}
    </section>
  `;
}

function renderAssistantToolPart(messageId, toolItem, message, defaultOpen = false) {
  const icon = toolIconMeta(toolItem.name);
  const statusLabel = toolStatusLabel(toolItem, message);
  const statusClassName = toolStatusClass(toolItem, message);
  const expanded = isAssistantPartExpanded(toolItem.key, defaultOpen);

  return `
    <details
      class="assistant-part assistant-part-tool assistant-part-tool-${escapeHtml(icon.variant)}"
      data-message-id="${escapeHtml(messageId)}"
      data-assistant-part-key="${escapeHtml(toolItem.key)}"
      ${expanded ? 'open data-ignore-toggle="true"' : ""}
    >
      <summary>
        <span class="assistant-part-heading">
          <span class="assistant-part-icon assistant-part-icon-${escapeHtml(icon.variant)}" aria-hidden="true">
            ${icon.svg}
          </span>
          <span class="assistant-part-heading-copy">
            <span class="assistant-part-kicker">${escapeHtml(icon.label)}</span>
            <span class="assistant-part-title">${escapeHtml(toolItem.name || "工具")}</span>
          </span>
        </span>
        <span class="assistant-part-status ${escapeHtml(statusClassName)}">${escapeHtml(statusLabel)}</span>
      </summary>
      ${renderAssistantPartBodyShell(
        "assistant-part-body assistant-part-tool-body",
        expanded ? renderAssistantToolBody(toolItem) : "",
        !expanded,
      )}
    </details>
  `;
}

function renderAssistantTimeline(message) {
  const items = buildAssistantTimelineItems(message);
  if (!items.length) {
    return "";
  }

  const lastReasoningIndex = items.reduce(
    (lastIndex, item, index) => (item.type === "reasoning" ? index : lastIndex),
    -1,
  );

  return `
    <div class="assistant-timeline">
      ${items
        .map((item, index) => {
          if (item.type === "reasoning") {
            return renderAssistantReasoningPart(
              message?.id,
              item.part,
              item.key,
              message?.status === "in_progress" && index === lastReasoningIndex,
            );
          }
          if (item.type === "tool") {
            return renderAssistantToolPart(
              message?.id,
              item,
              message,
              message?.status === "in_progress" && !item.toolResult
            );
          }
          const outputPendingClass =
            message?.status === "in_progress" && index === items.length - 1 ? " is-pending" : "";
          return `
            <section class="assistant-part assistant-part-output" data-assistant-output-key="${escapeHtml(item.key)}">
              <div class="markdown-body${outputPendingClass}">${renderMarkdown(item.part.text || "")}</div>
            </section>
          `;
        })
        .join("")}
    </div>
  `;
}

export function hydrateAssistantPart(details) {
  if (!(details instanceof HTMLDetailsElement) || !details.open) {
    return;
  }

  const body = details.querySelector("[data-assistant-part-body]");
  const messageId = String(details.dataset.messageId || "");
  const partKey = String(details.dataset.assistantPartKey || "");
  if (!body || !messageId || !partKey) {
    return;
  }

  const session = selectedSession();
  const message = session?.messages?.find((item) => String(item.id || "") === messageId);
  if (!message) {
    return;
  }

  const item = buildAssistantTimelineItems(message).find((candidate) => candidate.key === partKey);
  if (!item) {
    return;
  }

  let html = "";
  if (item.type === "reasoning") {
    body.className = "assistant-part-body markdown-body";
    html = renderReasoningBody(item.part);
  } else if (item.type === "tool") {
    body.className = "assistant-part-body assistant-part-tool-body";
    html = renderAssistantToolBody(item);
  } else {
    return;
  }

  if (body.innerHTML === html) {
    body.hidden = false;
    return;
  }

  body.innerHTML = html;
  body.__renderSignature = html;
  body.hidden = false;
}

function createElementFromMarkup(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content.firstElementChild;
}

function renderAssistantOutputPart(item, isPending) {
  return `
    <section class="assistant-part assistant-part-output" data-assistant-output-key="${escapeHtml(item.key)}">
      <div class="markdown-body${isPending ? " is-pending" : ""}">${renderMarkdown(item.part.text || "")}</div>
    </section>
  `;
}

function renderAssistantTimelineItem(message, item, index, lastReasoningIndex, totalItems) {
  if (item.type === "reasoning") {
    return renderAssistantReasoningPart(
      message?.id,
      item.part,
      item.key,
      message?.status === "in_progress" && index === lastReasoningIndex,
    );
  }
  if (item.type === "tool") {
    return renderAssistantToolPart(
      message?.id,
      item,
      message,
      message?.status === "in_progress" && !item.toolResult
    );
  }
  return renderAssistantOutputPart(item, message?.status === "in_progress" && index === totalItems - 1);
}

function updateAssistantOutputPart(node, item, isPending) {
  const body = node.querySelector(".markdown-body");
  if (!body) {
    return;
  }

  const nextClassName = `markdown-body${isPending ? " is-pending" : ""}`;
  if (body.className !== nextClassName) {
    body.className = nextClassName;
  }

  const text = item.part.text || "";
  const nextHtml = getCachedMarkdown(text);

  if (body.__renderSignature === nextHtml) {
    return;
  }
  body.__renderSignature = nextHtml;
  body.innerHTML = nextHtml;
}

function updateReasoningPart(node, item, isOpen) {
  const title = node.querySelector(".assistant-part-title");
  if (title) {
    title.textContent = truncate(item.part.text, 68) || "思考内容";
  }

  if (!(node instanceof HTMLDetailsElement) || !node.open) {
    return;
  }

  const body = node.querySelector("[data-assistant-part-body]");
  if (!body) {
    return;
  }
  const nextHtml = renderReasoningBody(item.part);
  if (body.__renderSignature === nextHtml) {
    body.hidden = false;
    return;
  }
  body.__renderSignature = nextHtml;
  body.className = "assistant-part-body markdown-body";
  body.innerHTML = nextHtml;
  body.hidden = false;
}

function updateToolPart(node, item, message, defaultOpen = false) {
  const title = node.querySelector(".assistant-part-title");
  if (title) {
    title.textContent = String(item.name || "工具");
  }

  const status = node.querySelector(".assistant-part-status");
  if (status) {
    status.textContent = toolStatusLabel(item, message);
    status.className = `assistant-part-status ${toolStatusClass(item, message)}`;
  }

  if (!(node instanceof HTMLDetailsElement)) {
    return;
  }

  const shouldBeOpen = isAssistantPartExpanded(item.key, defaultOpen);
  if (shouldBeOpen && !node.open) {
    node.dataset.ignoreToggle = "true";
    node.open = true;
  } else if (!shouldBeOpen && node.open) {
    node.dataset.ignoreToggle = "true";
    node.open = false;
  }

  const body = node.querySelector("[data-assistant-part-body]");
  if (!body) {
    return;
  }

  if (!node.open) {
    return;
  }

  const nextHtml = renderAssistantToolBody(item);
  if (body.__renderSignature === nextHtml) {
    body.hidden = false;
    return;
  }
  body.__renderSignature = nextHtml;
  body.className = "assistant-part-body assistant-part-tool-body";
  body.innerHTML = nextHtml;
  body.hidden = false;
}

function patchFrozenAssistantMessage(node, message) {
  if (!(node instanceof HTMLElement)) {
    return false;
  }

  const timeline = node.querySelector(".assistant-timeline");
  if (!(timeline instanceof HTMLElement)) {
    return false;
  }

  const items = buildAssistantTimelineItems(message);
  if (!items.length) {
    return false;
  }

  const lastReasoningIndex = items.reduce(
    (lastIndex, item, index) => (item.type === "reasoning" ? index : lastIndex),
    -1,
  );
  const existingByKey = new Map(
    Array.from(timeline.children)
      .filter((child) => child instanceof HTMLElement)
      .map((child) => [child.dataset.assistantPartKey || child.dataset.assistantOutputKey, child]),
  );
  let anchor = timeline.firstElementChild;

  for (const [index, item] of items.entries()) {
    let child = existingByKey.get(item.key);
    if (!child) {
      child = createElementFromMarkup(
        renderAssistantTimelineItem(message, item, index, lastReasoningIndex, items.length),
      );
    } else if (item.type === "output") {
      updateAssistantOutputPart(child, item, message?.status === "in_progress" && index === items.length - 1);
    } else if (item.type === "reasoning") {
      updateReasoningPart(child, item, message?.status === "in_progress" && index === lastReasoningIndex);
    } else if (item.type === "tool") {
      updateToolPart(
        child,
        item,
        message,
        message?.status === "in_progress" && !item.toolResult
      );
    }

    if (child !== anchor) {
      timeline.insertBefore(child, anchor);
    } else {
      anchor = anchor?.nextElementSibling || null;
    }
  }

  while (anchor) {
    const next = anchor.nextElementSibling;
    timeline.removeChild(anchor);
    anchor = next;
  }

  return true;
}

export function setAuthorizationFeedback(message, tone = "muted") {
  const target = byId("authorization-feedback");
  if (!target) {
    return;
  }
  setNodeText(target, message);
  target.dataset.tone = tone;
}

export function fillAuthorizationDraft(draft) {
  setNodeValue(byId("engagement-name"), draft?.name || "");
  setNodeValue(byId("authorization-code"), draft?.authorization || "");
  setNodeValue(byId("start-url"), draft?.start_url || "");
  setNodeValue(
    byId("allowed-hosts"),
    Array.isArray(draft?.allowed_hosts) ? draft.allowed_hosts.join("\n") : "",
  );
  setNodeChecked(byId("allow-subdomains"), draft?.allow_subdomains ?? true);
  setNodeValue(byId("engagement-notes"), draft?.notes || "");
}

export function collectAuthorizationDraft() {
  return {
    name: readNodeValue("engagement-name").trim(),
    authorization: readNodeValue("authorization-code").trim(),
    start_url: readNodeValue("start-url").trim(),
    allowed_hosts: readNodeLines("allowed-hosts"),
    allow_subdomains: byId("allow-subdomains")?.checked ?? true,
    notes: readNodeValue("engagement-notes").trim() || null,
  };
}

export function getDefaultAuthorizationDraft() {
  return state.defaultAuthorizationDraft || bootstrap.defaultAuthorizationDraft || {};
}

export function setSelectedKnowledgeBaseIds(ids) {
  state.selectedKnowledgeBaseIds = normalizeIdList(ids);
}

export function collectSelectedKnowledgeBaseIds() {
  return normalizeIdList(state.selectedKnowledgeBaseIds);
}

function selectedKnowledgeBase() {
  if (!state.selectedKnowledgeBaseId) {
    return null;
  }
  return state.knowledgeBaseDetails.get(state.selectedKnowledgeBaseId) || null;
}

function knowledgeBaseChipMarkup() {
  if (!state.knowledgeBases.length) {
    return `<div class="empty-state compact">No knowledge base yet. Create one in the Knowledge modal.</div>`;
  }
  const selected = new Set(state.selectedKnowledgeBaseIds || []);
  return state.knowledgeBases
    .map((item) => {
      const checked = selected.has(item.id);
      return `
        <label class="knowledge-select-option">
          <input type="checkbox" data-knowledge-selector="${escapeHtml(item.id)}" ${checked ? "checked" : ""} />
          <span class="knowledge-select-copy">
            <strong>${escapeHtml(item.name || item.id)}</strong>
            <em>${Number(item.document_count || 0)} docs</em>
          </span>
        </label>
      `;
    })
    .join("");
}

function knowledgeBaseListMarkup() {
  if (!state.knowledgeBases.length) {
    return `<div class="empty-state compact">Create your first knowledge base.</div>`;
  }
  return state.knowledgeBases
    .map((item) => {
      const active = String(item.id) === String(state.selectedKnowledgeBaseId || "");
      return `
        <button type="button" class="knowledge-item ${active ? "active" : ""}" data-knowledge-base-id="${escapeHtml(item.id)}">
          <span class="knowledge-item-title">${escapeHtml(item.name || item.id)}</span>
          <span class="knowledge-item-meta">${Number(item.document_count || 0)} docs · ${Number(item.chunk_count || 0)} chunks</span>
        </button>
      `;
    })
    .join("");
}

function knowledgeDocumentListMarkup(detail) {
  const documents = Array.isArray(detail?.documents) ? detail.documents : [];
  if (!documents.length) {
    return `<div class="empty-state compact">No documents yet. Add one below.</div>`;
  }
  return documents
    .map(
      (item) => `
        <article class="knowledge-doc-card">
          <div class="knowledge-doc-head">
            <strong>${escapeHtml(item.title || item.id)}</strong>
            <button type="button" class="ghost-button small" data-delete-knowledge-document-id="${escapeHtml(item.id)}">Delete</button>
          </div>
          <div class="knowledge-doc-meta">
            <span>${Number(item.word_count || 0)} words</span>
            <span>${Number(item.chunk_count || 0)} chunks</span>
            <span>${escapeHtml(formatDate(item.updated_at || item.created_at))}</span>
          </div>
          ${
            item.source
              ? `<p class="knowledge-doc-source">${escapeHtml(item.source)}</p>`
              : ""
          }
          <p class="knowledge-doc-preview">${escapeHtml(item.content_preview || "")}</p>
        </article>
      `,
    )
    .join("");
}

function knowledgeDetailMarkup(detail) {
  if (!detail) {
    return `
      <div class="empty-state">
        Select a knowledge base from the left, or create one.
      </div>
    `;
  }

  return `
    <section class="knowledge-detail-head">
      <div>
        <h3>${escapeHtml(detail.name || detail.id)}</h3>
        <p>${escapeHtml(detail.description || "No description.")}</p>
      </div>
      <button type="button" class="ghost-button" data-delete-knowledge-base-id="${escapeHtml(detail.id)}">Delete Base</button>
    </section>
    <section class="knowledge-detail-stats">
      <div class="meta-chip"><span>Documents</span><strong>${Number(detail.document_count || 0)}</strong></div>
      <div class="meta-chip"><span>Chunks</span><strong>${Number(detail.chunk_count || 0)}</strong></div>
      <div class="meta-chip"><span>Updated</span><strong>${escapeHtml(formatDate(detail.updated_at || detail.created_at))}</strong></div>
    </section>
    <section class="knowledge-ingest">
      <h4>Add Document</h4>
      <label class="field">
        <span>Title</span>
        <input id="knowledge-doc-title" type="text" placeholder="Playbook / FAQ / Notes" />
      </label>
      <label class="field">
        <span>Source (optional)</span>
        <input id="knowledge-doc-source" type="text" placeholder="internal wiki / file path / URL" />
      </label>
      <label class="field">
        <span>Text Content</span>
        <textarea id="knowledge-doc-content" rows="6" placeholder="Paste text content here..."></textarea>
      </label>
      <label class="field">
        <span>Or Upload File</span>
        <input id="knowledge-doc-file" type="file" />
      </label>
      <div class="knowledge-ingest-actions">
        <button type="button" class="primary-button" id="save-knowledge-document">Save Document</button>
      </div>
    </section>
    <section class="knowledge-documents">
      <h4>Documents</h4>
      <div class="knowledge-doc-list">${knowledgeDocumentListMarkup(detail)}</div>
    </section>
  `;
}

export function renderKnowledgeLibrary() {
  const selector = byId("knowledge-base-selector");
  if (selector) {
    selector.innerHTML = knowledgeBaseChipMarkup();
  }

  const listRoot = byId("knowledge-base-list");
  if (listRoot) {
    listRoot.innerHTML = knowledgeBaseListMarkup();
  }

  const detailRoot = byId("knowledge-detail");
  if (detailRoot) {
    detailRoot.innerHTML = knowledgeDetailMarkup(selectedKnowledgeBase());
  }
}

export function toggleKnowledgeModal(open) {
  state.knowledgeModalOpen = Boolean(open);
  const modal = byId("knowledge-modal");
  if (modal) {
    modal.hidden = !open;
  }
  document.body.classList.toggle("modal-open", state.settingsOpen || state.knowledgeModalOpen);
}

export function toggleSettings(open) {
  state.settingsOpen = open;
  const settingsModal = byId("settings-modal");
  if (settingsModal) {
    settingsModal.hidden = !open;
  }
  document.body.classList.toggle("modal-open", state.settingsOpen || state.knowledgeModalOpen);
}

export function renderAuthorizations(authorizations) {
  state.authorizations = authorizations;

  const select = byId("authorization-profile");
  if (select) {
    select.innerHTML = ['<option value="">使用当前表单内容</option>']
      .concat(
        authorizations.map(
          (item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`,
        ),
      )
      .join("");
  }

  const root = byId("authorization-library");
  if (!root) {
    return;
  }
  if (!authorizations.length) {
    root.innerHTML = `<div class="empty-state compact">还没有保存的授权配置。</div>`;
    return;
  }

  root.innerHTML = authorizations
    .map(
      (item) => `
        <button type="button" class="authorization-card" data-authorization-id="${escapeHtml(item.id)}">
          <div class="authorization-card-head">
            <strong>${escapeHtml(item.name)}</strong>
            <span>${escapeHtml(item.authorization)}</span>
          </div>
          <p>${escapeHtml(item.start_url)}</p>
        </button>
      `,
    )
    .join("");
}

export function renderSessions() {
  const connection = renderConnectionState();
  const statTotal = byId("stat-total-chats");
  const statRunning = byId("stat-running-chats");
  const connectionState = byId("connection-state");
  const artifactRoot = byId("artifact-root");
  setNodeText(statTotal, String(state.sessions.length));
  setNodeText(statRunning, String(state.sessions.filter((item) => isSessionBusyStatus(item.status)).length));
  setNodeText(connectionState, connection.label);
  if (connectionState) {
    connectionState.className = `mini-pill ${connection.className}`;
  }
  setNodeText(artifactRoot, state.artifactRoot || "artifacts/");

  const root = byId("chat-sessions-list");
  if (!root) {
    return;
  }

  if (!state.sessions.length) {
    root.innerHTML = `<div class="empty-state">还没有会话。发送第一条消息后会自动创建新对话。</div>`;
    return;
  }

  const groups = groupSessionsByDate(state.sessions);
  const existingGroups = new Map();
  Array.from(root.querySelectorAll(".session-group")).forEach((group) => {
    const title = group.querySelector(".session-group-title")?.textContent || "";
    existingGroups.set(title, group);
  });

  const newGroupTitles = new Set(groups.map((g) => g.label));

  existingGroups.forEach((group, title) => {
    if (!newGroupTitles.has(title)) {
      group.remove();
    }
  });

  groups.forEach((group, groupIndex) => {
    let groupEl = existingGroups.get(group.label);
    if (!groupEl) {
      groupEl = document.createElement("section");
      groupEl.className = "session-group";
      groupEl.innerHTML = `<h3 class="session-group-title">${escapeHtml(group.label)}</h3><div class="session-group-items"></div>`;
      if (groupIndex === 0) {
        root.insertBefore(groupEl, root.firstChild);
      } else {
        root.appendChild(groupEl);
      }
    }

    const itemsContainer = groupEl.querySelector(".session-group-items");
    if (!itemsContainer) {
      return;
    }

    const existingItems = new Map();
    Array.from(itemsContainer.querySelectorAll(".session-item")).forEach((item) => {
      const id = item.dataset.sessionId;
      if (id) {
        existingItems.set(id, item);
      }
    });

    const newSessionIds = new Set(group.items.map((s) => s.id));

    existingItems.forEach((item, id) => {
      if (!newSessionIds.has(id)) {
        item.remove();
      }
    });

    group.items.forEach((session, itemIndex) => {
      let itemEl = existingItems.get(String(session.id));
      const isActive = String(session.id) === String(state.selectedSessionId);
      const title = truncate(session.title, 42) || String(session.id);

      if (!itemEl) {
        itemEl = document.createElement("button");
        itemEl.type = "button";
        itemEl.className = "session-item";
        itemEl.dataset.sessionId = String(session.id);
        itemEl.innerHTML = `<span class="session-item-title"></span><span class="session-item-meta"></span>`;
        if (itemIndex === 0) {
          itemsContainer.insertBefore(itemEl, itemsContainer.firstChild);
        } else {
          itemsContainer.appendChild(itemEl);
        }
      }

      const titleEl = itemEl.querySelector(".session-item-title");
      const metaEl = itemEl.querySelector(".session-item-meta");

      if (titleEl && titleEl.textContent !== title) {
        titleEl.textContent = title;
      }

      const expectedMeta = sessionTrailingMarkup(session, isActive);
      if (metaEl && metaEl.innerHTML !== expectedMeta) {
        metaEl.innerHTML = expectedMeta;
      }

      const expectedClass = `session-item ${isActive ? "active" : ""}`.trim();
      if (itemEl.className !== expectedClass) {
        itemEl.className = expectedClass;
      }

      const expectedTitle = session.title || session.id;
      if (itemEl.title !== expectedTitle) {
        itemEl.title = expectedTitle;
      }
    });
  });
}

export function renderSessionMeta(session) {
  const root = byId("session-meta");
  if (!root) {
    return;
  }
  if (!session) {
    root.hidden = true;
    root.innerHTML = "";
    return;
  }

  const runtime = getSessionRuntimeSnapshot(session);
  const connection = renderConnectionState();
  const hasAllowedHosts = Array.isArray(session.allowed_hosts) && session.allowed_hosts.length > 0;

  const messages = Array.isArray(session.messages) ? session.messages : [];
  const compactedCount = messages.filter((msg) => msg.compacted).length;
  const activeCount = messages.filter((msg) => !msg.compacted).length;

  // Build meta items
  const items = [
    { label: "连接", value: connection.label, tone: connection.className },
    { label: "消息数", value: String(activeCount) },
    ...(compactedCount > 0
      ? [{ label: "已压缩", value: String(compactedCount), tone: "status-compacted" }]
      : []),
    ...(session.token_usage ? [
      { label: "Token", value: `${session.token_usage.total_tokens || 0}`, tone: "status-token" },
      ...(session.token_usage.event_count ? [{ label: "API调用", value: String(session.token_usage.event_count) }] : [])
    ] : []),
    // Budget warning
    ...(session.budget_warning ? [
      { label: "预算", value: session.budget_warning, tone: "status-warning" }
    ] : []),
    // Stop reason
    ...(session.stop_reason ? [
      { label: "停止原因", value: session.stop_reason, tone: session.stop_reason === "COMPLETED" ? "status-success" : "status-warning" }
    ] : []),
    ...(hasAllowedHosts
      ? [{ label: "授权范围", value: session.allowed_hosts.join(", ") }]
      : [{ label: "授权范围", value: "无限制", tone: "status-unrestricted" }]),
    ...(Array.isArray(session.knowledge_base_ids) && session.knowledge_base_ids.length
      ? [{ label: "知识库", value: `${session.knowledge_base_ids.length} 个` }]
      : []),
    ...(isSessionCompacting(session) ? [{ label: "记忆", value: "压缩中", tone: "status-compacting" }] : []),
    ...(isSessionBusyStatus(session.status) && runtime.latestToolName
      ? [{ label: "当前工具", value: runtime.latestToolName, tone: statusClass(session.status) }]
      : []),
    ...(!isSessionBusyStatus(session.status) && runtime.latestToolResultName
      ? [{ label: "最近工具", value: runtime.latestToolResultName }]
      : []),
    ...(session.start_url ? [{ label: "起始 URL", value: session.start_url }] : []),
    { label: "最近更新", value: formatDate(runtime.updatedAt || session.updated_at) },
  ];

  root.hidden = false;
  root.innerHTML = items
    .map(
      (item) => `
        <div class="meta-chip${item.tone ? ` ${escapeHtml(item.tone)}` : ""}">
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
        </div>
      `,
    )
    .join("");
}

export function renderHeader() {
  const session = selectedSession();
  const pauseButton = byId("pause-button");
  const distillButton = byId("distill-knowledge-button");
  const statusPill = byId("submit-status");
  const title = byId("chat-title");
  const kicker = byId("chat-kicker");
  const subtitle = byId("chat-subtitle");
  if (!statusPill || !title || !kicker) {
    return;
  }

  if (!session || !state.selectedSessionId) {
    setNodeText(kicker, "新对话");
    setNodeText(title, "开始新的评估对话");
    title.title = "开始新的评估对话";
    if (subtitle) {
      subtitle.hidden = false;
      setNodeText(subtitle, "连接建立后，工具调用和运行状态会在这里实时刷新。");
    }
    if (pauseButton) {
      pauseButton.hidden = true;
      pauseButton.disabled = true;
      pauseButton.textContent = "暂停";
    }
    if (distillButton) {
      distillButton.hidden = true;
      distillButton.disabled = true;
      distillButton.textContent = "沉淀";
      distillButton.setAttribute("aria-label", "沉淀");
      distillButton.setAttribute("title", "沉淀");
    }
    setNodeText(statusPill, state.isSubmitting ? "发送中" : "就绪");
    statusPill.className = `status-pill ${state.isSubmitting ? "status-running" : "status-idle"}`;
    renderSessionMeta(null);
    return;
  }

  const busy = isSessionBusyStatus(session.status);
  const compacting = isSessionCompacting(session);
  const interrupting = session.status === "interrupting";
  setNodeText(kicker, busy ? "进行中会话" : "历史会话");
  setNodeText(title, session.title || session.id);
  title.title = session.title || session.id;
  if (subtitle) {
    subtitle.hidden = true;
    setNodeText(subtitle, "");
  }
  if (pauseButton) {
    pauseButton.hidden = !busy;
    pauseButton.disabled = interrupting;
    pauseButton.textContent = interrupting ? "暂停中" : "暂停";
    pauseButton.setAttribute("aria-label", interrupting ? "正在暂停当前执行" : "暂停当前执行");
    pauseButton.setAttribute("title", interrupting ? "正在暂停当前执行" : "暂停当前执行");
  }
  if (distillButton) {
    const distilling = Boolean(state.isDistillingKnowledge);
    distillButton.hidden = false;
    distillButton.disabled = busy || state.isSubmitting || distilling;
    distillButton.textContent = distilling ? "沉淀中..." : "沉淀";
    distillButton.setAttribute("aria-label", distilling ? "正在沉淀" : "沉淀");
    distillButton.setAttribute("title", distilling ? "正在沉淀" : "沉淀");
  }
  const statusLabel = state.isSubmitting
    ? "发送中"
    : busy
      ? formatStatusText(session.status)
      : compacting
        ? "压缩记忆中"
        : formatStatusText(session.status);
  const statusTone = state.isSubmitting ? "status-running" : compacting && !busy ? "status-compacting" : statusClass(session.status);
  setNodeText(statusPill, statusLabel);
  statusPill.className = `status-pill ${statusTone}`;
  renderSessionMeta(session);
}

function emptyStageMarkup() {
  return `
    <div class="empty-stage">
      <div class="hero-card">
        <div class="hero-layout">
          <div class="hero-main">
            <span class="hero-kicker">开始评估</span>
            <h3>把目标、线索和你想拿到的结果告诉我</h3>
            <p>从第一条消息开始，我会持续推进测试、记录关键结论，并把过程保留在同一条对话里，方便你随时接着做。</p>
            <div class="hero-grid">
              <div>
                <strong>先给出目标</strong>
                <span>URL、题目链接、接口、附件，或你已经抓到的请求包都可以。</span>
              </div>
              <div>
                <strong>补充已知线索</strong>
                <span>账号口令、提示、报错、已有 payload 或 flag 线索，都会让推进更快。</span>
              </div>
              <div>
                <strong>说明想要的结果</strong>
                <span>例如继续打点、验证漏洞、复现利用、拿到 flag，或整理当前结论。</span>
              </div>
            </div>
          </div>
          <aside class="hero-side">
            <div class="hero-side-card">
              <span class="hero-side-kicker">推荐开场</span>
              <strong>可以直接这样发给我</strong>
              <pre class="hero-example">目标：https://target.example/login
已知：普通用户账号、一道题目提示、上一轮的请求包
任务：继续分析登录和会话流程，验证越权或想办法拿到 flag</pre>
            </div>
            <div class="hero-mini-grid">
              <div>
                <strong>过程可见</strong>
                <span>进度、工具结果和脚本变更会持续刷新。</span>
              </div>
              <div>
                <strong>上下文不断</strong>
                <span>关键线索和阶段结论会保留，第二轮也能接着做。</span>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  `;
}

function messageRenderSignature(message) {
  return String(
    message?.render_signature ||
      JSON.stringify([
        String(message?.role || "assistant"),
        String(message?.status || ""),
        String(message?.error || ""),
        message?.content || [],
      ]),
  );
}

function renderMessageMarkup(message) {
  const role = message.role === "user" ? "user" : "assistant";
  const text = messageText(message);
  const isPending = message.status === "in_progress";
  const isFailed = message.status === "failed";
  const isCompacted = Boolean(message.compacted);
  const assistantTimeline = role === "assistant" ? renderAssistantTimeline(message) : "";
  const bubbleText =
    role === "assistant"
      ? text || (isPending ? "正在处理请求…" : isFailed ? "本轮回复失败。" : "本轮没有可展示的文本输出。")
      : text;

  const compactedClass = isCompacted ? "message-compacted" : "";

  return {
    className: `message ${escapeHtml(role)} ${isFailed ? "message-failed" : ""} ${compactedClass}`.trim(),
    markup: `
      <div class="message-label-row">
        <span class="message-label">${role === "user" ? "用户" : "助手"}</span>
        <span class="message-time">${escapeHtml(formatDate(message.updated_at || message.created_at))}</span>
        ${isCompacted ? '<span class="message-compacted-badge" title="此消息已压缩，不会发送给模型">已压缩</span>' : ""}
      </div>
      <div class="message-bubble">
        ${
          role === "assistant"
            ? assistantTimeline || `<div class="markdown-body ${isPending ? "is-pending" : ""}">${renderMarkdown(bubbleText)}</div>`
            : `<div class="markdown-body">${renderMarkdown(bubbleText)}</div>`
        }
        ${message.error ? `<div class="message-error">${escapeHtml(message.error)}</div>` : ""}
      </div>
    `,
  };
}

function syncMessageNode(node, message) {
  const signature = messageRenderSignature(message);
  if (node.__renderSignature === signature) {
    return;
  }

  const view = renderMessageMarkup(message);
  node.dataset.messageId = String(message.id || "");
  node.__renderSignature = signature;
  node.className = view.className;
  node.innerHTML = view.markup;
}

function nowMs() {
  if (typeof window !== "undefined" && window.performance && typeof window.performance.now === "function") {
    return window.performance.now();
  }
  return Date.now();
}

function isChatNearBottom(scrollContainer, threshold = CHAT_AUTOFOLLOW_THRESHOLD_PX) {
  if (!scrollContainer) {
    return true;
  }
  return scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight <= threshold;
}

function setChatAutoFollow(enabled) {
  state.chatAutoFollow = Boolean(enabled);
}

function syncChatScrollSession(scrollContainer, sessionId) {
  const normalizedSessionId = String(sessionId || "");
  if (state.chatScrollSessionId === normalizedSessionId) {
    return;
  }
  state.chatScrollSessionId = normalizedSessionId;
  state.chatAutoFollow = true;
  state.chatProgrammaticScrollUntil = 0;
  state.chatTouchStartY = null;
  state.chatLastScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;
}

function ensureChatScrollTracking(scrollContainer) {
  if (!scrollContainer || scrollContainer.dataset.scrollTrackingBound === "true") {
    return;
  }

  scrollContainer.dataset.scrollTrackingBound = "true";

  scrollContainer.addEventListener(
    "wheel",
    (event) => {
      if (event.deltaY < -1) {
        setChatAutoFollow(false);
      }
    },
    { passive: true },
  );

  scrollContainer.addEventListener(
    "touchstart",
    (event) => {
      const touch = event.touches?.[0];
      state.chatTouchStartY = typeof touch?.clientY === "number" ? touch.clientY : null;
    },
    { passive: true },
  );

  scrollContainer.addEventListener(
    "touchmove",
    (event) => {
      const touch = event.touches?.[0];
      const touchY = typeof touch?.clientY === "number" ? touch.clientY : null;
      const startY = typeof state.chatTouchStartY === "number" ? state.chatTouchStartY : null;
      if (touchY !== null && startY !== null && touchY > startY + CHAT_TOUCH_RELEASE_DELTA_PX) {
        setChatAutoFollow(false);
      }
    },
    { passive: true },
  );

  const resetTouchTracking = () => {
    state.chatTouchStartY = null;
  };
  scrollContainer.addEventListener("touchend", resetTouchTracking, { passive: true });
  scrollContainer.addEventListener("touchcancel", resetTouchTracking, { passive: true });

  scrollContainer.addEventListener(
    "scroll",
    () => {
      if (nowMs() < Number(state.chatProgrammaticScrollUntil || 0)) {
        state.chatLastScrollTop = scrollContainer.scrollTop;
        return;
      }

      if (isChatNearBottom(scrollContainer)) {
        setChatAutoFollow(true);
      } else if (scrollContainer.scrollTop < Number(state.chatLastScrollTop || 0) - 1) {
        setChatAutoFollow(false);
      }

      state.chatLastScrollTop = scrollContainer.scrollTop;
    },
    { passive: true },
  );
}

function shouldStickChatToBottom(scrollContainer, sessionId) {
  if (!scrollContainer) {
    return false;
  }
  ensureChatScrollTracking(scrollContainer);
  syncChatScrollSession(scrollContainer, sessionId);
  return state.chatAutoFollow || isChatNearBottom(scrollContainer, 16);
}

function stickChatToBottom(scrollContainer) {
  if (!scrollContainer) {
    return;
  }
  state.chatProgrammaticScrollUntil = nowMs() + CHAT_PROGRAMMATIC_SCROLL_GUARD_MS;
  scrollContainer.scrollTop = scrollContainer.scrollHeight;
  state.chatLastScrollTop = scrollContainer.scrollTop;
}

export function renderMessages() {
  const root = byId("chat-thread");
  if (!root) {
    return;
  }
  const scrollContainer = root.parentElement;
  const session = selectedSession();
  const shouldStickToBottom = shouldStickChatToBottom(scrollContainer, state.selectedSessionId);
  if (!session || !state.selectedSessionId) {
    syncChatScrollSession(scrollContainer, "");
    root.innerHTML = emptyStageMarkup();
    root.dataset.view = "empty";
    return;
  }

  root.innerHTML = (session.messages || [])
    .map((message) => {
      const role = message.role === "user" ? "user" : "assistant";
      const text = messageText(message);
      const isPending = message.status === "in_progress";
      const isFailed = message.status === "failed";
      const assistantTimeline = role === "assistant" ? renderAssistantTimeline(message) : "";
      const bubbleText =
        role === "assistant"
          ? text || (isPending ? "正在分析请求并调用工具…" : isFailed ? "本轮回复失败。" : "本轮没有可展示的文本输出。")
          : text;

      return `
        <article class="message ${escapeHtml(role)} ${isFailed ? "message-failed" : ""}">
          <div class="message-label-row">
            <span class="message-label">${role === "user" ? "用户" : "助手"}</span>
            <span class="message-time">${escapeHtml(formatDate(message.updated_at || message.created_at))}</span>
          </div>
          <div class="message-bubble">
            ${
              role === "assistant"
                ? assistantTimeline || `<div class="markdown-body ${isPending ? "is-pending" : ""}">${renderMarkdown(bubbleText)}</div>`
                : `<div class="markdown-body">${renderMarkdown(bubbleText)}</div>`
            }
            ${message.error ? `<div class="message-error">${escapeHtml(message.error)}</div>` : ""}
          </div>
        </article>
      `;
    })
    .join("");

  if (scrollContainer && shouldStickToBottom) {
    stickChatToBottom(scrollContainer);
  }
}

function renderCompactedMessagesSection(compactedMessages) {
  if (!compactedMessages || compactedMessages.length === 0) {
    return "";
  }

  const tokenCount = compactedMessages.reduce((sum, msg) => sum + (msg.token_count || 0), 0);
  const turnCount = compactedMessages.filter((msg) => msg.role === "user").length;

  return `
    <section class="compacted-messages-section" data-compacted-section>
      <header class="compacted-messages-header">
        <div class="compacted-messages-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 7V4h16v3M9 20h6M12 4v16"/>
          </svg>
          <span>已压缩的历史消息</span>
        </div>
        <button class="compacted-messages-toggle" type="button" data-compacted-toggle aria-expanded="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
          <span>收起</span>
        </button>
      </header>
      <div class="compaction-stats">
        <span>共 <strong>${compactedMessages.length}</strong> 条消息</span>
        <span><strong>${turnCount}</strong> 轮对话</span>
        <span>约 <strong>${tokenCount}</strong> tokens</span>
        <span class="compaction-hint">（已压缩，不会发送给模型）</span>
      </div>
      <div class="compacted-messages-content" data-compacted-content>
        ${compactedMessages.map((msg) => {
          const view = renderMessageMarkup({ ...msg, compacted: true });
          return `<article class="${view.className}" data-message-id="${msg.id || ""}">${view.markup}</article>`;
        }).join("")}
      </div>
    </section>
  `;
}

function wireCompactedMessagesToggle() {
  document.querySelectorAll("[data-compacted-toggle]").forEach((toggle) => {
    if (toggle.dataset.wired === "true") {
      return;
    }
    toggle.dataset.wired = "true";
    toggle.addEventListener("click", () => {
      const section = toggle.closest("[data-compacted-section]");
      const content = section?.querySelector("[data-compacted-content]");
      const isCollapsed = content?.classList.contains("collapsed");
      if (content) {
        content.classList.toggle("collapsed", !isCollapsed);
      }
      toggle.classList.toggle("collapsed", isCollapsed);
      toggle.setAttribute("aria-expanded", String(isCollapsed));
      const label = toggle.querySelector("span:last-child");
      if (label) {
        label.textContent = isCollapsed ? "收起" : "展开";
      }
    });
  });
}

function renderMessagesFast() {
  const root = byId("chat-thread");
  if (!root) {
    return;
  }

  const scrollContainer = root.parentElement;
  const session = selectedSession();
  const shouldStickToBottom = shouldStickChatToBottom(scrollContainer, state.selectedSessionId);
  if (!session || !state.selectedSessionId) {
    syncChatScrollSession(scrollContainer, "");
    if (root.dataset.view !== "empty") {
      root.innerHTML = emptyStageMarkup();
      root.dataset.view = "empty";
    }
    return;
  }

  const messages = Array.isArray(session.messages) ? session.messages : [];

  // Clear empty/loading stage when we have messages, or show empty stage if no messages
  if (root.dataset.view === "empty" || root.dataset.view === "loading") {
    if (messages.length > 0) {
      root.innerHTML = "";
    } else {
      // Session loaded but empty - show empty stage
      root.innerHTML = emptyStageMarkup();
    }
  }

  root.dataset.view = "messages";

  const compactedMessages = messages.filter((msg) => msg.compacted);
  const activeMessages = messages.filter((msg) => !msg.compacted);

  const existingById = new Map(
    Array.from(root.children)
      .filter((node) => node instanceof HTMLElement && node.dataset.messageId)
      .map((node) => [node.dataset.messageId, node]),
  );

  const existingCompactedSection = Array.from(root.children).find(
    (node) => node.hasAttribute("data-compacted-section")
  );

  if (compactedMessages.length === 0) {
    // If we have an existing section but no compacted messages, let it be removed below
  } else {
    if (existingCompactedSection && existingCompactedSection.dataset.msgCount === String(compactedMessages.length)) {
      // Re-insert at top if not already
    } else {
      const sectionHtml = renderCompactedMessagesSection(compactedMessages);
      const sectionContainer = document.createElement("div");
      sectionContainer.innerHTML = sectionHtml;
      const section = sectionContainer.firstElementChild;
      if (section) {
        section.dataset.msgCount = String(compactedMessages.length);
        if (existingCompactedSection) {
           root.replaceChild(section, existingCompactedSection);
        } else {
           root.insertBefore(section, root.firstChild);
        }
      }
    }
  }

  let anchor = root.querySelector("[data-compacted-section]")?.nextElementSibling || root.firstElementChild;
  if (root.querySelector("[data-compacted-section]") === root.firstElementChild) {
     anchor = root.firstElementChild?.nextElementSibling || null;
  } else if (existingCompactedSection && existingCompactedSection.parentNode === root) {
     root.insertBefore(existingCompactedSection, root.firstElementChild);
     anchor = existingCompactedSection.nextElementSibling;
  }

  for (const message of activeMessages) {
    const messageId = String(message.id || "");
    let node = existingById.get(messageId);
    if (!node) {
      node = document.createElement("article");
      node.dataset.messageId = messageId;
    }
    if (node instanceof HTMLElement && isMessageRenderingFrozen(messageId)) {
      if (!patchFrozenAssistantMessage(node, message)) {
        syncMessageNode(node, message);
      }
    } else {
      syncMessageNode(node, message);
    }

    if (node !== anchor) {
      root.insertBefore(node, anchor);
    } else {
      anchor = anchor?.nextElementSibling || null;
    }
  }

  while (anchor && !anchor.dataset?.compactedSection) {
    const next = anchor.nextElementSibling;
    if (anchor.dataset.messageId) {
      root.removeChild(anchor);
    }
    anchor = next;
  }

  wireCompactedMessagesToggle();

  if (scrollContainer && shouldStickToBottom) {
    stickChatToBottom(scrollContainer);
  }
}

export function renderComposer() {
  const textarea = byId("goal");
  const hint = byId("composer-hint");
  const submitButton = byId("submit-button");
  const submitButtonLabel = byId("submit-button-label");
  const budgetBanner = byId("budget-warning-banner");
  const budgetText = byId("budget-warning-text");
  const session = selectedSession();
  
  if (!textarea || !submitButton) {
    return;
  }
  
  // Render budget warning banner
  if (budgetBanner && budgetText) {
    if (session?.budget_warning) {
      budgetBanner.hidden = false;
      budgetText.textContent = session.budget_warning;
      // Add error class if budget exceeded
      if (session.budget_warning.includes("超出") || session.budget_warning.includes("exceeded")) {
        budgetBanner.classList.add("error");
      } else {
        budgetBanner.classList.remove("error");
      }
    } else {
      budgetBanner.hidden = true;
    }
  }
  
  const busy = state.isSubmitting || isSessionBusyStatus(session?.status);
  const compacting = isSessionCompacting(session);
  const runtime = session ? getSessionRuntimeSnapshot(session) : null;
  const submitLabel = busy ? "处理中" : session && state.selectedSessionId ? "继续对话" : "发送并新建";

  textarea.placeholder = state.defaultGoal || bootstrap.defaultGoal || "";
  textarea.disabled = busy;
  submitButton.disabled = busy;
  submitButton.setAttribute("aria-label", submitLabel);
  submitButton.setAttribute("title", submitLabel);
  setNodeText(submitButtonLabel, submitLabel);

  if (!hint) {
    return;
  }

  if (session && state.selectedSessionId) {
    hint.hidden = false;
    setNodeText(
      hint,
      busy
        ? `${runtimeHeadline(session, runtime)} | ${runtimeDetail(session, runtime)}`
        : compacting
          ? `正在后台压缩记忆，不影响继续输入。新消息会继续追加到「${truncate(session.title || session.id, 28)}」中。`
          : `新消息会追加到「${truncate(session.title || session.id, 28)}」中。${runtime?.latestToolResultName ? ` 最近一次工具返回：${truncate(runtime.latestToolResultName, 24)}。` : ""}`,
    );
    return;
  }

  hint.hidden = false;
  setNodeText(hint, "当前输入会创建新会话，发送后会立即进入流式执行。");
}

export function renderApp() {
  renderSessions();
  renderHeader();
  renderMessagesFast();
  renderComposer();
  renderKnowledgeLibrary();
}
