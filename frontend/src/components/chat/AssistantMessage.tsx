// ── AssistantMessage ─────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderMessageMarkup() (assistant role branch)
//
// Renders an assistant message bubble containing the AssistantTimeline
// (if the message has structured parts) or a plain markdown fallback.

import { memo, useMemo } from "react";
import { cn } from "../../lib/cn";
import type { Message } from "../../types/session";
import { messageText } from "../../lib/message-normalizer";
import { formatTime } from "../../lib/utils";
import { AssistantTimeline } from "./AssistantTimeline";
import { MarkdownContent } from "../markdown/MarkdownContent";
import { MessageActions } from "./MessageActions";

interface AssistantMessageProps {
  /** The message data. */
  message: Message;
  /** Whether this is the last assistant message (enables regenerate button). */
  isLastAssistant: boolean;
  /** The current session ID. */
  sessionId: string;
  /** Callback to fork the session. */
  onFork?: (sessionId: string, messageIndex: number) => Promise<void>;
  /** Callback to regenerate the last assistant response. */
  onRegenerate?: (sessionId: string) => Promise<void>;
}

function AssistantMessageInner({
  message,
  isLastAssistant,
  sessionId,
  onFork,
  onRegenerate,
}: AssistantMessageProps) {
  const text = messageText(message);
  const isPending = message.status === "in_progress";
  const isFailed = message.status === "failed";
  const isInterrupted = message.status === "interrupted";
  const messageIndex =
    message.order_index !== undefined ? message.order_index - 1 : -1;

  const bubbleText = text
    || (isPending
      ? "正在处理请求..."
      : isFailed
        ? "本轮回复失败。"
        : isInterrupted
          ? ""
          : "本轮没有可展示的文本输出。");

  // Check if the message has structured parts (timeline items)
  const hasStructuredParts = useMemo(() => {
    if (!message.content || !Array.isArray(message.content)) return false;
    return message.content.some(
      (part) =>
        part.type === "reasoning" ||
        part.type === "tool_call" ||
        part.type === "tool_result",
    );
  }, [message.content]);

  return (
    <article
      className={cn(
        "message",
        "assistant",
        isFailed && "message-failed",
      )}
      data-message-id={message.id}
    >
      <div className="message-label-row">
        <span className="message-label">助手</span>
        <span className="message-time">
          {formatTime(message.updated_at || message.created_at)}
        </span>
        <MessageActions
          messageId={message.id}
          messageIndex={messageIndex}
          isLastAssistant={isLastAssistant}
          isPending={isPending}
          isCompacted={Boolean(message.compacted)}
          onFork={onFork}
          onRegenerate={onRegenerate}
          sessionId={sessionId}
        />
      </div>
      <div className="message-bubble">
        {hasStructuredParts ? (
          <AssistantTimeline message={message} />
        ) : (
          <MarkdownContent content={bubbleText} isPending={isPending} />
        )}
        {message.error && (
          <div className="message-error">{message.error}</div>
        )}
      </div>
    </article>
  );
}

export const AssistantMessage = memo(AssistantMessageInner);
