// ── Sub-Agents Panel ─────────────────────────────────────────────
// Displays the status of all sub-agents for the selected session.

import { cn } from "../../lib/cn";
import type { SubAgentInfo, SubAgentType } from "../../types/session";

interface SubAgentsPanelProps {
  subAgents: SubAgentInfo[];
  className?: string;
}

const AGENT_TYPE_CONFIG: Record<SubAgentType, { label: string; icon: string; color: string }> = {
  recon: { label: "侦察", icon: "🔍", color: "text-blue-500" },
  scanner: { label: "扫描", icon: "🔎", color: "text-green-500" },
  exploit: { label: "利用", icon: "⚡", color: "text-red-500" },
  report: { label: "报告", icon: "📝", color: "text-purple-500" },
};

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  idle: { label: "空闲", color: "text-muted-foreground" },
  running: { label: "运行中", color: "text-blue-500" },
  completed: { label: "已完成", color: "text-green-500" },
  failed: { label: "失败", color: "text-red-500" },
};

export function SubAgentsPanel({ subAgents, className }: SubAgentsPanelProps) {
  if (subAgents.length === 0) {
    return (
      <div className={cn("text-sm text-muted-foreground", className)}>
        暂无子 Agent
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="text-xs font-medium text-muted-foreground">
        子 Agent ({subAgents.length})
      </div>
      <div className="flex flex-col gap-1">
        {subAgents.map((agent) => {
          const typeConfig = AGENT_TYPE_CONFIG[agent.type];
          const statusConfig = STATUS_CONFIG[agent.status];

          return (
            <div
              key={agent.id}
              className="flex items-center gap-2 rounded-md border p-2 text-xs"
            >
              <span className={cn("text-base", typeConfig.color)}>
                {typeConfig.icon}
              </span>
              <div className="flex flex-1 flex-col">
                <span className="font-medium">{agent.name}</span>
                <span className="text-muted-foreground">
                  {typeConfig.label} · {agent.current_task || "无任务"}
                </span>
              </div>
              <span className={cn("font-medium", statusConfig.color)}>
                {statusConfig.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
