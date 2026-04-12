// ── API Authentication Token Management ─────────────────────────
// Migrated from /src/autosongshu_agent/web/static/auth.js

let _apiToken = "";

/**
 * Set the API token used for authentication.
 */
export function setApiToken(token: string): void {
  _apiToken = token;
}

/**
 * Get the current API token.
 */
export function getApiToken(): string {
  return _apiToken;
}

/**
 * Clear the stored API token.
 */
export function clearApiToken(): void {
  _apiToken = "";
}

/**
 * Check if an API token has been set.
 */
export function hasApiToken(): boolean {
  return Boolean(_apiToken);
}
