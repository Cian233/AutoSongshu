// ── FindingsPanel ───────────────────────────────────────────────
// Security findings panel, migrated from render.js renderFindings().
// Displays a list of findings sorted by severity, each showing
// severity badge, title, and truncated summary.
// Reads findings from useSessionStore.

import { useSessionStore } from "../../stores/use-session-store";
import { PanelSection } from "./PanelSection";
import { cn } from "../../lib/cn";
import type { Finding, FindingSeverity } from "../../types/session";

// ── Severity config ─────────────────────────────────────────────

const SEVERITY_ORDER: Record<FindingSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

const SEVERITY_LABELS: Record<FindingSeverity, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
  info: "信息",
};

const SEVERITY_BADGE_STYLES: Record<FindingSeverity, string> = {
  critical:
    "bg-[var(--danger-soft)] text-[var(--danger)] border-[var(--danger)]/20",
  high:
    "bg-[var(--danger-soft)] text-[var(--danger)] border-[var(--danger)]/15",
  medium:
    "bg-[var(--warning-soft)] text-[var(--warning)] border-[var(--warning)]/15",
  low:
    "bg-[var(--success-soft)] text-[var(--success)] border-[var(--success)]/15",
  info:
    "bg-[var(--bg-soft)] text-[var(--muted)] border-[var(--line)]",
};

const SEVERITY_BORDER_STYLES: Record<FindingSeverity, string> = {
  critical: "border-l-[var(--danger)]",
  high: "border-l-[var(--danger)]",
  medium: "border-l-[var(--warning)]",
  low: "border-l-[var(--success)]",
  info: "border-l-[var(--muted)]",
};

// ── Helpers ─────────────────────────────────────────────────────

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max) + "...";
}

function sortFindings(findings: Finding[]): Finding[] {
  return [...findings].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 5) - (SEVERITY_ORDER[b.severity] ?? 5),
  );
}

// ── Finding Item ────────────────────────────────────────────────

function FindingItem({ finding }: { finding: Finding }) {
  const severity: FindingSeverity = (finding.severity || "info") as FindingSeverity;
  const label = SEVERITY_LABELS[severity] || severity;
  const badgeStyle = SEVERITY_BADGE_STYLES[severity] || SEVERITY_BADGE_STYLES.info;
  const borderStyle = SEVERITY_BORDER_STYLES[severity] || SEVERITY_BORDER_STYLES.info;
  const summary = finding.summary ? truncate(finding.summary, 80) : "";

  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 px-2.5 py-2",
        "rounded-[var(--radius-sm)]",
        "border-l-2",
        borderStyle,
        "transition-colors duration-100",
        "hover:bg-[var(--sidebar-hover)]",
      )}
    >
      {/* Header: badge + title */}
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={cn(
            "flex-shrink-0",
            "inline-flex items-center justify-center",
            "min-w-[40px] h-5 px-1.5",
            "rounded-[var(--radius-sm)] border",
            "text-[var(--font-size-xs)] font-[var(--font-weight-semibold)]",
            badgeStyle,
          )}
        >
          {label}
        </span>
        <span
          className={cn(
            "flex-1 min-w-0 truncate",
            "text-[var(--font-size-sm)] text-[var(--text)] font-[var(--font-weight-medium)]",
          )}
          title={finding.title}
        >
          {finding.title}
        </span>
      </div>

      {/* Summary */}
      {summary && (
        <p
          className={cn(
            "m-0 pl-[52px]",
            "text-[var(--font-size-xs)] text-[var(--muted)]",
            "leading-[var(--line-height-normal)]",
          )}
        >
          {summary}
        </p>
      )}
    </div>
  );
}

// ── Empty State ─────────────────────────────────────────────────

function EmptyState({ icon, title, description }: { icon: string; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <span className="text-2xl">{icon}</span>
      <span className="text-[var(--font-size-sm)] font-[var(--font-weight-medium)] text-[var(--text)]">
        {title}
      </span>
      <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
        {description}
      </span>
    </div>
  );
}

// ── Component ───────────────────────────────────────────────────

interface FindingsPanelProps {
  className?: string;
}

export function FindingsPanel({ className }: FindingsPanelProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const findings = useSessionStore((s) => s.findings);

  const hasSession = Boolean(selectedSessionId);
  const sorted = sortFindings(findings);

  return (
    <PanelSection
      defaultOpen={true}
      className={className}
    >
      <PanelSection.Header title="安全发现" count={findings.length} />
      <PanelSection.Content>
        {!hasSession && (
          <EmptyState
            icon="📋"
            title="选择会话"
            description="切换到左侧会话列表开始"
          />
        )}
        {hasSession && findings.length === 0 && (
          <EmptyState
            icon="🔍"
            title="暂无发现"
            description="安全评估进行中，发现将实时显示"
          />
        )}
        {hasSession && findings.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {sorted.map((finding, idx) => (
              <FindingItem
                key={finding.id || `finding-${idx}`}
                finding={finding}
              />
            ))}
          </div>
        )}
      </PanelSection.Content>
    </PanelSection>
  );
}
