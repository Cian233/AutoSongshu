// ── MessageActions ───────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   wireForkButtons(), wireRegenerateButtons()
//
// Renders action buttons for messages: fork (branch from this point)
// and regenerate (re-generate the last assistant response).

import { memo, useCallback, useState } from "react";

interface MessageActionsProps {
  /** The message ID. */
  messageId: string;
  /** The message's order index (used for fork position). */
  messageIndex: number;
  /** Whether this is the last assistant message (enables regenerate). */
  isLastAssistant: boolean;
  /** Whether the message is still in progress. */
  isPending: boolean;
  /** Whether the message is compacted. */
  isCompacted: boolean;
  /** Callback to fork the session at this message. */
  onFork?: (sessionId: string, messageIndex: number) => Promise<void>;
  /** Callback to regenerate the last assistant response. */
  onRegenerate?: (sessionId: string) => Promise<void>;
  /** The current session ID. */
  sessionId: string;
}

function MessageActionsInner({
  messageId,
  messageIndex,
  isLastAssistant,
  isPending,
  isCompacted,
  onFork,
  onRegenerate,
  sessionId,
}: MessageActionsProps) {
  const [forkLoading, setForkLoading] = useState(false);
  const [regenerateLoading, setRegenerateLoading] = useState(false);

  const handleFork = useCallback(async () => {
    if (!onFork || forkLoading) return;
    setForkLoading(true);
    try {
      await onFork(sessionId, messageIndex);
    } catch (error) {
      console.error("Fork session failed:", error);
      alert(`分叉失败：${String((error as Error).message || error)}`);
    } finally {
      setForkLoading(false);
    }
  }, [onFork, sessionId, messageIndex, forkLoading]);

  const handleRegenerate = useCallback(async () => {
    if (!onRegenerate || regenerateLoading) return;
    setRegenerateLoading(true);
    try {
      await onRegenerate(sessionId);
    } catch (error) {
      console.error("Regenerate message failed:", error);
      alert(`重新生成失败：${String((error as Error).message || error)}`);
    } finally {
      setRegenerateLoading(false);
    }
  }, [onRegenerate, sessionId, regenerateLoading]);

  if (isPending || isCompacted) {
    return null;
  }

  return (
    <>
      <button
        className="message-fork-btn"
        type="button"
        onClick={handleFork}
        disabled={forkLoading}
        title="从此处分叉会话"
        data-fork-session
        data-message-index={String(messageIndex)}
        data-message-id={messageId}
      >
        {forkLoading ? "分叉中..." : "从此处分叉"}
      </button>
      {isLastAssistant && (
        <button
          className="message-regenerate-btn"
          type="button"
          onClick={handleRegenerate}
          disabled={regenerateLoading}
          title="重新生成回复"
          data-regenerate-message
          data-message-id={messageId}
        >
          {regenerateLoading ? "重新生成中..." : "重新生成"}
        </button>
      )}
    </>
  );
}

export const MessageActions = memo(MessageActionsInner);
