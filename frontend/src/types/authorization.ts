// ── Authorization Configuration Types ────────────────────────────

// ── Authorization Record (saved in library) ─────────────────────

export interface AuthorizationRecord {
  id: string;
  name: string;
  authorization: string;
  start_url: string;
  allowed_hosts?: string[];
  allow_subdomains?: boolean;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

// ── Authorization Draft (form state) ────────────────────────────

export interface AuthorizationDraft {
  name?: string;
  authorization?: string;
  start_url?: string;
  allowed_hosts?: string[];
  allow_subdomains?: boolean;
  notes?: string | null;
}

// ── Risk Level ──────────────────────────────────────────────────

export type RiskLevel = "low" | "medium" | "high" | "critical";

// ── Approval Request ────────────────────────────────────────────

export interface ApprovalRequest {
  request_id: string;
  session_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: RiskLevel;
  timeout_seconds: number;
}

// ── Approval Response ───────────────────────────────────────────

export interface ApprovalResponse {
  approved: boolean;
  reason?: string;
  remember_for_session?: boolean;
  always_allow?: boolean;
}
