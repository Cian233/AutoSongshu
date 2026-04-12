// ── SSE Event Types ─────────────────────────────────────────────

import type { SessionSummary, Message, Finding, Step, Progress } from "./session";

// ── SSE Event Names ─────────────────────────────────────────────

export type SSEEventType =
  | "connected"
  | "session.upsert"
  | "message.upsert"
  | "message.compacted"
  | "finding.upsert"
  | "step.upsert"
  | "progress.update"
  | "approval.request"
  | "approval.response";

// ── SSE Event Payloads ──────────────────────────────────────────

export interface SessionUpsertPayload {
  session: SessionSummary;
}

export interface MessageUpsertPayload {
  session_id: string;
  message: Message;
}

export interface MessageCompactedPayload {
  session_id: string;
  deleted_message_ids: string[];
}

export interface FindingUpsertPayload {
  session_id: string;
  findings: Finding[];
}

export interface StepUpsertPayload {
  session_id: string;
  step: Step;
}

export interface ProgressUpdatePayload {
  session_id: string;
  progress: Progress;
}

export interface ApprovalRequestPayload {
  request_id: string;
  session_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: "low" | "medium" | "high" | "critical";
  timeout_seconds: number;
}

export interface ApprovalResponsePayload {
  request_id: string;
  approved: boolean;
}

// ── SSE Event Map (event name -> payload) ────────────────────────

export interface SSEEventMap {
  connected: undefined;
  "session.upsert": SessionUpsertPayload;
  "message.upsert": MessageUpsertPayload;
  "message.compacted": MessageCompactedPayload;
  "finding.upsert": FindingUpsertPayload;
  "step.upsert": StepUpsertPayload;
  "progress.update": ProgressUpdatePayload;
  "approval.request": ApprovalRequestPayload;
  "approval.response": ApprovalResponsePayload;
}

// ── SSE Connection State ────────────────────────────────────────

export type SSEConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected";

// ── SSE Event Handler ───────────────────────────────────────────

export type SSEEventHandler<T = unknown> = (payload: T) => void;
