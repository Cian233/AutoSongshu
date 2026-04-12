// ── TokenUsageBar ──────────────────────────────────────────────
// Token usage progress bar, migrated from updateTokenUsageBar().
// Displays: progress bar with percentage, estimated cost, cache hit rate.

import { useSessionStore } from "../../stores/use-session-store";
import { cn } from "../../lib/cn";

// ── Component ──────────────────────────────────────────────────

interface TokenUsageBarProps {
  className?: string;
}

export function TokenUsageBar({ className }: TokenUsageBarProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);

  const session = selectedSessionId ? sessionDetails.get(selectedSessionId) : null;

  if (!session || !session.token_usage) {
    return null;
  }

  const usage = session.token_usage;
  const total = usage.budget || 128000;
  const used = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  const ratio = Math.min(used / total, 1);
  const pct = Math.round(ratio * 100);

  const level = ratio < 0.6 ? "low" : ratio < 0.85 ? "medium" : "high";

  const barColor =
    level === "low"
      ? "bg-[var(--success)]"
      : level === "medium"
        ? "bg-[var(--warning)]"
        : "bg-[var(--danger)]";

  const hasCost = usage.estimated_cost_usd !== undefined && usage.estimated_cost_usd !== null;
  const hasCache =
    usage.cache_hit_ratio !== undefined && usage.cache_hit_ratio !== null;

  return (
    <div className={cn("mt-2 p-3", className)}>
      {/* Label Row */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
          Token 用量
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
            {(used / 1000).toFixed(1)}k / {(total / 1000).toFixed(0)}k
          </span>

          {/* Estimated Cost */}
          {hasCost && (
            <span
              className={cn(
                "text-[var(--font-size-xs)] font-[var(--font-weight-semibold)]",
                "text-[var(--text-secondary)] bg-[var(--bg-soft)]",
                "px-1.5 py-px rounded-[var(--radius-sm)] whitespace-nowrap",
              )}
            >
              ${Number(usage.estimated_cost_usd).toFixed(2)}
            </span>
          )}

          {/* Cache Hit Rate */}
          {hasCache && (
            <span
              className={cn(
                "text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
                "text-[var(--success)]",
                "px-1.5 py-px rounded-[var(--radius-sm)] whitespace-nowrap",
              )}
              style={{
                background: "color-mix(in srgb, var(--success) 12%, transparent)",
              }}
            >
              Cache: {Math.round(Number(usage.cache_hit_ratio) * 100)}%
            </span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-1 bg-[var(--bg-soft)] rounded-sm overflow-hidden">
        <div
          className={cn(
            "h-full rounded-sm transition-[width,background] duration-300",
            barColor,
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
