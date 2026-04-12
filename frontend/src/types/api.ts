// ── API Request / Response Types ──────────────────────────────────

import type { SessionSummary } from "./session";
import type { KnowledgeBaseSummary } from "./knowledge";
import type { AuthorizationRecord } from "./authorization";

// ── Generic API Response ────────────────────────────────────────

export interface ApiResponse<T = unknown> {
  detail?: string;
  data?: T;
  [key: string]: unknown;
}

// ── Health ──────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
}

// ── Bootstrap ───────────────────────────────────────────────────

export interface BootstrapResponse {
  default_config_path: string;
  default_goal: string;
  default_authorization_draft: AuthorizationDraft | null;
  artifact_root: string;
  knowledge_bases: KnowledgeBaseSummary[];
  chat_sessions: SessionSummary[];
  authorizations: AuthorizationRecord[];
}

// ── Sessions ────────────────────────────────────────────────────

export interface ListSessionsResponse {
  sessions: SessionSummary[];
}

export interface CreateSessionRequest {
  config_path?: string;
  message: string;
  engagement_name?: string | null;
  authorization?: string | null;
  start_url?: string | null;
  allowed_hosts?: string[];
  allow_subdomains?: boolean;
  engagement_notes?: string | null;
  skill_dirs?: string[];
  knowledge_base_ids?: string[];
}

export interface SendMessageRequest {
  content: string;
}

export interface ForkSessionRequest {
  message_index?: number;
}

// ── Commands ────────────────────────────────────────────────────

export interface Command {
  name: string;
  description?: string;
  aliases?: string[];
}

export interface ListCommandsResponse {
  commands: Command[];
}

// ── Config ──────────────────────────────────────────────────────

export interface ConfigResponse {
  [key: string]: unknown;
}

export interface ReloadConfigRequest {
  config_path?: string;
}

// ── Approval ────────────────────────────────────────────────────

export interface ApprovalRequest {
  request_id: string;
  session_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: "low" | "medium" | "high" | "critical";
  timeout_seconds: number;
}

export interface ApprovalRespondRequest {
  approved: boolean;
  reason: string;
  remember_for_session: boolean;
  always_allow: boolean;
}

// ── Findings ────────────────────────────────────────────────────

export interface ListFindingsResponse {
  findings: import("./session").Finding[];
}

// ── Trajectory / Steps ──────────────────────────────────────────

export interface ListStepsResponse {
  steps: import("./session").Step[];
}

// ── Knowledge ───────────────────────────────────────────────────

export interface ListKnowledgeBasesResponse {
  items: KnowledgeBaseSummary[];
}

export interface CreateKnowledgeBaseRequest {
  name: string;
  description?: string | null;
}

export interface UpdateKnowledgeBaseRequest {
  name?: string;
  description?: string | null;
}

export interface CreateKnowledgeDocumentRequest {
  title: string;
  source?: string | null;
  source_type?: string;
  content?: string;
}

export interface HitTestingRequest {
  knowledge_base_id: string;
  query: string;
  limit?: number;
}

export interface HitTestingResponse {
  items: import("./knowledge").HitTestResult[];
}

// ── Authorization ───────────────────────────────────────────────

export interface AuthorizationDraft {
  name?: string;
  authorization?: string;
  start_url?: string;
  allowed_hosts?: string[];
  allow_subdomains?: boolean;
  notes?: string | null;
}

export interface ListAuthorizationsResponse {
  authorizations: AuthorizationRecord[];
}

// ── Fetch Options ───────────────────────────────────────────────

export interface FetchOptions extends Omit<RequestInit, "signal"> {
  timeoutMs?: number;
}

// ── API Endpoints Map ───────────────────────────────────────────

export const API_ENDPOINTS = {
  HEALTH: "/api/health",
  BOOTSTRAP: "/api/bootstrap",
  SESSIONS: "/api/chat/sessions",
  COMMANDS: "/api/commands",
  EVENTS: "/api/chat/events",
  AUTHORIZATIONS: "/api/authorizations",
  KNOWLEDGE_BASES: "/api/knowledge/bases",
  CONFIG: "/api/chat/config",
  CONFIG_RELOAD: "/api/chat/config/reload",
} as const;

export function sessionUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}`;
}

export function sessionMessagesUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/messages`;
}

export function sessionInterruptUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/interrupt`;
}

export function sessionForkUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/fork`;
}

export function sessionKnowledgeUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/knowledge-documents`;
}

export function sessionTrajectoryUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/trajectory`;
}

export function sessionFindingsUrl(id: string): string {
  return `/api/chat/sessions/${encodeURIComponent(id)}/findings`;
}

export function approvalRespondUrl(id: string): string {
  return `/api/chat/approvals/${encodeURIComponent(id)}/respond`;
}

export function knowledgeBaseUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}`;
}

export function knowledgeDocumentsUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}/documents`;
}

export function knowledgeDocumentUploadUrl(id: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(id)}/documents/upload`;
}

export function knowledgeDocumentUrl(baseId: string, docId: string): string {
  return `/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/${encodeURIComponent(docId)}`;
}
