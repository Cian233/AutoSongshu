import { useMemo } from "react";
import { useSessionStore } from "../../stores/use-session-store";
import { useProjectStore } from "../../stores/use-project-store";
import { SessionItem } from "./SessionItem";
import { truncate, isSessionCompacting } from "../../lib/utils";

type GroupKey = "today" | "yesterday" | "week" | "month" | "earlier";

const GROUP_ORDER: GroupKey[] = ["today", "yesterday", "week", "month", "earlier"];

const GROUP_LABELS: Record<GroupKey, string> = {
  today: "今天",
  yesterday: "昨天",
  week: "7 天内",
  month: "30 天内",
  earlier: "更早",
};

function startOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function sessionGroupKey(timestamp?: string): GroupKey {
  const value = new Date(timestamp || "");
  if (Number.isNaN(value.getTime())) {
    return "earlier";
  }

  const today = startOfLocalDay(new Date());
  const target = startOfLocalDay(value);
  const diffDays = Math.floor((today.getTime() - target.getTime()) / 86400000);

  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return "week";
  if (diffDays < 30) return "month";
  return "earlier";
}

interface SessionGroup {
  key: GroupKey;
  label: string;
  items: import("../../types/session").SessionSummary[];
}

function groupSessionsByDate(
  sessions: import("../../types/session").SessionSummary[],
): SessionGroup[] {
  const buckets = new Map<GroupKey, import("../../types/session").SessionSummary[]>(
    GROUP_ORDER.map((key) => [key, []]),
  );

  for (const session of sessions) {
    const key = sessionGroupKey(session.updated_at || session.created_at);
    buckets.get(key)?.push(session);
  }

  return GROUP_ORDER.map((key) => ({
    key,
    label: GROUP_LABELS[key],
    items: buckets.get(key) || [],
  })).filter((group) => group.items.length > 0);
}

export function SessionList() {
  const sessions = useSessionStore((s) => s.sessions);
  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const selectSession = useSessionStore((s) => s.selectSession);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  const projectSessions = useMemo(() => {
    if (!selectedProjectId) return [];
    return sessions.filter(
      (session) => String(session.project_id || "") === String(selectedProjectId),
    );
  }, [sessions, selectedProjectId]);

  const groups = useMemo(() => groupSessionsByDate(projectSessions), [projectSessions]);

  if (!projectSessions.length) {
    return (
      <div className="text-[var(--muted)] text-[var(--font-size-sm)] text-center py-8 px-4">
        {selectedProjectId ? "当前项目暂无会话，发送第一条消息即可创建。" : "请先选择一个项目。"}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => (
        <section key={group.key} className="grid gap-2">
          <h3 className="m-0 px-2.5 text-[var(--muted)] text-[0.84rem] font-semibold">
            {group.label}
          </h3>

          <div className="grid gap-[3px]">
            {group.items.map((session) => {
              const isActive = String(session.id) === String(selectedSessionId);
              const title = truncate(session.title, 42) || String(session.id);

              return (
                <SessionItem
                  key={String(session.id)}
                  session={session}
                  isActive={isActive}
                  onClick={() => selectSession(String(session.id))}
                >
                  <SessionItem.Title>{title}</SessionItem.Title>
                  <SessionItem.Meta
                    status={session.status}
                    isCompacting={isSessionCompacting(session)}
                    isActive={isActive}
                  />
                </SessionItem>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
