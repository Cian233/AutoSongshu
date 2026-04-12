// ── PanelSection ────────────────────────────────────────────────
// Generic collapsible panel using the compound component pattern.
// Built on native <details>/<summary> for accessibility and zero-JS toggle.
// Used by StepsPanel, FindingsPanel, ShortcutsPanel in the right sidebar.

import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/cn";
import type { ReactNode, HTMLAttributes } from "react";

// ── Root ────────────────────────────────────────────────────────

interface PanelSectionProps extends HTMLAttributes<HTMLDetailsElement> {
  /** Whether the panel is expanded by default */
  defaultOpen?: boolean;
  /** Additional class names */
  className?: string;
  children: ReactNode;
}

export function PanelSection({
  defaultOpen = true,
  className,
  children,
  ...rest
}: PanelSectionProps) {
  return (
    <details
      open={defaultOpen}
      className={cn("group", className)}
      {...rest}
    >
      {children}
    </details>
  );
}

// ── Header ──────────────────────────────────────────────────────

interface PanelSectionHeaderProps {
  /** Panel title text */
  title: string;
  /** Optional count badge (e.g. number of steps / findings) */
  count?: number;
  className?: string;
  children?: React.ReactNode;
}

export function PanelSectionHeader({
  title,
  count,
  className,
  children,
}: PanelSectionHeaderProps) {
  return (
    <summary
      className={cn(
        "flex items-center justify-between gap-2",
        "min-h-[36px] px-3 py-2",
        "cursor-pointer select-none list-none",
        "rounded-[var(--radius-md)]",
        "text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] text-[var(--text)]",
        "hover:bg-[var(--sidebar-hover)]",
        "transition-colors duration-150",
        className,
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="truncate">{title}</span>
        {count !== undefined && count > 0 && (
          <span
            className={cn(
              "flex-shrink-0 inline-flex items-center justify-center",
              "min-w-[20px] h-5 px-1.5",
              "rounded-full text-[var(--font-size-xs)] font-[var(--font-weight-semibold)]",
              "bg-[var(--bg-soft)] text-[var(--muted)]",
            )}
          >
            {count}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        {children}
        <ChevronDown
          className={cn(
            "w-4 h-4 text-[var(--muted)]",
            "transition-transform duration-200",
            "group-open:rotate-180",
          )}
        />
      </div>
    </summary>
  );
}

// ── Content ─────────────────────────────────────────────────────

interface PanelSectionContentProps extends HTMLAttributes<HTMLDivElement> {
  className?: string;
  children: ReactNode;
}

export function PanelSectionContent({
  className,
  children,
  ...rest
}: PanelSectionContentProps) {
  return (
    <div
      className={cn(
        "px-3 pb-2 pt-1",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

// ── Namespace ───────────────────────────────────────────────────

PanelSection.Header = PanelSectionHeader;
PanelSection.Content = PanelSectionContent;
