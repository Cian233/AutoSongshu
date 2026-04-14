// ── Session, Message, and Related Types ──────────────────────────

// ── Session Status ──────────────────────────────────────────────

export type SessionStatus =
  | "idle"
  | "running"
  | "interrupting"
  | "interrupted"
  | "error"
  | "failed"
  | "completed"
  | "in_progress";

// ── Penetration Testing Phase ───────────────────────────────────

export type PentestPhase = "planning" | "recon" | "scanning" | "exploitation" | "reporting";

// ── Plan Step ───────────────────────────────────────────────────

export interface PlanStep {
  id: string;
  title: string;
  description: string;
  phase: PentestPhase;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  assigned_agent?: string;
  started_at?: string;
  completed_at?: string;
}

// ── Sub-Agent Info ──────────────────────────────────────────────

export type SubAgentType = "recon" | "scanner" | "exploit" | "report";

export interface SubAgentInfo {
  id: string;
  name: string;
  type: SubAgentType;
  status: "idle" | "running" | "completed" | "failed";
  current_task?: string;
  tools_available?: string[];
  started_at?: string;
  completed_at?: string;
}

// ── Error Recovery Stats ────────────────────────────────────────

export interface ErrorRecoveryAttempt {
  strategy: "model_switching" | "task_simplification" | "delegation" | "plan_mode_fallback";
  success: boolean;
  duration_ms: number;
  timestamp: string;
}

export interface ErrorRecoveryStats {
  total_attempts: number;
  total_successes: number;
  total_failures: number;
  last_error_type?: string;
  attempts: ErrorRecoveryAttempt[];
}

// ── Token Usage ─────────────────────────────────────────────────

export interface CostUsage {
  budget?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  event_count?: number;
  estimated_cost_usd?: number;
  cache_hit_ratio?: number;
}

// ── Project ─────────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  workspace_dir: string;
  artifacts_dir: string;
  isolation_mode: "session" | "user" | "project";
  created_at: string;
  updated_at: string;
  session_count?: number;
}

// ── Session Summary (list item) ─────────────────────────────────

export interface SessionSummary {
  id: string;
  project_id: string;  // Codex-style: sessions belong to projects
  title?: string;
  status?: SessionStatus;
  created_at?: string;
  updated_at?: string;
  is_compacting?: boolean;
  mode?: string;
  start_url?: string;
  knowledge_base_count?: number;
  token_usage?: CostUsage;
  allowed_hosts?: string[];
  knowledge_base_ids?: string[];
}

// ── Message Part Types ──────────────────────────────────────────

export interface TextPart {
  type: "input_text" | "output_text";
  text: string;
}

export interface ReasoningPart {
  type: "reasoning";
  text: string;
}

export interface ToolCallPart {
  type: "tool_call";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResultPart {
  type: "tool_result";
  tool_call_id: string;
  name: string;
  content: TextPart[];
}

export interface ImagePart {
  type: "image";
  url: string;
}

export type MessagePart = TextPart | ReasoningPart | ToolCallPart | ToolResultPart | ImagePart;

// ── Tool Call / Result (legacy aliases) ─────────────────────────

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResult {
  tool_call_id: string;
  name: string;
  content: TextPart[];
}

// ── Message ─────────────────────────────────────────────────────

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: MessagePart[];
  status?: SessionStatus;
  error?: string;
  order_index?: number;
  created_at?: string;
  updated_at?: string;
  compacted?: boolean;
  /** Internal render signature for change detection */
  render_signature?: string;
}

// ── Session Detail ──────────────────────────────────────────────

export interface SessionDetail extends SessionSummary {
  messages: Message[];
  // Trae Solo pattern fields
  current_phase?: PentestPhase;
  plan_steps?: PlanStep[];
  sub_agents?: SubAgentInfo[];
  error_recovery?: ErrorRecoveryStats;
  active_model?: string;
  historical_experiences_count?: number;
}

// ── Finding ─────────────────────────────────────────────────────

export type FindingSeverity = "critical" | "high" | "medium" | "low" | "info";

export interface Finding {
  id?: string;
  title: string;
  summary?: string;
  severity: FindingSeverity;
  session_id?: string;
  created_at?: string;
}

// ── Step (Trajectory) ───────────────────────────────────────────

export type StepState = "succeeded" | "failed" | "running" | "pending" | "skipped";

export interface Step {
  index: number;
  tool_name?: string;
  action?: string;
  observation?: string;
  state?: StepState;
  duration_ms?: number;
  token_usage?: {
    input_tokens?: number;
    output_tokens?: number;
  };
}

// ── Progress ────────────────────────────────────────────────────

export interface Progress {
  detail?: string;
  percent?: number;
  session_id?: string;
}

// ── Session Runtime Snapshot ────────────────────────────────────

export interface SessionRuntimeSnapshot {
  assistantStatus: string;
  latestOutputText: string;
  latestToolName: string;
  latestToolResultName: string;
  pendingToolNames: string[];
  pendingToolCount: number;
  completedToolCount: number;
  reasoningCount: number;
  updatedAt: string;
}

// ── Connection State ────────────────────────────────────────────

export type ConnectionState = "connected" | "reconnecting" | "connecting" | "disconnected";

export interface ConnectionStateInfo {
  label: string;
  className: string;
}
