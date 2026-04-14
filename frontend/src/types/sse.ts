// ── SSE Event Types ─────────────────────────────────────────────

import type { SessionSummary, Message, Finding, Step, Progress, PlanStep } from "./session";

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
  | "approval.response"
  // Sub-Agent lifecycle events
  | "sub_agent.created"
  | "sub_agent.completed"
  | "sub_agent.failed"
  | "sub_agent.progress"
  // Error recovery events
  | "error_recovery.attempt"
  | "error_recovery.result"
  // Phase and plan events
  | "phase.changed"
  | "plan.updated"
  // Model routing events
  | "model.routed"
  | "model.performance"
  // Long-term memory events
  | "memory.historical_loaded"
  | "memory.experience_stored";

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

// ── Sub-Agent Lifecycle Event Payloads ──────────────────────────

export interface SubAgentCreatedPayload {
  session_id: string;
  agent_id: string;
  agent_name: string;
  agent_type: "recon" | "scanner" | "exploit" | "report";
  task?: string;
  tools_available?: string[];
  timestamp: string;
}

export interface SubAgentCompletedPayload {
  session_id: string;
  agent_id: string;
  agent_name: string;
  agent_type: "recon" | "scanner" | "exploit" | "report";
  result_summary?: string;
  timestamp: string;
}

export interface SubAgentFailedPayload {
  session_id: string;
  agent_id: string;
  agent_name: string;
  agent_type: "recon" | "scanner" | "exploit" | "report";
  error_message: string;
  timestamp: string;
}

export interface SubAgentProgressPayload {
  session_id: string;
  agent_id: string;
  agent_name: string;
  progress: number;
  current_task?: string;
  timestamp: string;
}

// ── Error Recovery Event Payloads ───────────────────────────────

export interface ErrorRecoveryAttemptPayload {
  session_id: string;
  strategy: "model_switching" | "task_simplification" | "delegation" | "plan_mode_fallback";
  attempt_count: number;
  max_attempts: number;
  error_type: string;
  timestamp: string;
}

export interface ErrorRecoveryResultPayload {
  session_id: string;
  strategy: "model_switching" | "task_simplification" | "delegation" | "plan_mode_fallback";
  success: boolean;
  duration_ms: number;
  timestamp: string;
}

// ── Phase and Plan Event Payloads ───────────────────────────────

export interface PhaseChangedPayload {
  session_id: string;
  from_phase: string | null;
  to_phase: "recon" | "scanning" | "exploitation" | "reporting" | "planning";
  timestamp: string;
}

export interface PlanUpdatedPayload {
  session_id: string;
  plan_steps: PlanStep[];
  timestamp: string;
}

// ── Model Routing Event Payloads ────────────────────────────────

export interface ModelRoutedPayload {
  session_id: string;
  from_model: string;
  to_model: string;
  reason: string;
  timestamp: string;
}

export interface ModelPerformancePayload {
  session_id: string;
  model_name: string;
  success_rate: number;
  avg_response_time_ms: number;
  total_requests: number;
  timestamp: string;
}

// ── Long-Term Memory Event Payloads ─────────────────────────────

export interface MemoryHistoricalLoadedPayload {
  session_id: string;
  experiences_count: number;
  experiences: Array<{
    session_id: string;
    target_url: string;
    findings_count: number;
  }>;
  timestamp: string;
}

export interface MemoryExperienceStoredPayload {
  session_id: string;
  experience_id: string;
  target_url: string;
  timestamp: string;
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
  // Sub-Agent lifecycle events
  "sub_agent.created": SubAgentCreatedPayload;
  "sub_agent.completed": SubAgentCompletedPayload;
  "sub_agent.failed": SubAgentFailedPayload;
  "sub_agent.progress": SubAgentProgressPayload;
  // Error recovery events
  "error_recovery.attempt": ErrorRecoveryAttemptPayload;
  "error_recovery.result": ErrorRecoveryResultPayload;
  // Phase and plan events
  "phase.changed": PhaseChangedPayload;
  "plan.updated": PlanUpdatedPayload;
  // Model routing events
  "model.routed": ModelRoutedPayload;
  "model.performance": ModelPerformancePayload;
  // Long-term memory events
  "memory.historical_loaded": MemoryHistoricalLoadedPayload;
  "memory.experience_stored": MemoryExperienceStoredPayload;
}

// ── SSE Connection State ────────────────────────────────────────

export type SSEConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected";

// ── SSE Event Handler ───────────────────────────────────────────

export type SSEEventHandler<T = unknown> = (payload: T) => void;
