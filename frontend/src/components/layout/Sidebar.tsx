// ── Sidebar ─────────────────────────────────────────────────────
// Left sidebar container with brand, actions, and session list.
// Mirrors the .sidebar structure from index.html.

import { Settings, Moon, Sun, Plus, Layers, PanelLeftClose } from "lucide-react";
import { useUIStore } from "../../stores/use-ui-store";
import { cn } from "../../lib/cn";
import { toggleSidebar } from "./AppShell";
import type { ReactNode } from "react";

interface SidebarProps {
  /** Session list component */
  sessionList: ReactNode;
  /** Callback when "New Chat" is clicked */
  onNewChat?: () => void;
  /** Additional class names */
  className?: string;
}

export function Sidebar({ sessionList, onNewChat, className }: SidebarProps) {
  const { theme, setTheme, toggleSettings } = useUIStore();

  const handleToggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  return (
    <div className={cn("flex flex-col gap-4 min-h-0 h-full min-w-0", className)}>
      {/* ── Sidebar Top ── */}
      <div className="grid gap-[18px]">
        {/* ── Brand Row ── */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {/* Logo Mark */}
            <span
              className="flex-shrink-0 w-8 h-8 flex items-center justify-center text-[var(--accent)]"
              aria-hidden="true"
            >
              <svg viewBox="0 0 24 24" className="w-5 h-5" fill="currentColor">
                <path d="M4 12c2.2-4.7 6.2-7 12-7-2.6 1.6-4.2 3.7-5 6.3 3.2-.7 6-.2 8 1.4-2.8.1-4.8 1.1-6.2 3 2 .2 3.6 1.1 4.7 2.7-2.3-.8-4.8-.7-7.4.2-2.1.8-4.2 1-6.1.5 1.5-.9 2.5-2.2 3-3.8C5.8 15 4.7 13.7 4 12Z" />
              </svg>
            </span>
            {/* Brand Copy */}
            <div className="min-w-0">
              <h1 className="m-[10px_0_0] text-[var(--text)] text-[var(--font-size-lg)] font-[var(--font-weight-bold)] leading-[1.1] tracking-[-0.01em]">
                AutoSongshu
              </h1>
              <p className="text-[var(--font-size-xs)] text-[var(--muted)] font-[var(--font-weight-medium)] uppercase">
                授权评估工作台
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              type="button"
              aria-label="隐藏侧边栏"
              title="隐藏侧边栏"
              onClick={toggleSidebar}
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg",
                "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
                "transition-colors duration-150",
              )}
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
            <button
              type="button"
              aria-label="默认设置"
              title="默认设置"
              onClick={toggleSettings}
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg",
                "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
                "transition-colors duration-150",
              )}
            >
              <Settings className="w-4 h-4" />
            </button>
            <button
              type="button"
              aria-label="切换主题"
              title="切换主题 (Ctrl+Shift+D)"
              onClick={handleToggleTheme}
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg text-base",
                "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
                "transition-colors duration-150",
              )}
            >
              {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {/* ── Actions ── */}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={onNewChat}
            className={cn(
              "flex items-center justify-center gap-2 w-full",
              "min-h-[42px] px-4 py-2.5",
              "rounded-xl border-none",
              "bg-[var(--accent)] text-white",
              "font-[var(--font-weight-medium)] text-[var(--font-size-md)]",
              "cursor-pointer transition-all duration-200",
              "hover:bg-[var(--accent-hover)] active:scale-[0.98]",
            )}
          >
            <Plus className="w-4 h-4" strokeWidth={1.8} />
            <span>开启新对话</span>
          </button>
          <a
            href="/knowledge"
            className={cn(
              "flex items-center justify-center gap-2 w-full",
              "min-h-[42px] px-4 py-2.5",
              "rounded-xl",
              "bg-[var(--sidebar-soft)] text-[var(--text)]",
              "font-[var(--font-weight-medium)] text-[var(--font-size-md)]",
              "transition-colors duration-150",
              "hover:bg-[var(--sidebar-hover)]",
            )}
          >
            <Layers className="w-4 h-4" strokeWidth={1.8} />
            <span>知识库</span>
          </a>
        </div>
      </div>

      {/* ── Session List ── */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {sessionList}
      </div>
    </div>
  );
}
