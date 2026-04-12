// ── EmptyStage ─────────────────────────────────────────────────
// Empty state welcome page, migrated from emptyStageMarkup().
// Displayed when no session is selected or chat thread is empty.

import { cn } from "../../lib/cn";

// ── Component ──────────────────────────────────────────────────

interface EmptyStageProps {
  className?: string;
}

export function EmptyStage({ className }: EmptyStageProps) {
  return (
    <div className={cn("grid", className)}>
      <div
        className={cn(
          "p-7 rounded-[var(--radius-xl)]",
          "bg-[var(--bg)] border border-[var(--line)]",
          "shadow-[var(--shadow-sm)]",
        )}
      >
        <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(300px,0.92fr)] gap-[18px] items-stretch max-lg:grid-cols-1">
          {/* ── Hero Main ── */}
          <div className="min-w-0">
            <span className="text-[var(--font-size-xs)] font-[var(--font-weight-semibold)] text-[var(--accent)] uppercase tracking-wider">
              开始评估
            </span>
            <h3 className="mt-2 mb-2 text-[var(--text)] text-[var(--font-size-xl)] font-[var(--font-weight-bold)] leading-[var(--line-height-tight)]">
              把目标、线索和你想拿到的结果告诉我
            </h3>
            <p className="mb-4 text-[var(--font-size-md)] text-[var(--text-secondary)] leading-[var(--line-height-relaxed)]">
              从第一条消息开始，我会持续推进测试、记录关键结论，并把过程保留在同一条对话里，方便你随时接着做。
            </p>

            <div className="grid grid-cols-1 gap-3 max-lg:grid-cols-1">
              <div>
                <strong className="block text-[var(--text)] text-[var(--font-size-md)] font-[var(--font-weight-semibold)] mb-0.5">
                  先给出目标
                </strong>
                <span className="text-[var(--font-size-sm)] text-[var(--muted)]">
                  URL、题目链接、接口、附件，或你已经抓到的请求包都可以。
                </span>
              </div>
              <div>
                <strong className="block text-[var(--text)] text-[var(--font-size-md)] font-[var(--font-weight-semibold)] mb-0.5">
                  补充已知线索
                </strong>
                <span className="text-[var(--font-size-sm)] text-[var(--muted)]">
                  账号口令、提示、报错、已有 payload 或 flag 线索，都会让推进更快。
                </span>
              </div>
              <div>
                <strong className="block text-[var(--text)] text-[var(--font-size-md)] font-[var(--font-weight-semibold)] mb-0.5">
                  说明想要的结果
                </strong>
                <span className="text-[var(--font-size-sm)] text-[var(--muted)]">
                  例如继续打点、验证漏洞、复现利用、拿到 flag，或整理当前结论。
                </span>
              </div>
            </div>
          </div>

          {/* ── Hero Side ── */}
          <aside className="min-w-0 grid gap-3.5 content-start">
            {/* Example Card */}
            <div
              className={cn(
                "p-4 rounded-[var(--radius-lg)]",
                "bg-[var(--panel-strong)] border border-[var(--line)]",
              )}
            >
              <span className="text-[var(--font-size-xs)] font-[var(--font-weight-semibold)] text-[var(--accent)] uppercase tracking-wider">
                推荐开场
              </span>
              <strong className="block text-[var(--text)] text-[var(--font-size-md)] font-[var(--font-weight-semibold)] mt-1 mb-2">
                可以直接这样发给我
              </strong>
              <pre
                className={cn(
                  "whitespace-pre-wrap text-[var(--font-size-sm)] text-[var(--text-secondary)]",
                  "font-[var(--font-mono)] leading-[var(--line-height-relaxed)]",
                  "p-3 rounded-[var(--radius-md)] bg-[var(--bg-soft)]",
                  "m-0 border-none",
                )}
              >
{`目标：https://target.example/login
已知：普通用户账号、一道题目提示、上一轮的请求包
任务：继续分析登录和会话流程，验证越权或想办法拿到 flag`}
              </pre>
            </div>

            {/* Mini Grid */}
            <div className="grid grid-cols-2 gap-3 max-lg:grid-cols-1">
              <div>
                <strong className="block text-[var(--text)] text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] mb-0.5">
                  过程可见
                </strong>
                <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
                  进度、工具结果和脚本变更会持续刷新。
                </span>
              </div>
              <div>
                <strong className="block text-[var(--text)] text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] mb-0.5">
                  上下文不断
                </strong>
                <span className="text-[var(--font-size-xs)] text-[var(--muted)]">
                  关键线索和阶段结论会保留，第二轮也能接着做。
                </span>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
