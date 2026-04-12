// ── ChatHeader ──────────────────────────────────────────────────
// Chat header in the right sidebar, migrated from renderHeader().
// Displays session title, status, and action buttons.

import { Pause, BookOpen, Download, RefreshCw } from "lucide-react";
import { useSessionStore } from "../../stores/use-session-store";
import {
  isSessionBusyStatus,
  isSessionCompacting,
  formatStatusText,
  statusClass,
  formatDate,
} from "../../lib/utils";
import { cn } from "../../lib/cn";
import type { SessionDetail, SessionRuntimeSnapshot } from "../../types/session";

// ── Helpers ────────────────────────────────────────────────────

/** Derive a lightweight runtime snapshot from session detail */
function getSessionRuntimeSnapshot(
  session: SessionDetail,
): SessionRuntimeSnapshot {
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const toolCalls = lastAssistant?.content?.filter(
    (p): p is import("../../types/session").ToolCallPart => p.type === "tool_call",
  ) || [];
  const toolResults = lastAssistant?.content?.filter(
    (p): p is import("../../types/session").ToolResultPart => p.type === "tool_result",
  ) || [];

  return {
    assistantStatus: lastAssistant?.status || "",
    latestOutputText: "",
    latestToolName: toolCalls[toolCalls.length - 1]?.name || "",
    latestToolResultName: toolResults[toolResults.length - 1]?.name || "",
    pendingToolNames: [],
    pendingToolCount: 0,
    completedToolCount: toolResults.length,
    reasoningCount: lastAssistant?.content?.filter(
      (p) => p.type === "reasoning",
    ).length || 0,
    updatedAt: session.updated_at || "",
  };
}

// ── Component ──────────────────────────────────────────────────

interface ChatHeaderProps {
  /** Callback for pause button */
  onPause?: () => void;
  /** Callback for distill knowledge button */
  onDistill?: () => void;
  /** Callback for export button */
  onExport?: () => void;
  /** Callback for refresh button */
  onRefresh?: () => void;
  className?: string;
}

export function ChatHeader({
  onPause,
  onDistill,
  onExport,
  onRefresh,
  className,
}: ChatHeaderProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);
  const isSubmitting = useSessionStore((s) => s.isSubmitting);
  const session = selectedSessionId ? sessionDetails.get(selectedSessionId) : null;

  // ── No session selected ──
  if (!session || !selectedSessionId) {
    return (
      <header className={cn("w-full flex flex-col items-stretch gap-5", className)}>
        {/* Heading */}
        <div className="min-w-0 flex flex-col items-start gap-2">
          <span className="text-[var(--font-size-xs)] font-[var(--font-weight-semibold)] text-[var(--muted)] uppercase tracking-wider">
            新对话
          </span>
          <h2 className="m-0 text-[var(--text)] text-[var(--font-size-lg)] font-[var(--font-weight-bold)] leading-[var(--line-height-tight)] tracking-[-0.01em]">
            开始新的评估对话
          </h2>
          <p className="text-[var(--font-size-sm)] text-[var(--muted)] m-0">
            连接建立后，工具调用和运行状态会在这里实时刷新。
          </p>
        </div>

        {/* Actions */}
        <div className="grid grid-cols-2 gap-2.5">
          <span
            className={cn(
              "col-span-2 flex items-center justify-center min-h-[34px] px-3 py-1.5 rounded-full",
              "text-[var(--font-size-xs)] font-[var(--font-weight-semibold)]",
              isSubmitting
                ? "bg-[var(--success-soft)] text-[var(--success)]"
                : "bg-[var(--bg-soft)] text-[var(--muted)]",
            )}
          >
            {isSubmitting ? "发送中" : "就绪"}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            className={cn(
              "flex items-center justify-center gap-1.5 w-full min-h-[34px] px-3 py-1.5",
              "rounded-lg text-[var(--font-size-sm)] font-[var(--font-weight-medium)]",
              "bg-transparent text-[var(--text)] border border-[var(--line)]",
              "hover:bg-[var(--bg-soft)] transition-colors duration-150",
              "cursor-pointer",
            )}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            刷新
          </button>
        </div>
      </header>
    );
  }

  // ── Session selected ──
  const busy = isSessionBusyStatus(session.status);
  const compacting = isSessionCompacting(session);
  const interrupting = session.status === "interrupting";
  const runtime = getSessionRuntimeSnapshot(session);

  const statusLabel = isSubmitting
    ? "发送中"
    : busy
      ? formatStatusText(session.status)
      : compacting
        ? "压缩记忆中"
        : formatStatusText(session.status);

  const statusTone = isSubmitting
    ? "status-running"
    : compacting && !busy
      ? "status-compacting"
      : statusClass(session.status);

  return (
    <header className={cn("w-full flex flex-col items-stretch gap-5", className)}>
      {/* Heading */}
      <div className="min-w-0 flex flex-col items-start gap-2">
        <span className="text-[var(--font-size-xs)] font-[var(--font-weight-semibold)] text-[var(--muted)] uppercase tracking-wider">
          {busy ? "进行中会话" : "历史会话"}
        </span>
        <h2
          className="m-0 text-[var(--text)] text-[var(--font-size-lg)] font-[var(--font-weight-bold)] leading-[var(--line-height-tight)] tracking-[-0.01em]"
          title={session.title || session.id}
        >
          {session.title || session.id}
        </h2>
      </div>

      {/* Actions */}
      <div className="grid grid-cols-2 gap-2.5">
        {/* Status Pill */}
        <span
          className={cn(
            "col-span-2 flex items-center justify-center min-h-[34px] px-3 py-1.5 rounded-full mb-2",
            "text-[var(--font-size-xs)] font-[var(--font-weight-semibold)]",
            statusTone === "status-running" && "bg-[var(--success-soft)] text-[var(--success)]",
            statusTone === "status-error" && "bg-[var(--danger-soft)] text-[var(--danger)]",
            statusTone === "status-compacting" && "bg-[var(--warning-soft)] text-[var(--warning)]",
            statusTone === "status-idle" && "bg-[var(--bg-soft)] text-[var(--muted)]",
          )}
        >
          {statusLabel}
        </span>

        {/* Pause Button */}
        {busy && (
          <button
            type="button"
            onClick={onPause}
            disabled={interrupting}
            className={cn(
              "flex items-center justify-center gap-1.5 w-full min-h-[34px] px-3 py-1.5",
              "rounded-lg text-[var(--font-size-sm)] font-[var(--font-weight-medium)]",
              "bg-transparent text-[var(--text)] border border-[var(--line)]",
              "hover:bg-[var(--bg-soft)] transition-colors duration-150",
              "cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed",
            )}
          >
            <Pause className="w-3.5 h-3.5" />
            {interrupting ? "暂停中" : "暂停"}
          </button>
        )}

        {/* Distill Knowledge Button */}
        <button
          type="button"
          onClick={onDistill}
          disabled={busy || isSubmitting}
          className={cn(
            "flex items-center justify-center gap-1.5 w-full min-h-[34px] px-3 py-1.5",
            "rounded-lg text-[var(--font-size-sm)] font-[var(--font-weight-medium)]",
            "bg-transparent text-[var(--text)] border border-[var(--line)]",
            "hover:bg-[var(--bg-soft)] transition-colors duration-150",
            "cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <BookOpen className="w-3.5 h-3.5" />
          沉淀
        </button>

        {/* Export Button */}
        <button
          type="button"
          onClick={onExport}
          className={cn(
            "flex items-center justify-center gap-1.5 w-full min-h-[34px] px-3 py-1.5",
            "rounded-lg text-[var(--font-size-sm)] font-[var(--font-weight-medium)]",
            "bg-transparent text-[var(--text)] border border-[var(--line)]",
            "hover:bg-[var(--bg-soft)] transition-colors duration-150",
            "cursor-pointer",
          )}
        >
          <Download className="w-3.5 h-3.5" />
          导出
        </button>

        {/* Refresh Button */}
        <button
          type="button"
          onClick={onRefresh}
          className={cn(
            "flex items-center justify-center gap-1.5 w-full min-h-[34px] px-3 py-1.5",
            "rounded-lg text-[var(--font-size-sm)] font-[var(--font-weight-medium)]",
            "bg-transparent text-[var(--text)] border border-[var(--line)]",
            "hover:bg-[var(--bg-soft)] transition-colors duration-150",
            "cursor-pointer",
          )}
        >
          <RefreshCw className="w-3.5 h-3.5" />
          刷新
        </button>
      </div>

      {/* Session Meta Chips */}
      <SessionMetaChips session={session} runtime={runtime} />
    </header>
  );
}

// ── Session Meta Chips ─────────────────────────────────────────

function SessionMetaChips({
  session,
  runtime,
}: {
  session: SessionDetail;
  runtime: SessionRuntimeSnapshot;
}) {
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const compactedCount = messages.filter((msg) => msg.compacted).length;
  const activeCount = messages.filter((msg) => !msg.compacted).length;
  const hasAllowedHosts = Array.isArray(session.allowed_hosts) && session.allowed_hosts.length > 0;
  const busy = isSessionBusyStatus(session.status);

  const chips: Array<{ label: string; value: string; tone?: string }> = [
    { label: "消息数", value: String(activeCount) },
    ...(compactedCount > 0
      ? [{ label: "已压缩", value: String(compactedCount), tone: "status-compacted" }]
      : []),
    ...(session.token_usage
      ? [
          {
            label: "Token",
            value: `${session.token_usage.total_tokens || 0}`,
            tone: "status-token",
          },
          ...(session.token_usage.event_count
            ? [{ label: "API调用", value: String(session.token_usage.event_count) }]
            : []),
        ]
      : []),
    ...(hasAllowedHosts
      ? [{ label: "授权范围", value: session.allowed_hosts!.join(", ") }]
      : [{ label: "授权范围", value: "无限制", tone: "status-unrestricted" }]),
    ...(Array.isArray(session.knowledge_base_ids) && session.knowledge_base_ids.length
      ? [{ label: "知识库", value: `${session.knowledge_base_ids.length} 个` }]
      : []),
    ...(isSessionCompacting(session)
      ? [{ label: "记忆", value: "压缩中", tone: "status-compacting" }]
      : []),
    ...(busy && runtime.latestToolName
      ? [{ label: "当前工具", value: runtime.latestToolName, tone: statusClass(session.status) }]
      : []),
    ...(!busy && runtime.latestToolResultName
      ? [{ label: "最近工具", value: runtime.latestToolResultName }]
      : []),
    ...(session.start_url
      ? [{ label: "起始 URL", value: session.start_url }]
      : []),
    { label: "最近更新", value: formatDate(runtime.updatedAt || session.updated_at) },
  ];

  return (
    <div className="flex flex-col gap-2.5 mt-3">
      {chips.map((chip) => (
        <div
          key={chip.label}
          className={cn(
            "inline-flex items-center justify-between gap-1.5",
            "min-h-[36px] max-w-full px-3.5 py-1.5",
            "rounded-[12px] bg-[var(--bg-soft)]",
          )}
        >
          <span className="text-[var(--font-size-xs)] text-[var(--muted)] font-[var(--font-weight-medium)]">
            {chip.label}
          </span>
          <strong className="text-[var(--font-size-xs)] text-[var(--text)] font-[var(--font-weight-semibold)]">
            {chip.value}
          </strong>
        </div>
      ))}
    </div>
  );
}
