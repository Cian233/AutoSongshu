// ── API Endpoint Definitions ─────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js — API constant
//
// All endpoint paths are relative to the server root.
// Dynamic endpoints are exposed as functions that accept IDs and return
// the fully-qualified path with proper URI encoding.

// ── Static Endpoints ────────────────────────────────────────────

export const API_ENDPOINTS = {
  /** Health check */
  HEALTH: "/api/health",
  /** Bootstrap — initial application state */
  BOOTSTRAP: "/api/bootstrap",
  /** List / create chat sessions */
  SESSIONS: "/api/chat/sessions",
  /** List available slash-commands */
  COMMANDS: "/api/commands",
  /** SSE event stream */
  EVENTS: "/api/chat/events",
  /** List / create authorization records */
  AUTHORIZATIONS: "/api/authorizations",
  /** List / create knowledge bases */
  KNOWLEDGE_BASES: "/api/knowledge/bases",
  /** Get / set chat configuration */
  CONFIG: "/api/chat/config",
  /** Hot-reload chat configuration */
  CONFIG_RELOAD: "/api/chat/config/reload",
} as const;

// ── Dynamic Endpoint Builders ───────────────────────────────────

/** Get a single session detail */
export function sessionUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}`;
}

/** Send a message to an existing session */
export function sessionMessagesUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/messages`;
}

/** Interrupt a running session */
export function sessionInterruptUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/interrupt`;
}

/** Fork a session at a given message index */
export function sessionForkUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/fork`;
}

/** Export a session as downloadable file */
export function sessionExportUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/export`;
}

/** Get / create knowledge documents from a session */
export function sessionKnowledgeUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/knowledge-documents`;
}

/** Get session trajectory (steps) */
export function sessionTrajectoryUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/trajectory`;
}

/** Get session memory status */
export function sessionMemoryStatusUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/memory-status`;
}

/** Get session findings */
export function sessionFindingsUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/findings`;
}

/** Respond to an approval request */
export function approvalRespondUrl(id: string): string {
  return `/api/chat/approvals/${encodeURIComponent(id)}/respond`;
}

/** Cancel an approval request */
export function approvalCancelUrl(id: string): string {
  return `/api/chat/approvals/${encodeURIComponent(id)}/cancel`;
}

/** Get / update / delete a knowledge base */
export function knowledgeBaseUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}`;
}

/** List / create documents in a knowledge base */
export function knowledgeDocumentsUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}/documents`;
}

/** Upload a document to a knowledge base */
export function knowledgeDocumentUploadUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}/documents/upload`;
}

/** Get / delete a specific document in a knowledge base */
export function knowledgeDocumentUrl(baseId: string, docId: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/${encodeURIComponent(docId)}`;
}
