// ── Command Suggestions Dropdown ────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js —
//   showCommandSuggestions(), hideCommandSuggestions()
//
// Renders a dropdown list of matching slash-commands below the
// composer textarea. Supports keyboard navigation highlighting and
// click selection.

import React, { useRef, useEffect } from "react";
import type { Command } from "../../types/api";
import { cn } from "../../lib/cn";

// ── Props ───────────────────────────────────────────────────────

export interface CommandSuggestionsProps {
  /** List of matching commands to display */
  suggestions: Command[];
  /** Index of the currently highlighted suggestion */
  selectedIndex: number;
  /** Called when a suggestion is clicked */
  onSelect: (command: Command, index: number) => void;
  /** Additional CSS class names */
  className?: string;
}

// ── Component ───────────────────────────────────────────────────

export const CommandSuggestions: React.FC<CommandSuggestionsProps> = ({
  suggestions,
  selectedIndex,
  onSelect,
  className,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  // Auto-scroll the selected item into view
  useEffect(() => {
    if (selectedRef.current && containerRef.current) {
      selectedRef.current.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    }
  }, [selectedIndex]);

  if (!suggestions.length) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "absolute bottom-full left-0 right-0 mb-1",
        "max-h-60 overflow-y-auto rounded-lg border border-border bg-popover shadow-lg",
        "py-1 z-50",
        className,
      )}
      role="listbox"
      aria-label="命令建议"
    >
      {suggestions.map((cmd, index) => (
        <button
          key={cmd.name}
          ref={index === selectedIndex ? selectedRef : undefined}
          type="button"
          role="option"
          aria-selected={index === selectedIndex}
          className={cn(
            "flex w-full items-center gap-2 px-3 py-2 text-left text-sm",
            "transition-colors duration-75",
            "hover:bg-accent hover:text-accent-foreground",
            index === selectedIndex && "bg-accent text-accent-foreground",
          )}
          onClick={() => onSelect(cmd, index)}
          onMouseEnter={() => onSelect(cmd, index)}
        >
          <span className="font-mono font-medium text-foreground">
            /{cmd.name}
          </span>
          {cmd.description && (
            <span className="text-muted-foreground truncate">
              {cmd.description}
            </span>
          )}
        </button>
      ))}
    </div>
  );
};

export default CommandSuggestions;
