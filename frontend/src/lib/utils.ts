// ── Utility Functions ────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/utils.js

/**
 * Get a DOM element by ID.
 */
export function byId(id: string): HTMLElement | null {
  return document.getElementById(id);
}

/**
 * Escape HTML special characters to prevent XSS.
 */
export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Truncate text to a maximum length, appending an ellipsis if needed.
 */
export function truncate(text: unknown, length = 72): string {
  const value = String(text ?? "").trim();
  if (!value) {
    return "";
  }
  if (value.length <= length) {
    return value;
  }
  return `${value.slice(0, length - 1)}\u2026`;
}

/**
 * Format a date value into a locale string.
 * Returns an em-dash for falsy values.
 */
export function formatDate(value: unknown): string {
  if (!value) {
    return "\u2014";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

/**
 * Format a date/time value as a short time string (e.g. "14:30").
 * Falls back to "—" for empty/invalid values.
 */
export function formatTime(value: unknown): string {
  if (!value) return "\u2014";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Split text into lines, trim whitespace, and filter out empty lines.
 */
export function normalizeLines(value: unknown): string[] {
  return String(value ?? "")
    .split(/\r?\n/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Sanitize a URL to ensure it uses a safe protocol.
 * Returns empty string if the URL is invalid or uses a disallowed protocol.
 */
export function sanitizeUrl(value: unknown): string {
  try {
    const url = new URL(String(value || ""), window.location.href);
    if (["http:", "https:", "mailto:"].includes(url.protocol)) {
      return url.toString();
    }
  } catch (_) {
    // Invalid URL
  }
  return "";
}

/**
 * Format a number with locale-aware thousand separators.
 */
export function formatCount(value: unknown): string {
  return Number(value || 0).toLocaleString();
}

/**
 * Shorten an ID string for display purposes.
 */
export function shortId(value: unknown, maxLength = 12): string {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}...`;
}

/**
 * Normalize an array of ID strings, removing duplicates and empty values.
 */
export function normalizeIdList(values: unknown[]): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const value of values || []) {
    const item = String(value || "").trim();
    if (!item || seen.has(item)) {
      continue;
    }
    seen.add(item);
    normalized.push(item);
  }
  return normalized;
}

/**
 * Check if an error is a transient transport error (network, timeout, etc.).
 */
export function isTransientTransportError(error: unknown): boolean {
  const message = String(
    (error instanceof Error ? error.message : error) || "",
  );
  return /networkerror|failed to fetch|fetch resource|load failed|request timed out|请求超时/i.test(
    message,
  );
}

/**
 * Sleep for a given number of milliseconds.
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

// ── Status Helpers ──────────────────────────────────────────────

export type SessionStatus =
  | "idle"
  | "running"
  | "interrupting"
  | "error"
  | "failed"
  | "completed"
  | "in_progress";

/**
 * Check if a session status indicates the session is actively processing.
 */
export function isSessionBusyStatus(
  status: SessionStatus | string | undefined,
): boolean {
  return (
    status === "running" ||
    status === "interrupting" ||
    status === "in_progress"
  );
}

/**
 * Format a session status into a human-readable Chinese label.
 */
export function formatStatusText(
  status: SessionStatus | string | undefined,
): string {
  const map: Record<string, string> = {
    idle: "已就绪",
    running: "生成中",
    interrupting: "中断中",
    error: "异常",
    failed: "失败",
    completed: "已完成",
    in_progress: "处理中",
  };
  return map[status || ""] || status || "未知";
}

/**
 * Get the CSS class name for a session status badge.
 */
export function statusClass(
  status: SessionStatus | string | undefined,
): string {
  if (isSessionBusyStatus(status)) {
    return "status-running";
  }
  if (status === "error" || status === "failed") {
    return "status-error";
  }
  return "status-idle";
}

/**
 * Check if a session is currently compacting its memory.
 */
export function isSessionCompacting(session: {
  is_compacting?: boolean;
}): boolean {
  return Boolean(session?.is_compacting);
}
