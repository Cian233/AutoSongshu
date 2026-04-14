// ── Error Recovery Panel ─────────────────────────────────────────
// Displays error recovery history and statistics.

import { cn } from "../../lib/cn";
import type { ErrorRecoveryStats, ErrorRecoveryAttempt } from "../../types/session";

interface ErrorRecoveryPanelProps {
  stats: ErrorRecoveryStats | null;
  className?: string;
}

const STRATEGY_LABELS: Record<ErrorRecoveryAttempt["strategy"], string> = {
  model_switching: "切换模型",
  task_simplification: "简化任务",
  delegation: "委派给专业 Agent",
  plan_mode_fallback: "退回规划模式",
};

export function ErrorRecoveryPanel({ stats, className }: ErrorRecoveryPanelProps) {
  if (!stats || stats.total_attempts === 0) {
    return (
      <div className={cn("text-sm text-muted-foreground", className)}>
        无错误恢复记录
      </div>
    );
  }

  const successRate = stats.total_attempts > 0
    ? Math.round((stats.total_successes / stats.total_attempts) * 100)
    : 0;

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {/* Stats summary */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border p-2">
          <div className="text-muted-foreground">总尝试次数</div>
          <div className="text-lg font-bold">{stats.total_attempts}</div>
        </div>
        <div className="rounded-md border p-2">
          <div className="text-muted-foreground">成功率</div>
          <div className={cn(
            "text-lg font-bold",
            successRate >= 50 ? "text-green-500" : "text-red-500",
          )}>
            {successRate}%
          </div>
        </div>
        <div className="rounded-md border p-2">
          <div className="text-muted-foreground">成功</div>
          <div className="text-lg font-bold text-green-500">{stats.total_successes}</div>
        </div>
        <div className="rounded-md border p-2">
          <div className="text-muted-foreground">失败</div>
          <div className="text-lg font-bold text-red-500">{stats.total_failures}</div>
        </div>
      </div>

      {/* Recovery attempts history */}
      <div className="flex flex-col gap-1">
        <div className="text-xs font-medium text-muted-foreground">
          恢复历史
        </div>
        <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
          {[...stats.attempts].reverse().map((attempt, index) => (
            <div
              key={index}
              className="flex items-center gap-2 rounded-md border p-2 text-xs"
            >
              <div
                className={cn(
                  "h-2 w-2 rounded-full",
                  attempt.success ? "bg-green-500" : "bg-red-500",
                )}
              />
              <div className="flex flex-1 flex-col">
                <span className="font-medium">
                  {STRATEGY_LABELS[attempt.strategy]}
                </span>
                <span className="text-muted-foreground">
                  {attempt.duration_ms > 0
                    ? `耗时 ${attempt.duration_ms}ms`
                    : "处理中..."}
                </span>
              </div>
              <span
                className={cn(
                  "font-medium",
                  attempt.success ? "text-green-500" : "text-red-500",
                )}
              >
                {attempt.success ? "成功" : "失败"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Last error type */}
      {stats.last_error_type && (
        <div className="text-xs text-muted-foreground">
          最后错误类型: <span className="font-medium text-foreground">{stats.last_error_type}</span>
        </div>
      )}
    </div>
  );
}
