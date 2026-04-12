// ── Command Autocomplete Hook ───────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js —
//   wireCommandAutocomplete()
//
// Provides a React hook that manages command autocomplete state:
//   - Loads commands from the API on mount
//   - Monitors textarea input for slash-prefixed queries
//   - Filters matching commands
//   - Tracks the currently selected suggestion index
//   - Handles keyboard navigation (ArrowUp/Down, Enter, Escape)
//   - Handles click selection

import { useState, useEffect, useCallback, useRef } from "react";
import type { Command } from "../types/api";
import {
  loadCommands,
  extractSlashFilter,
  filterCommands,
  replaceSlashWithCommand,
} from "../lib/commands";

// ── Hook Return Type ────────────────────────────────────────────

export interface CommandAutocompleteState {
  /** Whether the suggestions dropdown is visible */
  isOpen: boolean;
  /** Filtered list of matching commands */
  suggestions: Command[];
  /** Index of the currently selected suggestion (-1 if none) */
  selectedIndex: number;
  /** Select the next suggestion (ArrowDown) */
  selectNext: () => void;
  /** Select the previous suggestion (ArrowUp) */
  selectPrevious: () => void;
  /** Confirm the currently selected suggestion */
  confirmSelection: () => void;
  /** Close the suggestions dropdown */
  close: () => void;
  /** Update the filter based on textarea content and cursor position */
  updateFilter: (text: string, cursorPosition: number) => void;
  /** Handle a click on a specific suggestion by index */
  selectByIndex: (index: number) => void;
  /** Whether commands have been loaded */
  loaded: boolean;
}

// ── Hook ────────────────────────────────────────────────────────

/**
 * Hook that manages slash-command autocomplete state for a textarea.
 *
 * @returns CommandAutocompleteState with all necessary state and handlers.
 *
 * @example
 * ```tsx
 * const autocomplete = useCommandAutocomplete();
 *
 * <textarea
 *   onInput={(e) => autocomplete.updateFilter(e.currentTarget.value, e.currentTarget.selectionStart)}
 *   onKeyDown={(e) => {
 *     if (autocomplete.isOpen) {
 *       if (e.key === "ArrowDown") { e.preventDefault(); autocomplete.selectNext(); }
 *       else if (e.key === "ArrowUp") { e.preventDefault(); autocomplete.selectPrevious(); }
 *       else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); autocomplete.confirmSelection(); }
 *       else if (e.key === "Escape") { autocomplete.close(); }
 *     }
 *   }}
 * />
 * {autocomplete.isOpen && (
 *   <CommandSuggestions
 *     suggestions={autocomplete.suggestions}
 *     selectedIndex={autocomplete.selectedIndex}
 *     onSelect={autocomplete.selectByIndex}
 *   />
 * )}
 * ```
 */
export function useCommandAutocomplete(): CommandAutocompleteState {
  const [commands, setCommands] = useState<Command[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<Command[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Keep a ref to the latest state for use in callbacks without stale closures
  const suggestionsRef = useRef(suggestions);
  suggestionsRef.current = suggestions;

  // ── Load commands on mount ────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    loadCommands().then((cmds) => {
      if (!cancelled) {
        setCommands(cmds);
        setLoaded(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Update filter ─────────────────────────────────────────────

  const updateFilter = useCallback((text: string, cursorPosition: number) => {
    const filter = extractSlashFilter(text, cursorPosition);
    if (filter !== null) {
      const filtered = filterCommands(commands, filter);
      if (filtered.length > 0) {
        setSuggestions(filtered);
        setSelectedIndex(0);
        setIsOpen(true);
      } else {
        setIsOpen(false);
        setSuggestions([]);
      }
    } else {
      setIsOpen(false);
      setSuggestions([]);
    }
  }, [commands]);

  // ── Navigation ────────────────────────────────────────────────

  const selectNext = useCallback(() => {
    setSelectedIndex((prev) => {
      const max = suggestionsRef.current.length - 1;
      return Math.min(prev + 1, max);
    });
  }, []);

  const selectPrevious = useCallback(() => {
    setSelectedIndex((prev) => {
      return Math.max(prev - 1, 0);
    });
  }, []);

  // ── Confirm selection ─────────────────────────────────────────
  // This is a no-op in the hook itself; the parent component must
  // implement the actual text replacement because we need access to
  // the textarea ref. Instead, we expose the selected command and
  // let the parent handle replacement.

  const confirmSelection = useCallback(() => {
    // The parent should call getSelectedCommand() and handle replacement
    // This is intentionally a no-op; see getSelectedCommand() below.
  }, []);

  // ── Close ─────────────────────────────────────────────────────

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  // ── Select by index (click) ───────────────────────────────────

  const selectByIndex = useCallback((index: number) => {
    setSelectedIndex(index);
  }, []);

  return {
    isOpen,
    suggestions,
    selectedIndex,
    selectNext,
    selectPrevious,
    confirmSelection,
    close,
    updateFilter,
    selectByIndex,
    loaded,
  };
}

// ── Helper: get selected command ────────────────────────────────

/**
 * Get the currently selected command from the autocomplete state.
 * Returns null if no command is selected or the dropdown is closed.
 */
export function getSelectedCommand(
  suggestions: Command[],
  selectedIndex: number,
): Command | null {
  if (selectedIndex < 0 || selectedIndex >= suggestions.length) {
    return null;
  }
  return suggestions[selectedIndex] || null;
}

// ── Helper: apply command to textarea ───────────────────────────

/**
 * Apply a selected command to a textarea element by replacing the
 * slash-prefixed filter with the full command name.
 *
 * @param textarea     - The textarea DOM element.
 * @param commandName  - The full command name to insert.
 */
export function applyCommandToTextarea(
  textarea: HTMLTextAreaElement,
  commandName: string,
): void {
  const text = textarea.value;
  const cursorPosition = textarea.selectionStart || 0;
  const { text: newText, cursorPosition: newCursorPos } = replaceSlashWithCommand(
    text,
    cursorPosition,
    commandName,
  );
  textarea.value = newText;
  textarea.setSelectionRange(newCursorPos, newCursorPos);
  textarea.focus();
}
