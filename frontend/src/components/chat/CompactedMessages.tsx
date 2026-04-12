// ── CompactedMessages ────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderCompactedMessagesSection()
//
// Renders a collapsible section for compacted (summarized) messages
// that are no longer sent to the model but are kept for context.

import { memo, useState, useCallback } from "react";
import { cn } from "../../lib/cn";
import type { Message } from "../../types/session";
import { MarkdownContent } from "../markdown/MarkdownContent";
import { messageText } from "../../lib/message-normalizer";
import { formatTime } from "../../lib/utils";

interface CompactedMessagesProps {
  /** Array of compacted messages. */
  messages: Message[];
}

function CompactedMessagesInner({ messages }: CompactedMessagesProps) {
  const [expanded, setExpanded] = useState(true);

  const handleToggle = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  if (!messages || messages.length === 0) {
    return null;
  }

  const tokenCount = messages.reduce(
    (sum, msg) => sum + ((msg as unknown as Record<string, unknown>).token_count as number || 0),
    0,
  );
  const turnCount = messages.filter((msg) => msg.role === "user").length;

  return (
    <section className="compacted-messages-section" data-compacted-section>
      <header className="compacted-messages-header">
        <div className="compacted-messages-title">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            width={16}
            height={16}
          >
            <path d="M4 7V4h16v3M9 20h6M12 4v16" />
          </svg>
          <span>已压缩的历史消息</span>
        </div>
        <button
          className={cn("compacted-messages-toggle", !expanded && "collapsed")}
          type="button"
          onClick={handleToggle}
          aria-expanded={expanded}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            width={16}
            height={16}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
          <span>{expanded ? "收起" : "展开"}</span>
        </button>
      </header>
      <div className="compaction-stats">
        <span>
          共 <strong>{messages.length}</strong> 条消息
        </span>
        <span>
          <strong>{turnCount}</strong> 轮对话
        </span>
        <span>
          约 <strong>{tokenCount}</strong> tokens
        </span>
        <span className="compaction-hint">（已压缩，不会发送给模型）</span>
      </div>
      <div
        className={cn("compacted-messages-content", !expanded && "collapsed")}
        data-compacted-content
      >
        {messages.map((msg) => (
          <article
            key={msg.id}
            className={cn(
              "message",
              msg.role === "user" ? "user" : "assistant",
              "message-compacted",
            )}
            data-message-id={msg.id}
          >
            <div className="message-label-row">
              <span className="message-label">
                {msg.role === "user" ? "用户" : "助手"}
              </span>
              <span className="message-time">
                  {formatTime(msg.updated_at || msg.created_at)}
                </span>
              <span
                className="message-compacted-badge"
                title="此消息已压缩，不会发送给模型"
              >
                已压缩
              </span>
            </div>
            <div className="message-bubble">
              <MarkdownContent content={messageText(msg)} />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export const CompactedMessages = memo(CompactedMessagesInner);
