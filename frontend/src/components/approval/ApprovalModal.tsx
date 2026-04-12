// ── Approval Modal ──────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js —
//   showApprovalModal(), hideApprovalModal(), respondToApproval(), wireApprovalButtons()
// And from /src/autosongshu_agent/web/templates/index.html —
//   approval panel HTML
//
// Displays a modal dialog when the server requests tool execution approval:
//   - Tool name and arguments display
//   - Risk level badge (low / medium / high / critical)
//   - Timeout countdown timer
//   - Approve / Deny buttons
//   - "Remember for this session" checkbox
//   - "Always allow" checkbox
//   - Listens for window CustomEvent "approval:request" dispatched by useSSE

import React, { useState, useEffect, useCallback, useRef } from "react";
import { Shield, ShieldAlert, ShieldCheck, Clock, X } from "lucide-react";
import { cn } from "../../lib/cn";
import { fetchJson } from "../../lib/api";
import { approvalRespondUrl, approvalCancelUrl } from "../../lib/api-endpoints";
import { getRiskLabel, getRiskClass } from "../../lib/commands";
import type { ApprovalRequestPayload } from "../../types/sse";

// ── Types ───────────────────────────────────────────────────────

interface ApprovalState extends ApprovalRequestPayload {
  /** Whether the approval response is in progress */
  responding: boolean;
}

// ── Risk level icon ─────────────────────────────────────────────

function RiskIcon({ level }: { level: string }) {
  const normalized = String(level || "medium").toLowerCase();
  if (normalized === "critical" || normalized === "high") {
    return <ShieldAlert className="h-4 w-4" />;
  }
  if (normalized === "low") {
    return <ShieldCheck className="h-4 w-4" />;
  }
  return <Shield className="h-4 w-4" />;
}

// ── Component ───────────────────────────────────────────────────

export const ApprovalModal: React.FC = () => {
  const [approval, setApproval] = useState<ApprovalState | null>(null);
  const [rememberForSession, setRememberForSession] = useState(false);
  const [alwaysAllow, setAlwaysAllow] = useState(false);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Listen for approval:request CustomEvent ───────────────────

  useEffect(() => {
    function handleApprovalRequest(event: Event) {
      const customEvent = event as CustomEvent<ApprovalRequestPayload>;
      const payload = customEvent.detail;
      if (!payload || !payload.request_id) return;

      setApproval({ ...payload, responding: false });
      setRememberForSession(false);
      setAlwaysAllow(false);
      setRemainingSeconds(payload.timeout_seconds || 300);
    }

    function handleApprovalResponse() {
      setApproval(null);
      setRemainingSeconds(0);
    }

    window.addEventListener("approval:request", handleApprovalRequest);
    window.addEventListener("approval:response", handleApprovalResponse);

    return () => {
      window.removeEventListener("approval:request", handleApprovalRequest);
      window.removeEventListener("approval:response", handleApprovalResponse);
    };
  }, []);

  // ── Timeout countdown ─────────────────────────────────────────

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (!approval || remainingSeconds <= 0) {
      return;
    }

    timerRef.current = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          // Auto-dismiss on timeout
          setApproval(null);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [approval, remainingSeconds]);

  // ── Respond to approval ───────────────────────────────────────

  const respond = useCallback(
    async (approved: boolean) => {
      if (!approval || approval.responding) return;

      setApproval((prev) => (prev ? { ...prev, responding: true } : null));

      try {
        await fetchJson(approvalRespondUrl(approval.request_id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            approved,
            reason: "",
            remember_for_session: rememberForSession,
            always_allow: alwaysAllow,
          }),
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : String(error);
        window.alert(`审批响应失败：${message}`);
        // Re-enable the buttons on error
        setApproval((prev) => (prev ? { ...prev, responding: false } : null));
        return;
      }

      setApproval(null);
    },
    [approval, rememberForSession, alwaysAllow],
  );

  // ── Cancel approval (backdrop click) ──────────────────────────

  const handleBackdropClick = useCallback(async () => {
    if (!approval) return;

    try {
      await fetchJson(approvalCancelUrl(approval.request_id), {
        method: "POST",
      }).catch(() => {
        // Ignore cancel errors
      });
    } catch {
      // Ignore
    }

    setApproval(null);
  }, [approval]);

  // ── Escape key ────────────────────────────────────────────────

  useEffect(() => {
    if (!approval) return;

    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") {
        handleBackdropClick();
      }
    }

    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
    };
  }, [approval, handleBackdropClick]);

  // ── Don't render if no approval is pending ────────────────────

  if (!approval) {
    return null;
  }

  const riskLevel = String(approval.risk_level || "medium").toLowerCase();
  const riskLabel = getRiskLabel(riskLevel);
  const riskClassSuffix = getRiskClass(riskLevel);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleBackdropClick}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        className={cn(
          "relative z-50 w-full max-w-lg rounded-xl border border-border",
          "bg-background shadow-2xl",
          "animate-in fade-in zoom-in-95 duration-200",
        )}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="approval-title"
        aria-describedby="approval-description"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                riskClassSuffix === "is-critical" &&
                  "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
                riskClassSuffix === "is-high" &&
                  "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
                riskClassSuffix === "is-medium" &&
                  "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
                riskClassSuffix === "is-low" &&
                  "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
              )}
            >
              <RiskIcon level={riskLevel} />
              {riskLabel}
            </div>
            <h3
              id="approval-title"
              className="text-sm font-semibold text-foreground"
            >
              工具执行审批
            </h3>
          </div>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground hover:text-foreground"
            onClick={handleBackdropClick}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4" id="approval-description">
          {/* Tool name */}
          <div className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              工具
            </span>
            <code className="block rounded-md bg-muted px-3 py-2 font-mono text-sm text-foreground">
              {approval.tool_name || "-"}
            </code>
          </div>

          {/* Arguments */}
          <div className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              参数
            </span>
            <pre className="max-h-48 overflow-auto rounded-md bg-muted px-3 py-2 font-mono text-xs text-foreground whitespace-pre-wrap break-words">
              {JSON.stringify(approval.arguments || {}, null, 2)}
            </pre>
          </div>

          {/* Meta info (visually hidden but accessible) */}
          <div className="sr-only">
            <span>请求 ID: {approval.request_id}</span>
            <span>会话 ID: {approval.session_id}</span>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-border px-6 py-4 space-y-4">
          {/* Checkboxes */}
          <div className="flex flex-col gap-2">
            <label className="inline-flex items-center gap-2 text-sm text-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={rememberForSession}
                onChange={(e) => setRememberForSession(e.target.checked)}
                className="rounded border-border"
              />
              <span>本次会话始终允许</span>
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={alwaysAllow}
                onChange={(e) => setAlwaysAllow(e.target.checked)}
                className="rounded border-border"
              />
              <span>永久始终允许</span>
            </label>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between">
            {/* Timeout countdown */}
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span
                className={cn(
                  "font-mono tabular-nums",
                  remainingSeconds <= 30 && "text-red-500 dark:text-red-400",
                  remainingSeconds <= 10 && "animate-pulse",
                )}
              >
                {remainingSeconds}s
              </span>
            </div>

            {/* Buttons */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                className={cn(
                  "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium",
                  "border border-border bg-background text-foreground",
                  "hover:bg-accent hover:text-accent-foreground",
                  "transition-colors duration-150",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                )}
                onClick={() => respond(false)}
                disabled={approval.responding}
              >
                拒绝
              </button>
              <button
                type="button"
                className={cn(
                  "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium",
                  "bg-primary text-primary-foreground",
                  "hover:bg-primary/90",
                  "transition-colors duration-150",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                )}
                onClick={() => respond(true)}
                disabled={approval.responding}
              >
                {approval.responding ? "处理中..." : "批准"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ApprovalModal;
