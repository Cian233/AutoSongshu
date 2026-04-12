// ── ToolResult ───────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderToolResult(), renderSandboxEditResult(),
//   renderSandboxWriteResult(), renderSandboxMultieditResult()
//
// Renders tool result content with specialized layouts for different
// tool types.  Shows success/failure status, text results, and
// diff previews for edit operations.

import React, { memo, useMemo } from "react";
import { cn } from "../../lib/cn";
import type { ToolResultPart, ToolCallPart } from "../../types/session";
import { CodeBlock } from "../markdown/CodeBlock";

// ── Helper: safeStringify ─────────────────────────────────────────

function safeStringify(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  }
  return String(value);
}

// ── Helpers ──────────────────────────────────────────────────────

interface ToolTimelineItem {
  type: "tool";
  key: string;
  toolCallId: string;
  name: string;
  toolCall: ToolCallPart | null;
  toolResult: ToolResultPart | null;
}

function toolResultText(part: ToolResultPart | null): string {
  if (!part) return "";
  return (part.content || [])
    .filter(
      (item) =>
        String(item?.type || "").toLowerCase() === "output_text",
    )
    .map((item) => {
      const text = item.text;
      if (typeof text === "string") return text.trim();
      if (text != null && typeof text === "object") {
        try { return JSON.stringify(text, null, 2); } catch { return String(text); }
      }
      return String(text ?? "").trim();
    })
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

function tryParseJsonText(rawText: string): Record<string, unknown> | null {
  const text = rawText.trim();
  if (!text) return null;
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function parseToolResultPayload(
  toolItem: ToolTimelineItem,
): Record<string, unknown> | null {
  const resultText = toolResultText(toolItem?.toolResult);
  const parsed = tryParseJsonText(resultText);
  return parsed && typeof parsed === "object" && !Array.isArray(parsed)
    ? parsed
    : null;
}

function hasVisibleValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function formatEditModeLabel(mode?: string): string {
  return String(mode || "").toLowerCase() === "replace_lines"
    ? "按行替换"
    : "精确替换";
}

function formatLineRange(startLine?: number, endLine?: number): string {
  if (!startLine || !endLine) return "";
  return startLine === endLine
    ? `第 ${startLine} 行`
    : `第 ${startLine}-${endLine} 行`;
}

// ── Sub-components ───────────────────────────────────────────────

interface MetaChipEntry {
  label: string;
  value: unknown;
}

function formatChipValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    try {
      const json = JSON.stringify(value);
      // If the object is a simple dict, show it compactly
      if (json && json.length <= 120) return json;
      // For larger objects, show the type and first few keys
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length <= 3) {
        return entries.map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
      }
      return `{${entries.length} 项}`;
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function ToolMetaChips({ entries }: { entries: MetaChipEntry[] }) {
  const visible = entries.filter((e) => hasVisibleValue(e.value));
  if (!visible.length) return null;

  return (
    <div className="assistant-part-tool-meta">
      {visible.map((entry, i) => (
        <span className="assistant-part-tool-meta-chip" key={i}>
          <span>{entry.label}</span>
          <strong>{formatChipValue(entry.value)}</strong>
        </span>
      ))}
    </div>
  );
}

interface ToolCodeCardProps {
  title: string;
  content: string;
  language?: string;
  allowEmpty?: boolean;
  emptyLabel?: string;
}

function ToolCodeCard({
  title,
  content,
  language = "",
  allowEmpty = false,
  emptyLabel = "空内容",
}: ToolCodeCardProps) {
  const hasContent = content.length > 0;
  if (!hasContent && !allowEmpty) return null;

  return (
    <section className="assistant-part-tool-card">
      <div className="assistant-part-tool-card-head">
        <strong>{title}</strong>
      </div>
      {hasContent ? (
        <CodeBlock content={content} language={language} title={title} />
      ) : (
        <div className="assistant-part-empty assistant-part-empty-compact">
          {emptyLabel}
        </div>
      )}
    </section>
  );
}

interface ToolNoteProps {
  text: string;
  tone?: string;
}

function ToolNote({ text, tone }: ToolNoteProps) {
  if (!text.trim()) return null;
  return (
    <div className={cn("assistant-part-tool-note", tone && `is-${tone}`)}>
      {text}
    </div>
  );
}

interface StructuredBlockProps {
  meta?: React.ReactNode;
  body?: React.ReactNode;
  note?: React.ReactNode;
}

function StructuredBlock({ meta, body, note }: StructuredBlockProps) {
  return (
    <div className="assistant-part-tool-structured">
      {meta}
      {body}
      {note}
    </div>
  );
}

// ── Specialized result renderers ─────────────────────────────────

function SandboxEditResult({ toolItem }: { toolItem: ToolTimelineItem }) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload) return null;

  if (payload.ok === false && payload.error) {
    return (
      <StructuredBlock
        note={<ToolNote text={safeStringify(payload.error)} tone="danger" />}
      />
    );
  }

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            {
              label: "文件",
              value: payload.relative_path || payload.path,
            },
            { label: "模式", value: formatEditModeLabel(String(payload.edit_mode)) },
            {
              label: "状态",
              value: payload.changed ? "已更新" : "无变化",
            },
            {
              label: "影响",
              value: hasVisibleValue(payload.replaced_count)
                ? `${payload.replaced_count} 处`
                : "",
            },
            {
              label: "范围",
              value: formatLineRange(
                payload.start_line as number | undefined,
                payload.end_line as number | undefined,
              ),
            },
          ]}
        />
      }
      body={
        payload.changed ? (
          <ToolCodeCard
            title="变更预览"
            content={safeStringify(payload.diff)}
            language="diff"
            allowEmpty
            emptyLabel="没有可展示的差异"
          />
        ) : (
          <div className="assistant-part-empty">
            本次编辑没有改动文件内容。
          </div>
        )
      }
      note={
        payload.diff_truncated ? (
          <ToolNote
            text="Diff 过长，前端只展示了截断后的预览。"
            tone="info"
          />
        ) : undefined
      }
    />
  );
}

function SandboxWriteResult({ toolItem }: { toolItem: ToolTimelineItem }) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload) return null;

  if (payload.ok === false && payload.error) {
    return (
      <StructuredBlock
        note={<ToolNote text={String(payload.error)} tone="danger" />}
      />
    );
  }

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            {
              label: "文件",
              value: payload.relative_path || payload.path,
            },
            { label: "状态", value: "已写入" },
            {
              label: "大小",
              value: hasVisibleValue(payload.size_bytes)
                ? `${payload.size_bytes} B`
                : "",
            },
          ]}
        />
      }
      body={
        <div className="assistant-part-empty assistant-part-empty-compact">
          文件内容已写入 sandbox 工作区。
        </div>
      }
      note={
        <ToolNote
          text="这是整文件写入操作，所以不会提供 diff 预览。"
          tone="info"
        />
      }
    />
  );
}

function SandboxMultieditResult({
  toolItem,
}: {
  toolItem: ToolTimelineItem;
}) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload) return null;

  if (payload.ok === false && payload.error) {
    return (
      <StructuredBlock
        note={<ToolNote text={String(payload.error)} tone="danger" />}
      />
    );
  }

  const edits = Array.isArray(payload.edits) ? payload.edits : [];

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            {
              label: "文件",
              value: payload.relative_path || payload.path,
            },
            {
              label: "状态",
              value: payload.changed ? "已更新" : "无变化",
            },
            {
              label: "修改数",
              value: hasVisibleValue(payload.edit_count)
                ? `${payload.edit_count} 处`
                : `${edits.length} 处`,
            },
          ]}
        />
      }
      body={
        <>
          {edits.length > 0 && (
            <div className="assistant-part-tool-change-list">
              {edits.map((edit, i) => {
                const editObj = edit as Record<string, unknown>;
                const lineRange = formatLineRange(
                  editObj.start_line as number | undefined,
                  editObj.end_line as number | undefined,
                );

                return (
                  <article
                    className="assistant-part-tool-change-card"
                    key={i}
                  >
                    <div className="assistant-part-tool-change-head">
                      <strong>
                        修改 {Number(editObj.index) || 0}
                      </strong>
                      <span>
                        {lineRange ||
                          formatEditModeLabel(
                            String(editObj.edit_mode),
                          )}
                      </span>
                    </div>
                    <ToolMetaChips
                      entries={[
                        {
                          label: "模式",
                          value: formatEditModeLabel(
                            String(editObj.edit_mode),
                          ),
                        },
                        { label: "范围", value: lineRange },
                        {
                          label: "影响",
                          value: hasVisibleValue(editObj.replaced_count)
                            ? `${editObj.replaced_count} 处`
                            : "",
                        },
                        {
                          label: "状态",
                          value: editObj.changed
                            ? "已应用"
                            : "无变化",
                        },
                      ]}
                    />
                  </article>
                );
              })}
            </div>
          )}
          {payload.changed ? (
            <ToolCodeCard
            title="合并后的变更预览"
            content={safeStringify(payload.diff)}
            language="diff"
            allowEmpty
            emptyLabel="没有可展示的差异"
          />
          ) : (
            <div className="assistant-part-empty">
              本次多点编辑没有改动文件内容。
            </div>
          )}
        </>
      }
      note={
        payload.diff_truncated ? (
          <ToolNote
            text="Diff 过长，前端只展示了截断后的预览。"
            tone="info"
          />
        ) : undefined
      }
    />
  );
}

// ── Lightweight browser tool results ──────────────────────────────
// Tools like browser_navigate, browser_click, browser_fill, etc.
// return minimal payloads (url, status, title, etc.) that don't
// need a full code block.  Show compact meta chips instead.

/**
 * Tools whose results should be rendered as compact meta chips.
 * Uses prefix matching: any tool whose name starts with one of these
 * prefixes is considered lightweight.  Add new prefixes here as needed.
 */
const LIGHTWEIGHT_TOOL_PREFIXES = [
  "browser_",
];

/**
 * Additional lightweight tools that don't match any prefix above.
 * Only use this for exceptions — prefer adding a prefix above.
 */
const EXTRA_LIGHTWEIGHT_TOOLS = new Set<string>([]);

function isLightweightTool(toolName: string): boolean {
  const lower = toolName.toLowerCase();
  return (
    LIGHTWEIGHT_TOOL_PREFIXES.some((p) => lower.startsWith(p)) ||
    EXTRA_LIGHTWEIGHT_TOOLS.has(lower)
  );
}

/**
 * Render a lightweight tool result as compact meta chips.
 * Returns null if the payload looks like an error or is empty.
 */
function LightweightBrowserResult({
  toolItem,
}: {
  toolItem: ToolTimelineItem;
}) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload) return null;

  // If there's an error key, fall through to default rendering
  if (payload.error || payload.ok === false) return null;

  const entries: MetaChipEntry[] = [];

  // Build context-aware chip entries based on tool name
  const toolName = String(toolItem.name || "");

  if (toolName === "browser_navigate") {
    const summary = payload.summary as Record<string, unknown> | null | undefined;
    const metaDesc = summary?.meta_description as string | undefined;
    const textPreview = summary?.text_preview as string | undefined;
    const formsCount = summary?.forms_count as number | undefined;
    const linksCount = summary?.links_count as number | undefined;
    const inputsCount = summary?.inputs_count as number | undefined;

    return (
      <StructuredBlock
        meta={
          <ToolMetaChips
            entries={[
              ...(payload.title ? [{ label: "页面", value: payload.title }] : []),
              ...(payload.status != null ? [{ label: "状态码", value: payload.status }] : []),
              ...(formsCount ? [{ label: "表单", value: `${formsCount} 个` }] : []),
              ...(inputsCount ? [{ label: "输入框", value: `${inputsCount} 个` }] : []),
              ...(linksCount ? [{ label: "链接", value: `${linksCount} 个` }] : []),
            ]}
          />
        }
        body={
          (metaDesc || textPreview) ? (
            <ToolCodeCard
              title="页面摘要"
              content={[metaDesc, textPreview].filter(Boolean).join("\n\n")}
              language="text"
            />
          ) : undefined
        }
      />
    );
  } else if (toolName === "browser_click") {
    if (payload.clicked) entries.push({ label: "点击", value: payload.clicked });
    if (payload.url) entries.push({ label: "URL", value: payload.url });
  } else if (toolName === "browser_fill") {
    if (payload.filled) entries.push({ label: "填写", value: payload.filled });
    if (payload.submitted) entries.push({ label: "已提交", value: "是" });
    if (payload.url) entries.push({ label: "URL", value: payload.url });
  } else if (toolName === "browser_press") {
    if (payload.selector) entries.push({ label: "元素", value: payload.selector });
    if (payload.key) entries.push({ label: "按键", value: payload.key });
    if (payload.url) entries.push({ label: "URL", value: payload.url });
  } else if (toolName === "browser_wait_for_load_state") {
    if (payload.state) entries.push({ label: "状态", value: payload.state });
    if (payload.url) entries.push({ label: "URL", value: payload.url });
  } else if (toolName === "browser_wait_for_selector") {
    if (payload.selector) entries.push({ label: "选择器", value: payload.selector });
    if (payload.state) entries.push({ label: "状态", value: payload.state });
  } else if (toolName === "browser_screenshot") {
    if (payload.name) entries.push({ label: "截图", value: payload.name });
    if (payload.path) entries.push({ label: "路径", value: payload.path });
  } else if (toolName === "browser_hover") {
    if (payload.hovered) entries.push({ label: "悬停", value: payload.hovered });
    if (payload.title) entries.push({ label: "页面", value: payload.title });
  } else if (toolName === "browser_select_option") {
    if (payload.selector) entries.push({ label: "选择框", value: payload.selector });
    if (payload.selected_value) entries.push({ label: "选中值", value: payload.selected_value });
    if (payload.selected_label) entries.push({ label: "选中项", value: payload.selected_label });
    if (payload.title) entries.push({ label: "页面", value: payload.title });
  } else if (toolName === "browser_go_back" || toolName === "browser_go_forward") {
    if (payload.url) entries.push({ label: "URL", value: payload.url });
    if (payload.title) entries.push({ label: "页面", value: payload.title });
  } else if (toolName === "browser_get_element") {
    if (payload.found === false) {
      entries.push({ label: "结果", value: "未找到元素" });
    } else {
      if (payload.tag) entries.push({ label: "标签", value: payload.tag });
      if (payload.is_visible !== undefined) entries.push({ label: "可见", value: payload.is_visible ? "是" : "否" });
      if (payload.text) {
        // Show text preview inline (truncated)
        const text = String(payload.text);
        entries.push({ label: "文本", value: text.length > 80 ? text.slice(0, 80) + "…" : text });
      }
    }
  } else if (toolName === "browser_set_cookies") {
    if (payload.added != null) entries.push({ label: "已设置", value: `${payload.added} 个 cookie` });
  } else if (toolName === "browser_clear_cookies") {
    if (payload.cleared) entries.push({ label: "结果", value: "已清除所有 cookie" });
  } else if (toolName === "browser_upload_file") {
    if (payload.files) entries.push({ label: "文件", value: Array.isArray(payload.files) ? payload.files.join(", ") : String(payload.files) });
    if (payload.title) entries.push({ label: "页面", value: payload.title });
  } else if (toolName === "browser_wait_for_url") {
    if (payload.url) entries.push({ label: "URL", value: payload.url });
    if (payload.title) entries.push({ label: "页面", value: payload.title });
  } else if (toolName === "browser_scroll_to") {
    const pos = payload.scrolled_to as Record<string, unknown> | undefined;
    if (pos) entries.push({ label: "位置", value: `x:${pos.x}, y:${pos.y}` });
    if (payload.selector) entries.push({ label: "元素", value: payload.selector });
  } else if (toolName === "browser_inject_script" || toolName === "browser_add_init_script") {
    if (payload.injected) entries.push({ label: "结果", value: "脚本已注入" });
    if (payload.script_id) entries.push({ label: "脚本 ID", value: String(payload.script_id).substring(0, 30) });
    if (payload.world_name) entries.push({ label: "执行上下文", value: payload.world_name });
    if (payload.method) entries.push({ label: "注入方式", value: payload.method });
  } else if (toolName === "browser_remove_script") {
    if (payload.removed) entries.push({ label: "结果", value: "脚本已移除" });
    if (payload.script_id) entries.push({ label: "脚本 ID", value: String(payload.script_id).substring(0, 30) });
  } else if (toolName === "browser_list_injected_scripts") {
    if (Array.isArray(payload)) {
      entries.push({ label: "已注入脚本", value: `${payload.length} 个` });
    }
  } else if (toolName === "browser_inject_hook") {
    if (payload.injected) entries.push({ label: "结果", value: "Hook 已注入" });
    if (payload.script_id) entries.push({ label: "脚本 ID", value: String(payload.script_id).substring(0, 30) });
  } else {
    // Generic fallback: show all key-value pairs as chips
    for (const [k, v] of Object.entries(payload)) {
      if (v != null && v !== "") entries.push({ label: k, value: v });
    }
  }

  if (entries.length === 0) return null;

  return <ToolMetaChips entries={entries} />;
}

// ── HTTP request result renderer ──────────────────────────────────

function HttpRequestResult({ toolItem }: { toolItem: ToolTimelineItem }) {
  const payload = parseToolResultPayload(toolItem);
  if (!payload) return null;

  if (payload.error || payload.ok === false) {
    return (
      <StructuredBlock
        note={<ToolNote text={safeStringify(payload.error) || "请求失败"} tone="danger" />}
      />
    );
  }

  const statusCode = payload.status_code as number | undefined;
  const url = payload.url as string | undefined;
  const bodyPreview = payload.body_preview as string | undefined;
  const history = payload.history as Array<Record<string, unknown>> | undefined;

  // Build meta chips
  const metaEntries: MetaChipEntry[] = [];
  if (statusCode != null) {
    metaEntries.push({
      label: "状态码",
      value: statusCode,
    });
  }
  if (url) {
    metaEntries.push({
      label: "URL",
      value: url.length > 120 ? url.slice(0, 120) + "…" : url,
    });
  }
  if (history && history.length > 0) {
    metaEntries.push({
      label: "重定向",
      value: `${history.length} 次`,
    });
  }

  // Build body preview — use CodeBlock directly to avoid double-nesting
  let bodyBlock: React.ReactNode = null;
  if (bodyPreview) {
    // Try to detect if the body is JSON
    let language = "text";
    let formattedContent = bodyPreview;
    try {
      const parsed = JSON.parse(bodyPreview);
      formattedContent = JSON.stringify(parsed, null, 2);
      language = "json";
    } catch {
      // Not JSON, keep as-is
    }
    bodyBlock = (
      <CodeBlock
        content={formattedContent}
        language={language}
        title="响应内容"
      />
    );
  }

  return (
    <StructuredBlock
      meta={metaEntries.length > 0 ? <ToolMetaChips entries={metaEntries} /> : undefined}
      body={bodyBlock}
    />
  );
}

// ── Main Component ───────────────────────────────────────────────

interface ToolResultProps {
  /** The tool timeline item containing name, toolCall, and toolResult. */
  toolItem: ToolTimelineItem;
}

function ToolResultInner({ toolItem }: ToolResultProps) {
  const toolName = String(toolItem?.name || "");

  const content = useMemo(() => {
    // Specialized renderers for sandbox tools
    if (toolName === "sandbox_write_file") {
      return <SandboxWriteResult toolItem={toolItem} />;
    }
    if (toolName === "sandbox_edit_file") {
      return <SandboxEditResult toolItem={toolItem} />;
    }
    if (toolName === "sandbox_multiedit_file") {
      return <SandboxMultieditResult toolItem={toolItem} />;
    }

    // HTTP tools: structured rendering with status, headers, body preview
    if (toolName.startsWith("http_") || toolName === "probe_reflection") {
      return <HttpRequestResult toolItem={toolItem} />;
    }

    // Lightweight browser tools: show compact meta chips instead of code block
    if (isLightweightTool(toolName)) {
      const lightweight = <LightweightBrowserResult toolItem={toolItem} />;
      // If the lightweight renderer produced output, use it;
      // otherwise fall through to the default code block (e.g. on error).
      if (lightweight) return lightweight;
    }

    // Default: render result text as a code block
    const resultText = toolResultText(toolItem?.toolResult);
    const fallbackText =
      resultText ||
      JSON.stringify(toolItem?.toolResult?.content || [], null, 2);
    return <CodeBlock content={fallbackText} language="text" title="结果" />;
  }, [toolName, toolItem]);

  return content;
}

export { ToolResultInner as ToolResultDisplay };
export type { ToolTimelineItem };
export { toolResultText, parseToolResultPayload };
export default memo(ToolResultInner);
