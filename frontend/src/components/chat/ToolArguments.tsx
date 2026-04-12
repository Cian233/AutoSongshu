// ── ToolArguments ────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderToolArguments(), renderSandboxWriteArguments(),
//   renderSandboxSingleEditArguments(), renderSandboxMultieditArguments(),
//   renderToolCodeCard(), renderJsonBlock(), renderToolMetaChips()
//
// Renders tool call arguments with specialized layouts for different
// tool types (sandbox_write, sandbox_edit, sandbox_multiedit, etc.)

import React, { memo, useMemo } from "react";

// ── Helper: safeStringify ─────────────────────────────────────────

function safeStringify(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  }
  return String(value);
}
import { cn } from "../../lib/cn";
import type { ToolCallPart } from "../../types/session";
import { CodeBlock } from "../markdown/CodeBlock";
import { MarkdownContent } from "../markdown/MarkdownContent";

// ── Helpers ──────────────────────────────────────────────────────

function inferCodeLanguageFromPath(path: string): string {
  const normalized = path.trim().toLowerCase();
  if (!normalized) return "text";
  if (normalized.endsWith(".py")) return "python";
  if (normalized.endsWith(".json")) return "json";
  if (normalized.endsWith(".js") || normalized.endsWith(".mjs") || normalized.endsWith(".cjs"))
    return "javascript";
  if (normalized.endsWith(".ts") || normalized.endsWith(".tsx")) return "typescript";
  if (normalized.endsWith(".html") || normalized.endsWith(".htm")) return "html";
  if (normalized.endsWith(".css")) return "css";
  if (normalized.endsWith(".sh") || normalized.endsWith(".bash")) return "bash";
  return "text";
}

function formatEditModeLabel(mode?: string): string {
  return String(mode || "").toLowerCase() === "replace_lines" ? "按行替换" : "精确替换";
}

function formatLineRange(startLine?: number, endLine?: number): string {
  if (!startLine || !endLine) return "";
  return startLine === endLine ? `第 ${startLine} 行` : `第 ${startLine}-${endLine} 行`;
}

function hasVisibleValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

// ── Sub-components ───────────────────────────────────────────────

interface MetaChipEntry {
  label: string;
  value: unknown;
}

function ToolMetaChips({ entries }: { entries: MetaChipEntry[] }) {
  const visible = entries.filter((e) => hasVisibleValue(e.value));
  if (!visible.length) return null;

  return (
    <div className="assistant-part-tool-meta">
      {visible.map((entry, i) => (
        <span className="assistant-part-tool-meta-chip" key={i}>
          <span>{entry.label}</span>
          <strong>{String(entry.value)}</strong>
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
  subtitle?: string;
}

function ToolCodeCard({
  title,
  content,
  language = "",
  allowEmpty = false,
  emptyLabel = "空内容",
  subtitle,
}: ToolCodeCardProps) {
  const hasContent = content.length > 0;
  if (!hasContent && !allowEmpty) return null;

  return (
    <section className="assistant-part-tool-card">
      <div className="assistant-part-tool-card-head">
        <strong>{title}</strong>
        {subtitle && <span>{subtitle}</span>}
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

interface JsonBlockProps {
  label: string;
  value: unknown;
}

function JsonBlock({ label, value }: JsonBlockProps) {
  const pretty =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <CodeBlock content={pretty} language="json" title={label} />;
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

// ── Specialized renderers ────────────────────────────────────────

interface SandboxWriteProps {
  args: Record<string, unknown>;
}

function SandboxWriteArguments({ args }: SandboxWriteProps) {
  const inferred = inferCodeLanguageFromPath(safeStringify(args.path));
  // Sandbox only supports Python; fall back to "python" when the path
  // hasn't fully arrived yet during streaming (e.g. "/tmp/scrip" → "text").
  const snippetLanguage = inferred !== "text" ? inferred : "python";
  const content = safeStringify(args.content);

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            { label: "文件", value: args.path },
            { label: "方式", value: "整文件写入" },
          ]}
        />
      }
      body={
        <ToolCodeCard
          title="写入内容"
          content={content}
          language={snippetLanguage}
          allowEmpty={Object.prototype.hasOwnProperty.call(args, "content")}
          emptyLabel="写入空文件"
        />
      }
      note={
        <ToolNote
          text="write_file 会直接创建新文件，或覆盖已有文件的全部内容。"
          tone="info"
        />
      }
    />
  );
}

interface SandboxSingleEditProps {
  args: Record<string, unknown>;
}

function SandboxSingleEditArguments({ args }: SandboxSingleEditProps) {
  const inferred = inferCodeLanguageFromPath(safeStringify(args.path));
  const snippetLanguage = inferred !== "text" ? inferred : "python";
  const oldSnippet =
    typeof args.old_text === "string" && args.old_text.length
      ? args.old_text
      : typeof args.expected_old_text === "string"
        ? args.expected_old_text
        : safeStringify(args.old_text ?? args.expected_old_text);
  const oldLabel =
    typeof args.old_text === "string" && args.old_text.length
      ? "原片段"
      : "当前片段";

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            { label: "文件", value: args.path },
            {
              label: "模式",
              value: formatEditModeLabel(
                args.start_line && args.end_line ? "replace_lines" : "replace_text",
              ),
            },
            { label: "范围", value: formatLineRange(args.start_line as number | undefined, args.end_line as number | undefined) },
            { label: "策略", value: args.replace_all ? "全部替换" : "" },
          ]}
        />
      }
      body={
        <div className="assistant-part-tool-card-list">
          <ToolCodeCard
            title={oldLabel}
            content={String(oldSnippet || "")}
            language={snippetLanguage}
            allowEmpty={typeof args.expected_old_text === "string"}
            emptyLabel="匹配空内容"
          />
          <ToolCodeCard
            title="替换为"
            content={safeStringify(args.new_text)}
            language={snippetLanguage}
            allowEmpty={Object.prototype.hasOwnProperty.call(args, "new_text")}
            emptyLabel="删除这段内容"
          />
          {args.max_diff_chars != null &&
            Number(args.max_diff_chars) !== 12000 && (
              <JsonBlock
                label="其他参数"
                value={{ max_diff_chars: args.max_diff_chars }}
              />
            )}
        </div>
      }
    />
  );
}

interface MultieditEntry {
  old_text?: string;
  expected_old_text?: string;
  new_text?: string;
  start_line?: number;
  end_line?: number;
  replace_all?: boolean;
  [key: string]: unknown;
}

interface SandboxMultieditProps {
  args: Record<string, unknown>;
}

function SandboxMultieditArguments({ args }: SandboxMultieditProps) {
  const inferred = inferCodeLanguageFromPath(String(args.path || ""));
  const snippetLanguage = inferred !== "text" ? inferred : "python";

  let edits: MultieditEntry[] = [];
  if (Array.isArray(args.edits)) {
    edits = args.edits.filter(
      (item) => item && typeof item === "object",
    ) as MultieditEntry[];
  } else if (typeof args.edits_json === "string") {
    try {
      const parsed = JSON.parse(args.edits_json);
      if (Array.isArray(parsed)) {
        edits = parsed.filter(
          (item) => item && typeof item === "object",
        ) as MultieditEntry[];
      }
    } catch {
      // ignore parse errors
    }
  }

  if (!edits.length) {
    return <JsonBlock label="参数" value={args} />;
  }

  return (
    <StructuredBlock
      meta={
        <ToolMetaChips
          entries={[
            { label: "文件", value: args.path },
            { label: "修改数", value: `${edits.length} 处` },
          ]}
        />
      }
      body={
        <div className="assistant-part-tool-change-list">
          {edits.map((edit, index) => {
            const oldSnippet =
              typeof edit.old_text === "string" && edit.old_text.length
                ? edit.old_text
                : typeof edit.expected_old_text === "string"
                  ? edit.expected_old_text
                  : "";
            const lineRange = formatLineRange(edit.start_line, edit.end_line);

            return (
              <article
                className="assistant-part-tool-change-card"
                key={index}
              >
                <div className="assistant-part-tool-change-head">
                  <strong>修改 {index + 1}</strong>
                  <span>{lineRange || "精确片段"}</span>
                </div>
                <ToolMetaChips
                  entries={[
                    {
                      label: "模式",
                      value: formatEditModeLabel(
                        lineRange ? "replace_lines" : "replace_text",
                      ),
                    },
                    { label: "范围", value: lineRange },
                    {
                      label: "策略",
                      value: edit.replace_all ? "全部替换" : "",
                    },
                  ]}
                />
                <div className="assistant-part-tool-card-list">
                  <ToolCodeCard
                    title={
                      typeof edit.old_text === "string" && edit.old_text.length
                        ? "原片段"
                        : "当前片段"
                    }
                    content={safeStringify(oldSnippet)}
                    language={snippetLanguage}
                    allowEmpty={typeof edit.expected_old_text === "string"}
                    emptyLabel="匹配空内容"
                  />
                  <ToolCodeCard
                    title="替换为"
                    content={safeStringify(edit.new_text)}
                    language={snippetLanguage}
                    allowEmpty={Object.prototype.hasOwnProperty.call(
                      edit,
                      "new_text",
                    )}
                    emptyLabel="删除这段内容"
                  />
                </div>
              </article>
            );
          })}
        </div>
      }
    />
  );
}

// ── Main Component ───────────────────────────────────────────────

interface ToolArgumentsProps {
  /** The tool call part containing name and arguments. */
  toolCall: ToolCallPart;
}

function ToolArgumentsInner({ toolCall }: ToolArgumentsProps) {
  const toolName = String(toolCall?.name || "");
  const args = (toolCall?.arguments || {}) as Record<string, unknown>;

  const content = useMemo(() => {
    // sandbox_run_python: show code block with extras
    if (toolName === "sandbox_run_python" && typeof args.code === "string") {
      const remainingArgs = { ...args };
      delete remainingArgs.code;

      const hasExtras = Object.keys(remainingArgs).length > 0;

      return (
        <div className="assistant-part-tool-arguments">
          <div className="assistant-part-tool-arguments-code markdown-body">
            <MarkdownContent
              content={`\`\`\`python\n${args.code.replace(/\n$/, "")}\n\`\`\``}
            />
          </div>
          {hasExtras && (
            <div className="assistant-part-tool-arguments-extra">
              <div className="assistant-part-section-title">其他参数</div>
              <JsonBlock label="参数" value={remainingArgs} />
            </div>
          )}
        </div>
      );
    }

    // sandbox_write_file
    if (toolName === "sandbox_write_file") {
      return <SandboxWriteArguments args={args} />;
    }

    // sandbox_edit_file
    if (toolName === "sandbox_edit_file") {
      return <SandboxSingleEditArguments args={args} />;
    }

    // sandbox_multiedit_file
    if (toolName === "sandbox_multiedit_file") {
      return <SandboxMultieditArguments args={args} />;
    }

    // String value argument
    if (typeof args.value === "string") {
      return (
        <div className="assistant-part-tool-arguments">
          <div className="assistant-part-tool-arguments-code markdown-body">
            <MarkdownContent content={args.value} />
          </div>
        </div>
      );
    }

    // Default: JSON block
    return <JsonBlock label="参数" value={args} />;
  }, [toolName, args]);

  return content;
}

export const ToolArguments = memo(ToolArgumentsInner);
