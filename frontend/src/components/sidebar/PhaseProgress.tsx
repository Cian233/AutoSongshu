// ── Phase Progress Indicator ─────────────────────────────────────
// Displays the current penetration testing phase and progress.

import { cn } from "../../lib/cn";
import type { PentestPhase } from "../../types/session";

interface PhaseProgressProps {
  currentPhase: PentestPhase | null;
  className?: string;
}

const PHASES: { key: PentestPhase; label: string; icon: string }[] = [
  { key: "planning", label: "规划", icon: "📋" },
  { key: "recon", label: "侦察", icon: "🔍" },
  { key: "scanning", label: "扫描", icon: "🔎" },
  { key: "exploitation", label: "利用", icon: "⚡" },
  { key: "reporting", label: "报告", icon: "📝" },
];

const PHASE_ORDER: Record<PentestPhase, number> = {
  planning: 0,
  recon: 1,
  scanning: 2,
  exploitation: 3,
  reporting: 4,
};

export function PhaseProgress({ currentPhase, className }: PhaseProgressProps) {
  const currentIndex = currentPhase ? PHASE_ORDER[currentPhase] : -1;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>渗透测试阶段</span>
        {currentPhase && (
          <span className="font-medium text-foreground">
            {PHASES.find((p) => p.key === currentPhase)?.label}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1">
        {PHASES.map((phase, index) => {
          const isCompleted = currentIndex > index;
          const isActive = currentIndex === index;
          const isPending = currentIndex < index;

          return (
            <div
              key={phase.key}
              className="flex flex-1 flex-col items-center gap-1"
            >
              <div
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-sm transition-all",
                  isCompleted && "bg-primary text-primary-foreground",
                  isActive && "ring-2 ring-primary bg-primary/10 text-primary",
                  isPending && "bg-muted text-muted-foreground",
                )}
                title={phase.label}
              >
                {isCompleted ? "✓" : phase.icon}
              </div>
              <span
                className={cn(
                  "text-[10px] transition-colors",
                  isActive && "font-medium text-foreground",
                  isCompleted && "text-muted-foreground",
                  isPending && "text-muted-foreground/50",
                )}
              >
                {phase.label}
              </span>
            </div>
          );
        })}
      </div>
      {/* Progress bar */}
      <div className="relative h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="absolute left-0 top-0 h-full bg-primary transition-all duration-500"
          style={{
            width: currentPhase
              ? `${((currentIndex + 1) / PHASES.length) * 100}%`
              : "0%",
          }}
        />
      </div>
    </div>
  );
}
