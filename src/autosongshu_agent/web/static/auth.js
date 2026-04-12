// ── API Authentication Token ──────────────────────────────────────
let _apiToken = "";

export function setApiToken(token) {
  _apiToken = token;
}

export function getApiToken() {
  return _apiToken;
}
