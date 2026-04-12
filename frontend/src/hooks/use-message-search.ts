// ── useMessageSearch ────────────────────────────────────────────
// Message search hook, migrated from render.js search functions.
// Searches across all messages in the current session, tracks
// match count, current index, and supports prev/next navigation
// with auto-scroll to the matched element.
//
// Search strategy:
//   1. Collect all text content from messages (text parts, reasoning parts,
//      tool names, observation text).
//   2. Perform case-insensitive matching.
//   3. Return flat list of { messageId, matchIndex, text, offset } results.
//   4. Navigate with goNext() / goPrev() and auto-scroll via DOM refs.

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useSessionStore } from "../stores/use-session-store";
import type { Message } from "../types/session";

// ── Types ───────────────────────────────────────────────────────

export interface SearchMatch {
  /** The message ID containing this match */
  messageId: string;
  /** Index of this match within the flat results list */
  matchIndex: number;
  /** The matched text snippet (for display) */
  text: string;
  /** Character offset within the source text */
  offset: number;
}

export interface UseMessageSearchReturn {
  /** Current search query */
  query: string;
  /** Set the search query and recompute matches */
  setQuery: (query: string) => void;
  /** All matches for the current query */
  matches: SearchMatch[];
  /** Total number of matches */
  totalMatches: number;
  /** Current match index (1-based for display, 0 when no matches) */
  currentIndex: number;
  /** Navigate to the next match (wraps around) */
  goNext: () => void;
  /** Navigate to the previous match (wraps around) */
  goPrev: () => void;
  /** Clear the search query and matches */
  clear: () => void;
  /** Ref to attach to the chat thread container for scroll-into-view */
  containerRef: React.RefObject<HTMLDivElement | null>;
}

// ── Text extraction ─────────────────────────────────────────────

/**
 * Extract all searchable text segments from a message's content parts.
 * Returns an array of { text, messageId } entries.
 */
function extractTextParts(message: Message): Array<{ text: string; messageId: string }> {
  const parts: Array<{ text: string; messageId: string }> = [];
  const messageId = message.id;

  for (const part of message.content) {
    switch (part.type) {
      case "input_text":
      case "output_text":
      case "reasoning":
        parts.push({ text: part.text, messageId });
        break;
      case "tool_call":
        parts.push({
          text: `${part.name} ${JSON.stringify(part.arguments)}`,
          messageId,
        });
        break;
      case "tool_result": {
        // Extract text from tool result content parts
        for (const contentPart of part.content) {
          if (contentPart.type === "input_text" || contentPart.type === "output_text") {
            parts.push({ text: contentPart.text, messageId });
          }
        }
        break;
      }
    }
  }

  return parts;
}

/**
 * Escape special regex characters in a string.
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Find all occurrences of `query` in `text`, returning match offsets.
 */
function findMatchesInText(
  text: string,
  regex: RegExp,
  messageId: string,
  startIndex: number,
): SearchMatch[] {
  const results: SearchMatch[] = [];
  let match: RegExpExecArray | null;

  // Reset lastIndex for global regex
  regex.lastIndex = 0;

  while ((match = regex.exec(text)) !== null) {
    results.push({
      messageId,
      matchIndex: startIndex + results.length,
      text: match[0],
      offset: match.index,
    });

    // Prevent infinite loops on zero-length matches
    if (match[0].length === 0) {
      regex.lastIndex++;
    }
  }

  return results;
}

// ── Hook ────────────────────────────────────────────────────────

export function useMessageSearch(): UseMessageSearchReturn {
  const [query, setQueryState] = useState("");
  const [currentIndex, setCurrentIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);

  const session = selectedSessionId
    ? sessionDetails.get(selectedSessionId)
    : null;

  const messages = session?.messages || [];

  // ── Compute matches whenever query or messages change ──
  const matches: SearchMatch[] = useMemo(() => {
    if (!query.trim()) return [];

    const trimmed = query.trim();
    const regex = new RegExp(escapeRegex(trimmed), "gi");
    const allMatches: SearchMatch[] = [];

    for (const message of messages) {
      if (message.compacted) continue;
      const textParts = extractTextParts(message);
      for (const { text, messageId } of textParts) {
        const partMatches = findMatchesInText(
          text,
          regex,
          messageId,
          allMatches.length,
        );
        allMatches.push(...partMatches);
      }
    }

    return allMatches;
  }, [query, messages]);

  const totalMatches = matches.length;

  // ── Reset current index when matches change ──
  useEffect(() => {
    if (totalMatches > 0 && currentIndex >= totalMatches) {
      setCurrentIndex(totalMatches - 1);
    } else if (totalMatches === 0) {
      setCurrentIndex(0);
    }
  }, [totalMatches, currentIndex]);

  // ── Auto-scroll to current match ──
  useEffect(() => {
    if (totalMatches === 0 || currentIndex < 0) return;

    const currentMatch = matches[currentIndex];
    if (!currentMatch) return;

    // Find the DOM element for the matched message
    const container = containerRef.current;
    if (!container) return;

    // Look for message elements by data attributes or IDs
    const messageEl = container.querySelector(
      `[data-message-id="${currentMatch.messageId}"]`,
    );

    if (messageEl) {
      // Check if the element is within the visible area of the scroll container
      const containerRect = container.getBoundingClientRect();
      const elementRect = messageEl.getBoundingClientRect();

      const isAboveVisible = elementRect.top < containerRect.top + 60;
      const isBelowVisible = elementRect.bottom > containerRect.bottom - 20;

      if (isAboveVisible || isBelowVisible) {
        messageEl.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [currentIndex, totalMatches, matches]);

  // ── Actions ──

  const setQuery = useCallback((newQuery: string) => {
    setQueryState(newQuery);
    setCurrentIndex(0);
  }, []);

  const goNext = useCallback(() => {
    if (totalMatches === 0) return;
    setCurrentIndex((prev) => (prev + 1) % totalMatches);
  }, [totalMatches]);

  const goPrev = useCallback(() => {
    if (totalMatches === 0) return;
    setCurrentIndex((prev) => (prev - 1 + totalMatches) % totalMatches);
  }, [totalMatches]);

  const clear = useCallback(() => {
    setQueryState("");
    setCurrentIndex(0);
  }, []);

  return {
    query,
    setQuery,
    matches,
    totalMatches,
    currentIndex,
    goNext,
    goPrev,
    clear,
    containerRef,
  };
}
