// ── ShortcutsPanel ──────────────────────────────────────────────
// Keyboard shortcuts reference panel for the right sidebar.
// Displays a list of key combinations with descriptions.
// Uses PanelSection for consistent collapsible behavior.

import { PanelSection } from "./PanelSection";
import { cn } from "../../lib/cn";

// ── Shortcut definitions ────────────────────────────────────────

interface Shortcut {
  /** Key combination label (e.g. "Ctrl + N") */
  keys: string;
  /** Description of what the shortcut does */
  description: string;
}

const SHORTCUTS: Shortcut[] = [
  { keys: "Ctrl + N", description: "新建对话" },
  { keys: "Ctrl + F", description: "搜索消息" },
  { keys: "Ctrl + Shift + D", description: "切换主题" },
  { keys: "Ctrl + ,", description: "打开设置" },
  { keys: "Ctrl + Enter", description: "发送消息" },
  { keys: "Escape", description: "关闭面板" },
  { keys: "Enter", description: "搜索下一个匹配" },
  { keys: "Shift + Enter", description: "搜索上一个匹配" },
];

// ── Shortcut Item ───────────────────────────────────────────────

function ShortcutItem({ shortcut }: { shortcut: Shortcut }) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3",
        "min-h-[32px] px-2.5 py-1.5",
        "rounded-[var(--radius-sm)]",
        "transition-colors duration-100",
        "hover:bg-[var(--sidebar-hover)]",
      )}
    >
      {/* Description */}
      <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
        {shortcut.description}
      </span>

      {/* Key combo */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {shortcut.keys.split(" + ").map((key, idx) => (
          <span
            key={`${key}-${idx}`}
            className={cn(
              "inline-flex items-center justify-center",
              "min-w-[22px] h-5 px-1.5",
              "rounded-[var(--radius-sm)]",
              "bg-[var(--bg-soft)] border border-[var(--line)]",
              "text-[var(--font-size-xs)] font-[var(--font-mono)] text-[var(--text-secondary)]",
              "shadow-[0_1px_0_var(--line)]",
            )}
          >
            {key}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Component ───────────────────────────────────────────────────

interface ShortcutsPanelProps {
  className?: string;
}

export function ShortcutsPanel({ className }: ShortcutsPanelProps) {
  return (
    <PanelSection
      defaultOpen={false}
      className={className}
    >
      <PanelSection.Header title="快捷键" />
      <PanelSection.Content>
        <div className="flex flex-col gap-0.5">
          {SHORTCUTS.map((shortcut) => (
            <ShortcutItem key={shortcut.keys} shortcut={shortcut} />
          ))}
        </div>
      </PanelSection.Content>
    </PanelSection>
  );
}
