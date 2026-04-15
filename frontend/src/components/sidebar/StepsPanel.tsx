import { useEffect, useMemo, useState } from "react";
import { Check, X, Loader2, Circle, Ban } from "lucide-react";
import { useSessionStore } from "../../stores/use-session-store";
import { PanelSection } from "./PanelSection";
import { cn } from "../../lib/cn";
import type { PlanStep, Step, StepState, PentestPhase } from "../../types/session";

const STEP_STATE_ICONS: Record<StepState, typeof Check> = {
  succeeded: Check,
  failed: X,
  running: Loader2,
  pending: Circle,
  skipped: Ban,
};

const STEP_STATE_COLORS: Record<StepState, string> = {
  succeeded: "text-[var(--success)]",
  failed: "text-[var(--danger)]",
  running: "text-[var(--accent)]",
  pending: "text-[var(--muted)]",
  skipped: "text-[var(--muted)]",
};

const PHASE_CONFIG: Record<PentestPhase, { label: string; color: string }> = {
  planning: { label: "规划", color: "bg-gray-500/20 text-gray-400" },
  recon: { label: "侦察", color: "bg-blue-500/20 text-blue-400" },
  scanning: { label: "扫描", color: "bg-green-500/20 text-green-400" },
  exploitation: { label: "利用", color: "bg-red-500/20 text-red-400" },
  reporting: { label: "报告", color: "bg-purple-500/20 text-purple-400" },
};

type TaskSource = "plan" | "subtask" | "semantic";

interface DisplayTask {
  key: string;
  title: string;
  detail?: string;
  state: StepState;
  phase: PentestPhase | null;
  durationMs: number;
  tokens: number;
  sourceCount: number;
  source: TaskSource;
  firstIndex: number;
}

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return `${str.slice(0, max)}...`;
}

function normalizeDetailText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function sumTokens(step: Pick<Step, "token_usage">): number {
  if (!step.token_usage) return 0;
  return (step.token_usage.input_tokens || 0) + (step.token_usage.output_tokens || 0);
}

function looksLikeJson(text: string): boolean {
  const trimmed = text.trim();
  return (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  );
}

function normalizeState(raw: string | undefined): StepState {
  if (raw === "succeeded" || raw === "failed" || raw === "running" || raw === "pending" || raw === "skipped") {
    return raw;
  }
  return "succeeded";
}

function mapPlanState(status: PlanStep["status"]): StepState {
  switch (status) {
    case "running":
      return "running";
    case "failed":
      return "failed";
    case "skipped":
      return "skipped";
    case "succeeded":
      return "succeeded";
    default:
      return "pending";
  }
}

function normalizeToolName(step: Step): string {
  const explicit = String(step.tool_name || "").trim();
  if (explicit) return explicit;
  const action = String(step.action || "").trim();
  const match = action.match(/^tool_call:(.+)$/i);
  if (match?.[1]) return match[1].trim();
  return action;
}

function extractPhaseFromText(value: string): PentestPhase | null {
  const lower = value.toLowerCase();
  if (
    lower.includes("http") ||
    lower.includes("browser") ||
    lower.includes("dns") ||
    lower.includes("recon")
  ) {
    return "recon";
  }
  if (
    lower.includes("sandbox") ||
    lower.includes("scan") ||
    lower.includes("nmap") ||
    lower.includes("dirsearch")
  ) {
    return "scanning";
  }
  if (
    lower.includes("exploit") ||
    lower.includes("payload") ||
    lower.includes("attack")
  ) {
    return "exploitation";
  }
  if (
    lower.includes("report") ||
    lower.includes("finding") ||
    lower.includes("export")
  ) {
    return "reporting";
  }
  if (
    lower.includes("plan") ||
    lower.includes("subtask") ||
    lower.includes("todo")
  ) {
    return "planning";
  }
  return null;
}

function parseSubtaskStateFromText(text: string): StepState | null {
  const lower = text.toLowerCase();
  if (lower.includes("failed")) return "failed";
  if (lower.includes("completed") || lower.includes("done") || lower.includes("succeeded")) return "succeeded";
  if (lower.includes("in_progress") || lower.includes("running")) return "running";
  if (lower.includes("pending")) return "pending";
  if (lower.includes("blocked")) return "skipped";
  return null;
}

function deriveSemanticTitle(step: Step): string {
  const tool = normalizeToolName(step).toLowerCase();
  if (tool.includes("create_plan") || tool.includes("subtask") || tool.includes("todo")) return "规划子任务";
  if (tool.includes("read") || tool.includes("list") || tool.includes("glob") || tool.includes("search")) return "检查文件与上下文";
  if (tool.includes("write") || tool.includes("edit") || tool.includes("patch")) return "修改实现";
  if (tool.includes("run") || tool.includes("bash") || tool.includes("shell") || tool.includes("test")) return "运行与验证";
  if (tool.includes("http") || tool.includes("browser") || tool.includes("web")) return "收集运行证据";
  if (tool.includes("finding") || tool.includes("report")) return "汇总发现";

  const action = String(step.action || "").replace(/^tool_call:/i, "").replace(/_/g, " ").trim();
  return action ? `执行：${action}` : "执行子任务";
}

function deriveSemanticDetail(step: Step): string | undefined {
  const observation = String(step.observation || "").trim();
  if (!observation || looksLikeJson(observation)) {
    return undefined;
  }

  const progressMatch = observation.match(/progress:\s*(.+)/i);
  if (progressMatch?.[1]) {
    return normalizeDetailText(progressMatch[1]);
  }

  return normalizeDetailText(observation);
}

function buildTasksFromPlanSteps(planSteps: PlanStep[]): DisplayTask[] {
  return planSteps.map((step, idx) => ({
    key: `plan:${step.id || idx}`,
    title: step.title || `子任务 ${idx + 1}`,
    detail: step.description ? normalizeDetailText(step.description) : undefined,
    state: mapPlanState(step.status),
    phase: step.phase || null,
    durationMs: 0,
    tokens: 0,
    sourceCount: 1,
    source: "plan",
    firstIndex: idx,
  }));
}

function buildTasksFromSubtaskEvents(steps: Step[]): DisplayTask[] {
  const tasksByKey = new Map<string, DisplayTask>();

  const sorted = [...steps].sort((a, b) => Number(a.index || 0) - Number(b.index || 0));
  for (const step of sorted) {
    const tool = normalizeToolName(step).toLowerCase();
    const observation = String(step.observation || "").trim();
    const index = Number(step.index || 0);
    const stepTokens = sumTokens(step);
    const stepDuration = Number(step.duration_ms || 0);

    let key = "";
    let title = "";
    let detail = "";
    let state: StepState = normalizeState(step.state);

    if (tool === "create_plan") {
      const planName = observation.match(/plan\s+['\"]([^'\"]+)['\"]/i)?.[1]?.trim();
      key = "plan:create";
      title = planName ? `创建计划：${planName}` : "创建执行计划";
      detail = observation ? normalizeDetailText(observation) : "";
      state = "succeeded";
    } else if (tool === "update_subtask_state" || tool === "finish_subtask") {
      const named = observation.match(/named\s+['\"]([^'\"]+)['\"]/i)?.[1]?.trim() || "子任务";
      const subtaskIndex = observation.match(/index\s+(\d+)/i)?.[1];
      key = subtaskIndex ? `subtask:${subtaskIndex}` : `subtask:${named.toLowerCase()}`;
      title = named;
      detail = observation ? normalizeDetailText(observation) : "";
      state = tool === "finish_subtask" ? "succeeded" : (parseSubtaskStateFromText(observation) || state);
    } else if (tool === "update_progress") {
      const progressLine = observation.match(/progress:\s*(.+)/i)?.[1]?.trim();
      if (!progressLine) {
        continue;
      }
      key = `progress:${index}`;
      title = progressLine;
      detail = normalizeDetailText(observation.replace(/progress:\s*.+/i, "").trim());
      state = parseSubtaskStateFromText(observation) || "running";
    } else {
      continue;
    }

    const existing = tasksByKey.get(key);
    if (!existing) {
      tasksByKey.set(key, {
        key,
        title,
        detail: detail || undefined,
        state,
        phase: extractPhaseFromText(`${tool} ${title}`),
        durationMs: stepDuration,
        tokens: stepTokens,
        sourceCount: 1,
        source: "subtask",
        firstIndex: index,
      });
      continue;
    }

    existing.title = title || existing.title;
    existing.detail = detail || existing.detail;
    existing.state = state;
    existing.durationMs += stepDuration;
    existing.tokens += stepTokens;
    existing.sourceCount += 1;
  }

  return Array.from(tasksByKey.values()).sort((a, b) => a.firstIndex - b.firstIndex);
}

function buildSemanticTasks(steps: Step[]): DisplayTask[] {
  const sorted = [...steps].sort((a, b) => Number(a.index || 0) - Number(b.index || 0));
  const tasks: DisplayTask[] = [];

  for (const step of sorted) {
    const title = deriveSemanticTitle(step);
    const detail = deriveSemanticDetail(step);
    const state = normalizeState(step.state);
    const phase = extractPhaseFromText(`${normalizeToolName(step)} ${title}`);
    const duration = Number(step.duration_ms || 0);
    const tokens = sumTokens(step);
    const firstIndex = Number(step.index || 0);

    const last = tasks[tasks.length - 1];
    if (last && last.title === title && last.state === state && last.phase === phase) {
      last.durationMs += duration;
      last.tokens += tokens;
      last.sourceCount += 1;
      if (detail) {
        last.detail = detail;
      }
      continue;
    }

    tasks.push({
      key: `semantic:${firstIndex}`,
      title,
      detail,
      state,
      phase,
      durationMs: duration,
      tokens,
      sourceCount: 1,
      source: "semantic",
      firstIndex,
    });
  }

  return tasks;
}

function buildDisplayTasks(planSteps: PlanStep[], steps: Step[]): DisplayTask[] {
  if (planSteps.length > 0) {
    return buildTasksFromPlanSteps(planSteps);
  }

  const fromSubtasks = buildTasksFromSubtaskEvents(steps);
  if (fromSubtasks.length > 0) {
    return fromSubtasks;
  }

  return buildSemanticTasks(steps);
}

function PhaseBadge({ phase }: { phase: PentestPhase }) {
  const config = PHASE_CONFIG[phase];
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", config.color)}>
      {config.label}
    </span>
  );
}

interface StepItemProps {
  task: DisplayTask;
  index: number;
  compactDetail?: boolean;
  onClick?: () => void;
}

function StepItem({ task, index, compactDetail = true, onClick }: StepItemProps) {
  const Icon = STEP_STATE_ICONS[task.state] || Circle;
  const colorClass = STEP_STATE_COLORS[task.state] || "text-[var(--muted)]";
  const duration = task.durationMs > 0 ? formatDuration(task.durationMs) : "";
  const sourceCount = task.sourceCount > 1 ? `x${task.sourceCount}` : "";
  const detailText = task.detail
    ? (compactDetail ? truncate(task.detail, 96) : task.detail)
    : "";

  return (
    <div
      className={cn(
        "flex flex-col gap-1 px-2.5 py-2",
        "rounded-[var(--radius-sm)]",
        "transition-colors duration-100",
        onClick ? "cursor-pointer hover:bg-[var(--sidebar-hover)]" : "",
      )}
      onClick={onClick}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="flex-shrink-0 w-5 text-center text-[var(--font-size-xs)] text-[var(--muted)] font-[var(--font-mono)]">
          {index + 1}
        </span>

        <span className={cn("flex-shrink-0", colorClass)}>
          <Icon className={cn("w-3.5 h-3.5", task.state === "running" && "animate-spin")} />
        </span>

        <span
          className={cn(
            "flex-1 min-w-0 truncate",
            "text-[var(--font-size-sm)] text-[var(--text)] font-[var(--font-weight-medium)]",
          )}
          title={task.title}
        >
          {task.title}
        </span>

        {task.phase && <PhaseBadge phase={task.phase} />}

        <span className="flex-shrink-0 text-[var(--font-size-xs)] text-[var(--muted)] whitespace-nowrap">
          {sourceCount}
          {sourceCount && duration ? " | " : ""}
          {duration}
          {(sourceCount || duration) && task.tokens > 0 ? " | " : ""}
          {task.tokens > 0 ? `${task.tokens} tok` : ""}
        </span>
      </div>

      {detailText && (
        <p
          className={cn(
            "m-0 pl-[30px]",
            "text-[var(--font-size-xs)] text-[var(--muted)]",
            "leading-[var(--line-height-normal)]",
            !compactDetail && "whitespace-pre-wrap break-words",
          )}
        >
          {detailText}
        </p>
      )}
    </div>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <span className="text-[var(--font-size-sm)] font-[var(--font-weight-medium)] text-[var(--text)]">
        {title}
      </span>
      <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
        {description}
      </span>
    </div>
  );
}

interface TaskListModalProps {
  open: boolean;
  tasks: DisplayTask[];
  onClose: () => void;
}

function TaskListModal({ open, tasks, onClose }: TaskListModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" aria-hidden="true" />
      <div
        className="relative z-10 w-full max-w-4xl max-h-[85vh] overflow-hidden rounded-xl border border-[var(--line-strong)] bg-[var(--panel)] shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tasks-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3">
          <div className="flex items-center gap-2">
            <h3 id="tasks-modal-title" className="text-sm font-semibold text-[var(--text)]">完整任务列表</h3>
            <span className="rounded-full bg-[var(--bg-soft)] px-2 py-0.5 text-xs text-[var(--muted)]">{tasks.length}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[var(--line)] px-2 py-1 text-xs text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]"
          >
            关闭
          </button>
        </div>

        <div className="overflow-y-auto px-3 py-2 max-h-[calc(85vh-56px)]">
          {tasks.length === 0 ? (
            <EmptyState title="暂无任务" description="当前会话还没有可展示的任务。" />
          ) : (
            <div className="flex flex-col gap-0.5">
              {tasks.map((task, idx) => (
                <StepItem
                  key={`modal:${task.key}`}
                  task={task}
                  index={idx}
                  compactDetail={false}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface StepsPanelProps {
  className?: string;
}

export function StepsPanel({ className }: StepsPanelProps) {
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);
  const steps = useSessionStore((s) => s.steps);
  const currentPhase = useSessionStore((s) => s.currentPhase);
  const subAgents = useSessionStore((s) => s.subAgents);

  const [taskModalOpen, setTaskModalOpen] = useState(false);

  const planSteps = selectedSessionId
    ? (sessionDetails.get(selectedSessionId)?.plan_steps || [])
    : [];

  const tasks = useMemo(
    () => buildDisplayTasks(planSteps, steps),
    [planSteps, steps],
  );

  const hasSession = Boolean(selectedSessionId);

  useEffect(() => {
    setTaskModalOpen(false);
  }, [selectedSessionId]);

  useEffect(() => {
    if (!taskModalOpen) {
      return;
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setTaskModalOpen(false);
      }
    }

    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
    };
  }, [taskModalOpen]);

  const openTaskModal = () => {
    if (!tasks.length) {
      return;
    }
    setTaskModalOpen(true);
  };

  return (
    <>
      <PanelSection defaultOpen={true} className={className}>
        <PanelSection.Header title="执行子任务" count={tasks.length}>
          <button
            type="button"
            className={cn(
              "rounded-md border border-[var(--line)] px-2 py-0.5 text-[11px]",
              "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            disabled={!hasSession || tasks.length === 0}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              openTaskModal();
            }}
          >
            查看全部
          </button>
        </PanelSection.Header>
        <PanelSection.Content>
          {!hasSession && (
            <EmptyState
              title="请选择会话"
              description="请先在左侧会话列表中选择一个会话。"
            />
          )}

          {hasSession && tasks.length === 0 && (
            <EmptyState
              title="暂无子任务"
              description="Agent 执行过程中会在这里显示子任务进度。"
            />
          )}

          {hasSession && tasks.length > 0 && (
            <div className="flex flex-col gap-2">
              {currentPhase && (
                <div className="flex items-center gap-2 px-2 py-1 rounded-md bg-[var(--sidebar-hover)]">
                  <span className="text-xs text-[var(--muted)]">当前阶段：</span>
                  <PhaseBadge phase={currentPhase} />
                  {subAgents.length > 0 && (
                    <span className="text-xs text-[var(--muted)] ml-auto">
                      {subAgents.length} 个子 Agent
                    </span>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-0.5">
                {tasks.map((task, idx) => (
                  <StepItem
                    key={task.key}
                    task={task}
                    index={idx}
                    onClick={openTaskModal}
                  />
                ))}
              </div>
            </div>
          )}
        </PanelSection.Content>
      </PanelSection>

      <TaskListModal
        open={taskModalOpen}
        tasks={tasks}
        onClose={() => setTaskModalOpen(false)}
      />
    </>
  );
}
