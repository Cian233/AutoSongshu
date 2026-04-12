// ── ToolPart ─────────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderAssistantToolPart(), toolIconMeta(), toolStatusLabel(),
//   toolStatusClass()
//
// Renders a collapsible tool call panel using the compound component
// pattern.  The panel shows an icon, tool name, and status badge in
// the header, and the tool arguments + result in the body.
//
// Compound components:
//   ToolPart.Header  - icon + tool name + status
//   ToolPart.Body    - arguments section + result section

import React, { memo, useState, useMemo } from "react";
import { cn } from "../../lib/cn";
import type {
  Message,
} from "../../types/session";
import { ToolArguments } from "./ToolArguments";
import { ToolResultDisplay, type ToolTimelineItem } from "./ToolResult";

// ── Tool icon metadata ───────────────────────────────────────────

interface ToolIconMeta {
  variant: string;
  label: string;
  svg: React.ReactNode;
}

function toolIconMeta(name: string): ToolIconMeta {
  const normalized = String(name || "tool").toLowerCase();

  if (normalized.startsWith("browser_")) {
    return {
      variant: "browser",
      label: "浏览器",
      svg: (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect
            x="3.5" y="5" width="17" height="14" rx="3"
            stroke="currentColor" strokeWidth="1.8"
          />
          <path d="M3.5 9H20.5" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="6.5" cy="7" r="1" fill="currentColor" />
          <circle cx="9.5" cy="7" r="1" fill="currentColor" />
        </svg>
      ),
    };
  }

  if (
    normalized.startsWith("sandbox_") ||
    normalized.includes("python") ||
    normalized.includes("shell")
  ) {
    return {
      variant: "sandbox",
      label: "沙箱",
      svg: (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect
            x="3.5" y="4" width="17" height="16" rx="3"
            stroke="currentColor" strokeWidth="1.8"
          />
          <path
            d="M7 9L10 12L7 15"
            stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round"
          />
          <path
            d="M12.5 15H17"
            stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ),
    };
  }

  if (
    normalized.startsWith("http_") ||
    normalized.includes("request") ||
    normalized.includes("fetch") ||
    normalized.includes("curl")
  ) {
    return {
      variant: "network",
      label: "网络",
      svg: (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8" />
          <path d="M4.5 12H19.5" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 4.5C14.5 7 15.8 9.5 15.8 12C15.8 14.5 14.5 17 12 19.5C9.5 17 8.2 14.5 8.2 12C8.2 9.5 9.5 7 12 4.5Z"
            stroke="currentColor" strokeWidth="1.8"
          />
        </svg>
      ),
    };
  }

  if (
    normalized.includes("file") ||
    normalized.includes("artifact") ||
    normalized.startsWith("fs_") ||
    normalized.includes("read") ||
    normalized.includes("write")
  ) {
    return {
      variant: "file",
      label: "文件",
      svg: (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M7 4.5H13L17.5 9V18.5C17.5 19.0523 17.0523 19.5 16.5 19.5H7.5C6.94772 19.5 6.5 19.0523 6.5 18.5V5.5C6.5 4.94772 6.94772 4.5 7.5 4.5Z"
            stroke="currentColor" strokeWidth="1.8"
          />
          <path
            d="M13 4.5V9H17.5"
            stroke="currentColor" strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      ),
    };
  }

  if (
    normalized.includes("search") ||
    normalized.includes("scan") ||
    normalized.includes("find")
  ) {
    return {
      variant: "search",
      label: "搜索",
      svg: (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="5.5" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M15.5 15.5L19 19"
            stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ),
    };
  }

  return {
    variant: "default",
    label: "工具",
    svg: (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M14.5 6.5A4 4 0 0 0 9 11L5 15V19H9L13 15A4 4 0 0 0 17.5 9.5L14 13L11 10L14.5 6.5Z"
          stroke="currentColor" strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    ),
  };
}

// ── Status helpers ───────────────────────────────────────────────

function toolStatusLabel(
  toolItem: ToolTimelineItem,
  message?: Message,
): string {
  if (toolItem.toolResult) {
    if ((toolItem.toolResult as unknown as Record<string, unknown>).error) {
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

function toolStatusClass(
  toolItem: ToolTimelineItem,
  message?: Message,
): string {
  if (toolItem.toolResult) {
    if ((toolItem.toolResult as unknown as Record<string, unknown>).error) {
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

// ── Compound sub-components ──────────────────────────────────────

interface ToolPartHeaderProps {
  icon: ToolIconMeta;
  toolName: string;
  statusLabel: string;
  statusClassName: string;
}

function ToolPartHeader({
  icon,
  toolName,
  statusLabel,
  statusClassName,
}: ToolPartHeaderProps) {
  return (
    <summary>
      <span className="assistant-part-heading">
        <span
          className={cn(
            "assistant-part-icon",
            `assistant-part-icon-${icon.variant}`,
          )}
          aria-hidden="true"
        >
          {icon.svg}
        </span>
        <span className="assistant-part-heading-copy">
          <span className="assistant-part-kicker">{icon.label}</span>
          <span className="assistant-part-title">
            {toolName || "工具"}
          </span>
        </span>
      </span>
      <span
        className={cn("assistant-part-status", statusClassName)}
      >
        {statusLabel}
      </span>
    </summary>
  );
}

interface ToolPartBodyProps {
  toolItem: ToolTimelineItem;
}

function ToolPartBody({ toolItem }: ToolPartBodyProps) {
  return (
    <div
      className="assistant-part-body assistant-part-tool-body"
      data-assistant-part-body
    >
      <section className="assistant-part-section">
        <div className="assistant-part-section-title">调用参数</div>
        {toolItem.toolCall ? (
          <ToolArguments toolCall={toolItem.toolCall} />
        ) : (
          <div className="assistant-part-empty">等待调用参数</div>
        )}
      </section>
      <section className="assistant-part-section">
        <div className="assistant-part-section-title">返回结果</div>
        {toolItem.toolResult ? (
          <ToolResultDisplay toolItem={toolItem} />
        ) : (
          <div className="assistant-part-empty">工具结果尚未返回</div>
        )}
      </section>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────

interface ToolPartProps {
  /** The tool timeline item. */
  toolItem: ToolTimelineItem;
  /** The parent message (for status detection). */
  message?: Message;
  /** Whether this part should be open by default. */
  defaultOpen?: boolean;
}

function ToolPartInner({
  toolItem,
  message,
  defaultOpen = false,
}: ToolPartProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const icon = useMemo(() => toolIconMeta(toolItem.name), [toolItem.name]);
  const statusLabel = useMemo(
    () => toolStatusLabel(toolItem, message),
    [toolItem, message],
  );
  const statusClassName = useMemo(
    () => toolStatusClass(toolItem, message),
    [toolItem, message],
  );

  // Sync open state when tool result arrives
  const shouldAutoOpen = defaultOpen || (message?.status === "in_progress" && !toolItem.toolResult);
  React.useEffect(() => {
    if (shouldAutoOpen && !isOpen) {
      setIsOpen(true);
    }
  }, [shouldAutoOpen]);

  return (
    <details
      className={cn(
        "assistant-part",
        "assistant-part-tool",
        `assistant-part-tool-${icon.variant}`,
      )}
      data-assistant-part-key={toolItem.key}
      open={isOpen}
      onToggle={(e) => {
        setIsOpen(e.currentTarget.open);
      }}
    >
      <ToolPartHeader
        icon={icon}
        toolName={toolItem.name}
        statusLabel={statusLabel}
        statusClassName={statusClassName}
      />
      {isOpen && <ToolPartBody toolItem={toolItem} />}
    </details>
  );
}

// Attach compound components
export const ToolPart = Object.assign(memo(ToolPartInner), {
  Header: memo(ToolPartHeader),
  Body: memo(ToolPartBody),
});
