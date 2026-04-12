export function byId(id) {
  return document.getElementById(id);
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function truncate(text, length = 72) {
  const value = String(text ?? "").trim();
  if (!value) {
    return "";
  }
  if (value.length <= length) {
    return value;
  }
  return `${value.slice(0, length - 1)}…`;
}

export function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function normalizeLines(value) {
  return String(value ?? "")
    .split(/\r?\n/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function sanitizeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.href);
    if (["http:", "https:", "mailto:"].includes(url.protocol)) {
      return url.toString();
    }
  } catch (_) {}
  return "";
}
