// ── Command Definitions and Matching Logic ───────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js —
//   loadCommands(), showCommandSuggestions(), hideCommandSuggestions(),
//   wireCommandAutocomplete()
//
// Provides:
//   - Command type definition
//   - Command loading from the API
//   - Command filtering and matching logic
//   - Slash-prefix detection in text input

import type { Command, ListCommandsResponse } from "../types/api";
import { fetchJson } from "../lib/api";
import { API_ENDPOINTS } from "../lib/api-endpoints";

// ── Module-level cache ──────────────────────────────────────────

let cachedCommands: Command[] | null = null;

// ── Command Loading ─────────────────────────────────────────────

/**
 * Load the list of available slash-commands from the server.
 * Results are cached after the first successful load.
 */
export async function loadCommands(): Promise<Command[]> {
  if (cachedCommands) {
    return cachedCommands;
  }
  try {
    const payload = await fetchJson<ListCommandsResponse>(API_ENDPOINTS.COMMANDS);
    cachedCommands = payload.commands || [];
    return cachedCommands;
  } catch {
    return [];
  }
}

/**
 * Clear the command cache, forcing a reload on next call to loadCommands().
 */
export function clearCommandCache(): void {
  cachedCommands = null;
}

// ── Slash-Prefix Detection ──────────────────────────────────────

/**
 * Extract the slash-prefixed filter string from text before the cursor.
 * Returns null if the cursor is not immediately after a slash command prefix.
 *
 * @example
 *   extractSlashFilter("help me /sea", 13)  // => "/sea"
 *   extractSlashFilter("hello world", 5)    // => null
 *   extractSlashFilter("/foo bar", 4)       // => "/foo"
 */
export function extractSlashFilter(
  text: string,
  cursorPosition: number,
): string | null {
  const beforeCursor = text.slice(0, cursorPosition);
  const match = beforeCursor.match(/\/[a-zA-Z]*$/);
  return match ? match[0] : null;
}

// ── Command Filtering ───────────────────────────────────────────

/**
 * Filter commands by a slash-prefixed query string.
 * Matches against command name and aliases (case-insensitive prefix match).
 *
 * @param commands - Full list of available commands.
 * @param filter   - Slash-prefixed filter string (e.g. "/sea").
 * @returns Filtered and ordered list of matching commands.
 */
export function filterCommands(
  commands: Command[],
  filter: string,
): Command[] {
  const query = String(filter || "").toLowerCase().replace(/^\//, "");
  if (!query) {
    return commands;
  }
  return commands.filter((cmd) => {
    const name = String(cmd.name || "").toLowerCase();
    const aliases = Array.isArray(cmd.aliases)
      ? cmd.aliases.map((a) => String(a).toLowerCase())
      : [];
    return name.startsWith(query) || aliases.some((a) => a.startsWith(query));
  });
}

// ── Command Replacement ─────────────────────────────────────────

/**
 * Replace the slash-prefixed filter in the text with a full command name.
 * Returns the new text and the cursor position after the command name.
 *
 * @param text          - The full text content.
 * @param cursorPosition - Current cursor position in the text.
 * @param commandName   - The full command name to insert.
 * @returns Object with `text` (new text) and `cursorPosition` (new cursor position).
 */
export function replaceSlashWithCommand(
  text: string,
  cursorPosition: number,
  commandName: string,
): { text: string; cursorPosition: number } {
  const beforeCursor = text.slice(0, cursorPosition);
  const afterCursor = text.slice(cursorPosition);
  const slashMatch = beforeCursor.match(/\/[a-zA-Z]*$/);

  if (!slashMatch) {
    return { text, cursorPosition };
  }

  const newBefore = beforeCursor.slice(0, -slashMatch[0].length) + commandName + " ";
  const newCursorPos = newBefore.length;
  return {
    text: newBefore + afterCursor,
    cursorPosition: newCursorPos,
  };
}

// ── Risk Level Helpers ──────────────────────────────────────────

export type RiskLevel = "low" | "medium" | "high" | "critical";

const RISK_LABELS: Record<RiskLevel, string> = {
  low: "低风险",
  medium: "中等风险",
  high: "高风险",
  critical: "严重风险",
};

/**
 * Get the Chinese label for a risk level.
 */
export function getRiskLabel(level: RiskLevel | string): string {
  const normalized = String(level || "medium").toLowerCase() as RiskLevel;
  return RISK_LABELS[normalized] || RISK_LABELS.medium;
}

/**
 * Get the CSS class suffix for a risk level badge.
 */
export function getRiskClass(level: RiskLevel | string): string {
  const normalized = String(level || "medium").toLowerCase();
  if (normalized === "critical") return "is-critical";
  if (normalized === "high") return "is-high";
  if (normalized === "low") return "is-low";
  return "is-medium";
}
