// ── StepsPanel ──────────────────────────────────────────────────
// Execution steps panel, migrated from render.js renderSteps().
// Displays a list of agent steps with tool name, status icon, duration,
// token usage, and observation summary.
// Reads steps from useSessionStore.

import { Check, X, Loader2, Circle, Ban } from "lucide-react";
import { useSessionStore } from "../../stores/use-session-store";
import { PanelSection } from "./PanelSection";
import { cn } from "../../lib/cn";
import type { Step, StepState } from "../../types/session";

// ── State icon mapping ──────────────────────────────────────────

const STEP_STATE_ICONS: Record<StepState, typeof Check> = {
  succeeded: Check,
  failed: X,
  running: Loader2,
  pending: Circle,
  skipped: Ban,
};

const STEP_STATE_COLORS: Record<StepState, string> = {
  succeeded: "text-[var(--success)]",
  failed: "text-[var(--danger)]",
  running: "text-[var(--accent)]",
  pending: "text-[var(--muted)]",
  skipped: "text-[var(--muted)]",
};

// ── Helpers ─────────────────────────────────────────────────────

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max) + "...";
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Step Item ───────────────────────────────────────────────────

function StepItem({ step, index }: { step: Step; index: number }) {
  const state: StepState = (step.state || "succeeded") as StepState;
  const Icon = STEP_STATE_ICONS[state] || Circle;
  const colorClass = STEP_STATE_COLORS[state] || "text-[var(--muted)]";
  const toolName = step.tool_name || step.action || "unknown";
  const observation = step.observation ? truncate(step.observation, 60) : "";
  const duration = step.duration_ms ? formatDuration(step.duration_ms) : "";
  const tokens = step.token_usage
    ? ((step.token_usage.input_tokens || 0) + (step.token_usage.output_tokens || 0))
    : 0;

  return (
    <div
      className={cn(
        "flex flex-col gap-1 px-2.5 py-2",
        "rounded-[var(--radius-sm)]",
        "transition-colors duration-100",
        "hover:bg-[var(--sidebar-hover)]",
      )}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 min-w-0">
        {/* Index */}
        <span className="flex-shrink-0 w-5 text-center text-[var(--font-size-xs)] text-[var(--muted)] font-[var(--font-mono)]">
          {index + 1}
        </span>

        {/* State icon */}
        <span className={cn("flex-shrink-0", colorClass)}>
          <Icon
            className={cn(
              "w-3.5 h-3.5",
              state === "running" && "animate-spin",
            )}
          />
        </span>

        {/* Tool name */}
        <span
          className={cn(
            "flex-1 min-w-0 truncate",
            "text-[var(--font-size-sm)] text-[var(--text)] font-[var(--font-weight-medium)]",
            "font-[var(--font-mono)]",
          )}
          title={toolName}
        >
          {toolName}
        </span>

        {/* Meta: duration + tokens */}
        <span className="flex-shrink-0 text-[var(--font-size-xs)] text-[var(--muted)] whitespace-nowrap">
          {duration}
          {tokens > 0 && duration ? " \u00B7 " : ""}
          {tokens > 0 ? `${tokens} tok` : ""}
        </span>
      </div>

      {/* Observation */}
      {observation && (
        <p
          className={cn(
            "m-0 pl-[30px]",
            "text-[var(--font-size-xs)] text-[var(--muted)]",
            "leading-[var(--line-height-normal)]",
          )}
        >
          {observation}
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

interface StepsPanelProps {
  className?: string;
}

export function StepsPanel({ className }: StepsPanelProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const steps = useSessionStore((s) => s.steps);

  const hasSession = Boolean(selectedSessionId);

  return (
    <PanelSection
      defaultOpen={true}
      className={className}
    >
      <PanelSection.Header title="执行步骤" count={steps.length} />
      <PanelSection.Content>
        {!hasSession && (
          <EmptyState
            icon="📋"
            title="选择会话"
            description="切换到左侧会话列表开始"
          />
        )}
        {hasSession && steps.length === 0 && (
          <EmptyState
            icon="⏳"
            title="暂无步骤"
            description="发送消息后执行步骤将显示在这里"
          />
        )}
        {hasSession && steps.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {steps.map((step) => (
              <StepItem
                key={step.index}
                step={step}
                index={step.index}
              />
            ))}
          </div>
        )}
      </PanelSection.Content>
    </PanelSection>
  );
}
