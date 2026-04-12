// ── SessionItem ─────────────────────────────────────────────────
// Individual session entry using compound component pattern.
// Mirrors .session-item from render.js.

import type { SessionSummary, SessionStatus } from "../../types/session";
import { cn } from "../../lib/cn";
import { isSessionBusyStatus } from "../../lib/utils";

// ── Compound Component Root ────────────────────────────────────

interface SessionItemRootProps {
  /** Session data */
  session: SessionSummary;
  /** Whether this session is currently selected */
  isActive: boolean;
  /** Click handler */
  onClick?: () => void;
  /** Additional class names */
  className?: string;
  children: React.ReactNode;
}

function SessionItemRoot({
  session,
  isActive,
  onClick,
  className,
  children,
}: SessionItemRootProps) {
  const title = session.title || session.id;

  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        // Base layout matching .session-item
        "flex items-center justify-between gap-3 w-full min-w-0 min-h-[46px]",
        "px-3 py-2.5",
        "border-none rounded-[var(--radius-md)]",
        "bg-transparent text-[var(--text)] text-left",
        "appearance-none -webkit-appearance-none",
        "shadow-none overflow-hidden",
        "transition-[background,color,transform] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]",
        "cursor-pointer",
        "mx-[var(--space-sm)]",
        // Active state
        isActive && "bg-[var(--accent-soft)] text-[var(--accent)]",
        // Hover state
        !isActive && "hover:bg-[var(--sidebar-hover)]",
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── Title Sub-component ────────────────────────────────────────

interface SessionItemTitleProps {
  /** Display text (truncated) */
  children: React.ReactNode;
  className?: string;
}

function SessionItemTitle({ children, className }: SessionItemTitleProps) {
  return (
    <span
      className={cn(
        "flex-1 min-w-0 text-[var(--font-size-base)] font-[var(--font-weight-normal)]",
        "truncate block",
        className,
      )}
    >
      {children}
    </span>
  );
}

// ── Meta Sub-component ─────────────────────────────────────────

interface SessionItemMetaProps {
  /** Session status */
  status?: SessionStatus;
  /** Whether the session is compacting */
  isCompacting?: boolean;
  /** Whether this session is active */
  isActive: boolean;
  className?: string;
}

function SessionItemMeta({ status, isCompacting, isActive, className }: SessionItemMetaProps) {
  const statusStr = String(status || "");

  // Compacting badge (takes priority over idle)
  if (isCompacting && !isSessionBusyStatus(statusStr)) {
    return (
      <span
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-full text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
          "bg-[var(--warning-soft)] text-[var(--warning)]",
          className,
        )}
      >
        压缩中
      </span>
    );
  }

  // Interrupting badge
  if (statusStr === "interrupting") {
    return (
      <span
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-full text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
          "bg-[var(--success-soft)] text-[var(--success)]",
          className,
        )}
      >
        中断中
      </span>
    );
  }

  // Running badge
  if (isSessionBusyStatus(statusStr)) {
    return (
      <span
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-full text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
          "bg-[var(--success-soft)] text-[var(--success)]",
          className,
        )}
      >
        进行中
      </span>
    );
  }

  // Error badge
  if (statusStr === "error" || statusStr === "failed") {
    return (
      <span
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-full text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
          "bg-[var(--danger-soft)] text-[var(--danger)]",
          className,
        )}
      >
        异常
      </span>
    );
  }

  // Active session shows "more" indicator
  if (isActive) {
    return (
      <span
        className={cn(
          "text-[var(--muted-soft)] text-sm flex-shrink-0",
          className,
        )}
        aria-hidden="true"
      >
        ...
      </span>
    );
  }

  // Default: status dot
  const dotColor =
    isSessionBusyStatus(statusStr)
      ? "bg-[var(--success)]"
      : statusStr === "error" || statusStr === "failed"
        ? "bg-[var(--danger)]"
        : "bg-[var(--muted-soft)]";

  return (
    <span
      className={cn(
        "w-2 h-2 rounded-full flex-shrink-0",
        dotColor,
        className,
      )}
      aria-hidden="true"
    />
  );
}

// ── Compound Component Object ──────────────────────────────────

export const SessionItem = Object.assign(SessionItemRoot, {
  Title: SessionItemTitle,
  Meta: SessionItemMeta,
});
