// ── SearchPanel ─────────────────────────────────────────────────
// Message search panel, migrated from render.js search functions.
// Provides:
//   - Real-time search input
//   - Match count display (X / Y)
//   - Previous / Next navigation buttons
//   - Close button
//   - Escape to close
//   - Search highlight context (exposes query + currentIndex for
//     downstream components to render <mark> tags)
//
// Integrates with useSearchStore for open/close state and
// useMessageSearch for search logic.

import { useEffect, useRef, useCallback } from "react";
import { Search, ChevronUp, ChevronDown, X } from "lucide-react";
import { useSearchStore } from "../../stores/use-search-store";
import { useMessageSearch } from "../../hooks/use-message-search";
import { cn } from "../../lib/cn";

// ── Component ───────────────────────────────────────────────────

interface SearchPanelProps {
  className?: string;
}

export function SearchPanel({ className }: SearchPanelProps) {
  const searchOpen = useSearchStore((s) => s.searchOpen);
  const setSearchOpen = useSearchStore((s) => s.setSearchOpen);

  const {
    query,
    setQuery,
    totalMatches,
    currentIndex,
    goNext,
    goPrev,
    clear,
    containerRef,
  } = useMessageSearch();

  const inputRef = useRef<HTMLInputElement>(null);

  // ── Focus input when panel opens ──
  useEffect(() => {
    if (searchOpen && inputRef.current) {
      // Small delay to ensure DOM is ready
      const timer = setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [searchOpen]);

  // ── Escape to close ──
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setSearchOpen(false);
        clear();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (e.shiftKey) {
          goPrev();
        } else {
          goNext();
        }
      }
    },
    [setSearchOpen, clear, goNext, goPrev],
  );

  // ── Close handler ──
  const handleClose = useCallback(() => {
    setSearchOpen(false);
    clear();
  }, [setSearchOpen, clear]);

  // ── Input change handler (real-time search) ──
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setQuery(e.target.value);
    },
    [setQuery],
  );

  // ── Don't render when closed ──
  if (!searchOpen) {
    return null;
  }

  // ── Count display ──
  let countText = "";
  if (query.trim()) {
    if (totalMatches === 0) {
      countText = "无匹配";
    } else {
      countText = `${currentIndex + 1} / ${totalMatches}`;
    }
  }

  const hasMatches = totalMatches > 0;

  return (
    <>
      {/* Search Bar */}
      <div
        className={cn(
          "flex items-center gap-2",
          "px-3 py-2",
          "border-b border-[var(--line)]",
          "bg-[var(--sidebar)]",
          className,
        )}
      >
        {/* Search icon */}
        <Search className="w-4 h-4 flex-shrink-0 text-[var(--muted)]" />

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="搜索消息..."
          spellCheck={false}
          autoComplete="off"
          className={cn(
            "flex-1 min-w-0",
            "h-7 px-2",
            "rounded-[var(--radius-sm)]",
            "bg-[var(--bg-soft)] border border-[var(--line)]",
            "text-[var(--font-size-sm)] text-[var(--text)]",
            "placeholder:text-[var(--muted)]",
            "outline-none",
            "focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]/30",
            "transition-colors duration-150",
          )}
        />

        {/* Count display */}
        {countText && (
          <span
            className={cn(
              "flex-shrink-0",
              "text-[var(--font-size-xs)] font-[var(--font-weight-medium)]",
              hasMatches
                ? "text-[var(--text-secondary)]"
                : "text-[var(--muted)]",
              "whitespace-nowrap min-w-[40px] text-center",
            )}
          >
            {countText}
          </span>
        )}

        {/* Prev button */}
        <button
          type="button"
          onClick={goPrev}
          disabled={!hasMatches}
          title="上一个匹配 (Shift+Enter)"
          className={cn(
            "flex items-center justify-center",
            "w-7 h-7 rounded-[var(--radius-sm)]",
            "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
            "transition-colors duration-100",
            "cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed",
          )}
        >
          <ChevronUp className="w-4 h-4" />
        </button>

        {/* Next button */}
        <button
          type="button"
          onClick={goNext}
          disabled={!hasMatches}
          title="下一个匹配 (Enter)"
          className={cn(
            "flex items-center justify-center",
            "w-7 h-7 rounded-[var(--radius-sm)]",
            "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
            "transition-colors duration-100",
            "cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed",
          )}
        >
          <ChevronDown className="w-4 h-4" />
        </button>

        {/* Close button */}
        <button
          type="button"
          onClick={handleClose}
          title="关闭搜索 (Esc)"
          className={cn(
            "flex items-center justify-center",
            "w-7 h-7 rounded-[var(--radius-sm)]",
            "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
            "transition-colors duration-100",
            "cursor-pointer",
          )}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Invisible container ref for scroll targeting */}
      {/* This ref should be forwarded to the chat scroll container */}
      <div
        ref={containerRef as React.RefObject<HTMLDivElement>}
        className="hidden"
        aria-hidden="true"
        data-search-container
      />
    </>
  );
}
