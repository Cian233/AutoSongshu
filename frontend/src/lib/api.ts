// ── HTTP Fetch Utilities ─────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/state.js — fetchJson
//
// Provides typed wrappers around the native fetch API with:
//   - Automatic timeout via AbortController
//   - Automatic API token injection via Authorization header
//   - JSON response parsing with error handling

import { getApiToken } from "./auth";
import { API_ENDPOINTS } from "./api-endpoints";
import type { FetchOptions } from "../types/api";

// ── Constants ───────────────────────────────────────────────────

const DEFAULT_FETCH_TIMEOUT_MS = 12_000;

// ── fetchJson ───────────────────────────────────────────────────

/**
 * Low-level JSON fetch with timeout and auth token injection.
 *
 * @param url  - Full URL or absolute path to fetch.
 * @param options - Optional fetch options (method, headers, body, timeoutMs).
 * @returns Parsed JSON response body.
 * @throws Error on network failure, timeout, or non-OK HTTP status.
 */
export async function fetchJson<T = unknown>(
  url: string,
  options: FetchOptions = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, ...fetchOptions } = options;

  // Build AbortController for timeout
  const controller =
    typeof AbortController !== "undefined" &&
    !(fetchOptions as RequestInit).signal
      ? new AbortController()
      : null;

  const normalizedTimeoutMs = Number(timeoutMs);
  const timer =
    controller &&
    Number.isFinite(normalizedTimeoutMs) &&
    normalizedTimeoutMs > 0
      ? window.setTimeout(() => controller.abort(), normalizedTimeoutMs)
      : null;

  let response: Response;

  try {
    // Inject API token if available
    const apiToken = getApiToken();
    if (apiToken) {
      fetchOptions.headers = fetchOptions.headers || {};
      (fetchOptions.headers as Record<string, string>)["Authorization"] =
        `Bearer ${apiToken}`;
    }

    response = await fetch(
      url,
      controller
        ? { ...fetchOptions, signal: controller.signal }
        : fetchOptions,
    );
  } catch (error) {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
    if (controller?.signal?.aborted) {
      throw new Error("请求超时，请稍后重试。");
    }
    throw error;
  }

  if (timer !== null) {
    window.clearTimeout(timer);
  }

  // Parse response body
  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_) {
      payload = text;
    }
  }

  // Handle HTTP errors
  if (!response.ok) {
    let detail = "";
    if (typeof payload === "object" && payload !== null) {
      const p = payload as Record<string, unknown>;
      if ("detail" in p) {
        const d = p.detail;
        if (typeof d === "string") {
          detail = d;
        } else if (Array.isArray(d)) {
          // FastAPI 422 validation error: detail is an array of {loc, msg, type}
          detail = (d as Array<{ msg?: string }>)
            .map((e) => e.msg || "")
            .filter(Boolean)
            .join("; ");
        } else {
          detail = String(d);
        }
      }
    }
    if (!detail && typeof payload === "string" && payload) {
      detail = payload;
    }
    if (!detail) {
      detail = response.statusText;
    }
    throw new Error(detail || "请求失败");
  }

  return payload as T;
}

// ── fetchApi ────────────────────────────────────────────────────

/**
 * Convenience wrapper that prefixes the path with the API base.
 * Automatically injects the Authorization header.
 *
 * @param path    - API path (e.g. "/api/chat/sessions").
 * @param options - Optional fetch options.
 * @returns Parsed JSON response body.
 */
export async function fetchApi<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  return fetchJson<T>(path, options);
}

// ── Re-export API_ENDPOINTS for convenience ─────────────────────

export { API_ENDPOINTS };
