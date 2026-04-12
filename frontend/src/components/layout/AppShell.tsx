// ── AppShell ────────────────────────────────────────────────────
// Three-column layout container using CSS Grid.
// Mirrors the .app-shell structure from styles.css:
//   grid-template-columns: var(--sidebar-width) minmax(0,1fr) var(--right-sidebar-width)

import { useState, useEffect, type ReactNode } from "react";
import { cn } from "../../lib/cn";

interface AppShellProps {
  /** Left sidebar content (260px) */
  sidebar: ReactNode;
  /** Main chat area (flexible width) */
  children: ReactNode;
  /** Right panel content (280px, hidden on small screens) */
  rightPanel?: ReactNode;
  /** Additional class names */
  className?: string;
}

export function AppShell({ sidebar, children, rightPanel, className }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Allow child components to toggle the sidebar via custom event
  useEffect(() => {
    const handler = () => setSidebarOpen((v) => !v);
    window.addEventListener("sidebar:toggle", handler);
    return () => window.removeEventListener("sidebar:toggle", handler);
  }, []);

  return (
    <div
      className={cn(
        // Base grid layout matching .app-shell
        "grid gap-0 h-[100dvh] min-h-[100dvh] overflow-hidden p-0",
        // Three-column grid: sidebar | chat | right panel
        sidebarOpen
          ? "[grid-template-columns:var(--sidebar-width)_minmax(0,1fr)_var(--right-sidebar-width)]"
          : "[grid-template-columns:0px_minmax(0,1fr)_var(--right-sidebar-width)]",
        // Background from .app-shell
        "bg-[var(--bg)]",
        // Responsive: hide right panel below 1024px
        "max-lg:[grid-template-columns:var(--sidebar-width)_minmax(0,1fr)]",
        // Responsive: single column below 820px
        "max-[820px]:[grid-template-columns:1fr]",
        className,
      )}
    >
      {/* Left Sidebar */}
      <aside
        className={cn(
          "flex flex-col gap-4 min-h-0 h-full",
          "px-4 py-6",
          "bg-[var(--sidebar)] border-r border-[var(--line)]",
          "overflow-x-hidden overflow-y-auto",
          // Responsive adjustments
          "max-lg:h-auto max-lg:min-h-auto max-lg:overflow-visible max-lg:border-r-0 max-lg:border-b border-b-[var(--line)]",
          "max-[820px]:p-4",
          // Collapse transition
          "transition-[width,padding,opacity] duration-200 ease-in-out",
          !sidebarOpen && "w-0 !px-0 !py-0 !border-r-0 opacity-0 pointer-events-none",
        )}
      >
        {sidebar}
      </aside>

      {/* Toggle button — visible when sidebar is collapsed */}
      {!sidebarOpen && (
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="fixed top-4 left-4 z-50 flex items-center justify-center w-9 h-9 rounded-[var(--radius-md)] bg-[var(--sidebar)] border border-[var(--line)] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--bg-soft)] transition-colors shadow-sm cursor-pointer"
          title="显示侧边栏"
          aria-label="显示侧边栏"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
        </button>
      )}

      {/* Main Chat Area */}
      <main className="flex flex-col min-h-0 min-w-0 h-full overflow-hidden">
        {children}
      </main>

      {/* Right Panel */}
      {rightPanel && (
        <aside
          className={cn(
            "flex flex-col min-h-0 h-full",
            "px-4 py-6 overflow-y-auto",
            "bg-[var(--sidebar)] border-l border-[var(--line)]",
            // Hide on smaller screens
            "max-lg:hidden",
          )}
        >
          {rightPanel}
        </aside>
      )}
    </div>
  );
}

/** Dispatch a sidebar toggle event (call from any child component) */
export function toggleSidebar() {
  window.dispatchEvent(new CustomEvent("sidebar:toggle"));
}
