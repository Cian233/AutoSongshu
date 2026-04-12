// ── UserMessage ──────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderMessageMarkup() (user role branch)
//
// Renders a user message bubble with label, timestamp, and markdown content.

import { memo } from "react";
import { cn } from "../../lib/cn";
import type { Message } from "../../types/session";
import { messageText } from "../../lib/message-normalizer";
import { formatTime } from "../../lib/utils";
import { MarkdownContent } from "../markdown/MarkdownContent";
import { MessageActions } from "./MessageActions";

interface UserMessageProps {
  /** The message data. */
  message: Message;
  /** Whether this is the last assistant message (not applicable for user, but needed for MessageActions). */
  isLastAssistant?: boolean;
  /** The current session ID. */
  sessionId: string;
  /** Callback to fork the session. */
  onFork?: (sessionId: string, messageIndex: number) => Promise<void>;
}

function UserMessageInner({
  message,
  isLastAssistant = false,
  sessionId,
  onFork,
}: UserMessageProps) {
  const text = messageText(message);
  const messageIndex =
    message.order_index !== undefined ? message.order_index - 1 : -1;

  return (
    <article
      className={cn("message", "user")}
      data-message-id={message.id}
    >
      <div className="message-label-row">
        <span className="message-label">用户</span>
        <span className="message-time">
          {formatTime(message.updated_at || message.created_at)}
        </span>
        <MessageActions
          messageId={message.id}
          messageIndex={messageIndex}
          isLastAssistant={isLastAssistant}
          isPending={message.status === "in_progress"}
          isCompacted={Boolean(message.compacted)}
          onFork={onFork}
          sessionId={sessionId}
        />
      </div>
      <div className="message-bubble">
        <MarkdownContent content={text} />
        {message.error && (
          <div className="message-error">{message.error}</div>
        )}
      </div>
    </article>
  );
}

export const UserMessage = memo(UserMessageInner);
