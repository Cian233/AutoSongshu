// ── ChatThread ───────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderMessagesFast(), renderCompactedMessagesSection()
//
// Main message list container.  Renders:
//   1. CompactedMessages section (if any compacted messages exist)
//   2. All active (non-compacted) messages as UserMessage / AssistantMessage
//   3. Empty state when no session is selected or no messages exist
//
// Manages auto-scroll behavior via the useChatScroll hook.

import { memo, useEffect, useMemo } from "react";
import type { Message } from "../../types/session";
import { useChatScroll } from "../../hooks/use-chat-scroll";
import { CompactedMessages } from "./CompactedMessages";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { MarkdownContent } from "../markdown/MarkdownContent";
import { messageText } from "../../lib/message-normalizer";

interface ChatThreadProps {
  /** All messages for the current session (including compacted). */
  messages: Message[];
  /** The currently selected session ID. */
  sessionId: string | null;
  /** Callback to fork a session at a given message index. */
  onFork?: (sessionId: string, messageIndex: number) => Promise<void>;
  /** Callback to regenerate the last assistant response. */
  onRegenerate?: (sessionId: string) => Promise<void>;
}

function ChatThreadInner({
  messages,
  sessionId,
  onFork,
  onRegenerate,
}: ChatThreadProps) {
  const { scrollContainerRef, shouldStickToBottom, stickToBottom } =
    useChatScroll({ sessionId });

  // Separate compacted, system summary, and active messages
  const { compactedMessages, summaryMessage, activeMessages, lastAssistantId } = useMemo(() => {
    const compacted = messages.filter((msg) => msg.compacted);
    const system: Message[] = [];
    const active: Message[] = [];

    for (const msg of messages) {
      if (msg.compacted) continue;
      if ((msg.role as string) === "system") {
        system.push(msg);
      } else {
        active.push(msg);
      }
    }

    // Find the last assistant message ID (excluding compacted)
    let lastId = "";
    for (let i = active.length - 1; i >= 0; i--) {
      if (active[i].role === "assistant") {
        lastId = active[i].id || "";
        break;
      }
    }

    return {
      compactedMessages: compacted,
      summaryMessage: system[0] || null,
      activeMessages: active,
      lastAssistantId: lastId,
    };
  }, [messages]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (shouldStickToBottom) {
      // Double rAF to ensure DOM has painted after React commit
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          stickToBottom();
        });
      });
    }
  }, [messages.length, shouldStickToBottom, stickToBottom]);

  // Auto-scroll when the last message content changes (streaming)
  const lastMessage = activeMessages[activeMessages.length - 1];
  const lastMessageUpdatedAt = lastMessage?.updated_at || lastMessage?.created_at || "";
  useEffect(() => {
    if (shouldStickToBottom && lastMessage) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          stickToBottom();
        });
      });
    }
  }, [lastMessage?.render_signature, lastMessageUpdatedAt, shouldStickToBottom, stickToBottom]);

  // Empty state: no session selected
  if (!sessionId) {
    return (
      <div className="chat-scroll-container" ref={scrollContainerRef}>
        <div id="chat-thread" data-view="empty">
          <EmptyStage />
        </div>
      </div>
    );
  }

  // Empty state: session selected but no messages
  if (activeMessages.length === 0 && compactedMessages.length === 0) {
    return (
      <div className="chat-scroll-container" ref={scrollContainerRef}>
        <div id="chat-thread" data-view="empty">
          <EmptyStage />
        </div>
      </div>
    );
  }

  return (
    <div className="chat-scroll-container" ref={scrollContainerRef}>
      <div id="chat-thread" data-view="messages">
        {compactedMessages.length > 0 && (
          <CompactedMessages messages={compactedMessages} />
        )}
        {summaryMessage && (
          <ContextSummaryCard message={summaryMessage} />
        )}
        {activeMessages.map((message) => {
          if (message.role === "user") {
            return (
              <UserMessage
                key={message.id}
                message={message}
                sessionId={sessionId}
                onFork={onFork}
              />
            );
          }

          return (
            <AssistantMessage
              key={message.id}
              message={message}
              isLastAssistant={message.id === lastAssistantId}
              sessionId={sessionId}
              onFork={onFork}
              onRegenerate={onRegenerate}
            />
          );
        })}
      </div>
    </div>
  );
}

// ── Empty Stage ──────────────────────────────────────────────────

function EmptyStage() {
  return (
    <div className="empty-stage">
      <div className="hero-card">
        <div className="hero-layout">
          <div className="hero-main">
            <span className="hero-kicker">开始评估</span>
            <h3>把目标、线索和你想拿到的结果告诉我</h3>
            <p>
              从第一条消息开始，我会持续推进测试、记录关键结论，并把过程保留在同一条对话里，方便你随时接着做。
            </p>
            <div className="hero-grid">
              <div>
                <strong>先给出目标</strong>
                <span>
                  URL、题目链接、接口、附件，或你已经抓到的请求包都可以。
                </span>
              </div>
              <div>
                <strong>补充已知线索</strong>
                <span>
                  账号口令、提示、报错、已有 payload 或 flag
                  线索，都会让推进更快。
                </span>
              </div>
              <div>
                <strong>说明想要的结果</strong>
                <span>
                  例如继续打点、验证漏洞、复现利用、拿到
                  flag，或整理当前结论。
                </span>
              </div>
            </div>
          </div>
          <aside className="hero-side">
            <div className="hero-side-card">
              <span className="hero-side-kicker">推荐开场</span>
              <strong>可以直接这样发给我</strong>
              <pre className="hero-example">
                {`目标：https://target.example/login\n已知：普通用户账号、一道题目提示、上一轮的请求包\n任务：继续分析登录和会话流程，验证越权或想办法拿到 flag`}
              </pre>
            </div>
            <div className="hero-mini-grid">
              <div>
                <strong>过程可见</strong>
                <span>进度、工具结果和脚本变更会持续刷新。</span>
              </div>
              <div>
                <strong>上下文不断</strong>
                <span>
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

// ── Context Summary Divider ───────────────────────────────────────
// Renders the compaction summary (role="system") as a divider with
// the summary body always visible below it.

function ContextSummaryCard({ message }: { message: Message }) {
  const text = messageText(message);

  // Strip the boilerplate intro line
  const introMatch = text.match(
    /^这是一次从上一段对话中接续的会话[，,]原因是[^\n]+。\s*\n*/,
  );
  const body = introMatch ? text.slice(introMatch[0].length).trim() : text;

  if (!body) return null;

  return (
    <div className="context-summary-card" data-context-summary>
      <div className="context-summary-divider">
        <span className="context-summary-divider-line" />
        <span className="context-summary-divider-label">上下文摘要</span>
        <span className="context-summary-divider-line" />
      </div>
      <div className="context-summary-body">
        <MarkdownContent content={body} />
      </div>
    </div>
  );
}

export const ChatThread = memo(ChatThreadInner);
