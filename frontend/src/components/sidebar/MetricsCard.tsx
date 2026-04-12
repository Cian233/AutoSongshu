// ── MetricsCard ────────────────────────────────────────────────
// Metrics card showing session statistics, migrated from renderMetricsCard().
// Displays: message count, token count, current tool, scope, progress.

import { useSessionStore } from "../../stores/use-session-store";
import { cn } from "../../lib/cn";
import type { SessionDetail } from "../../types/session";

// ── Helpers ────────────────────────────────────────────────────

function getSessionRuntimeSnapshot(session: SessionDetail) {
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const toolCalls = lastAssistant?.content?.filter(
    (p): p is import("../../types/session").ToolCallPart => p.type === "tool_call",
  ) || [];
  const toolResults = lastAssistant?.content?.filter(
    (p): p is import("../../types/session").ToolResultPart => p.type === "tool_result",
  ) || [];

  return {
    latestToolName: toolCalls[toolCalls.length - 1]?.name || "",
    latestToolResultName: toolResults[toolResults.length - 1]?.name || "",
  };
}

// ── Component ──────────────────────────────────────────────────

interface MetricsCardProps {
  className?: string;
}

export function MetricsCard({ className }: MetricsCardProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);
  const progress = useSessionStore((s) => s.progress);
  const progressSessionId = useSessionStore((s) => s.progressSessionId);

  const session = selectedSessionId ? sessionDetails.get(selectedSessionId) : null;

  if (!session || !selectedSessionId) {
    return null;
  }

  const messages = Array.isArray(session.messages) ? session.messages : [];
  const activeCount = messages.filter((msg) => !msg.compacted).length;
  const totalTokens = session.token_usage ? (session.token_usage.total_tokens || 0) : 0;
  const hasAllowedHosts = Array.isArray(session.allowed_hosts) && session.allowed_hosts.length > 0;
  const scopeText = hasAllowedHosts ? `${session.allowed_hosts!.length} 项` : "无限制";
  const runtime = getSessionRuntimeSnapshot(session);
  const toolText = runtime.latestToolName || runtime.latestToolResultName || "-";
  const showProgress =
    progress && progressSessionId === selectedSessionId && progress.detail;

  return (
    <div
      className={cn(
        "p-3 rounded-[var(--radius-md)]",
        "bg-[var(--panel-strong)] border border-[var(--line)]",
        className,
      )}
    >
      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-2">
        <MetricItem label="消息数" value={String(activeCount)} />
        <MetricItem
          label="Token"
          value={totalTokens > 0 ? `${(totalTokens / 1000).toFixed(1)}k` : "-"}
        />
        <MetricItem label="当前工具" value={toolText} mono />
        <MetricItem label="授权范围" value={scopeText} />
      </div>

      {/* Progress Detail */}
      {showProgress && (
        <div
          className="mt-2 text-[var(--font-size-xs)] text-[var(--muted)] truncate"
          title={progress!.detail}
        >
          {progress!.detail}
        </div>
      )}
    </div>
  );
}

// ── Metric Item ────────────────────────────────────────────────

function MetricItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[var(--font-size-xs)] text-[var(--muted)] font-[var(--font-weight-medium)]">
        {label}
      </span>
      <span
        className={cn(
          "text-[var(--font-size-md)] text-[var(--text)] font-[var(--font-weight-semibold)]",
          mono && "font-[var(--font-mono)] text-[var(--font-size-sm)]",
        )}
      >
        {value}
      </span>
    </div>
  );
}
