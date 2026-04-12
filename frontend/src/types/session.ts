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

// ── Session Summary (list item) ─────────────────────────────────

export interface SessionSummary {
  id: string;
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
