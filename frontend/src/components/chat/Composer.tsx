// ── Composer (Message Input) ────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js —
//   submitMessage()
// And from /src/autosongshu_agent/web/templates/index.html —
//   composer form, textarea, submit button
//
// Provides the message input area with:
//   - Multi-line textarea with auto-resize
//   - Send button (Cmd+Enter / Ctrl+Enter to send)
//   - Submitting state with loading indicator
//   - Slash-command autocomplete integration
//   - Attachment button placeholder (disabled)

import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  type KeyboardEvent,
  type FormEvent,
} from "react";
import { Send, Paperclip, Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";
import { useSessionStore } from "../../stores/use-session-store";
import {
  useCommandAutocomplete,
  getSelectedCommand,
  applyCommandToTextarea,
} from "../../hooks/use-command-autocomplete";
import { CommandSuggestions } from "./CommandSuggestions";
import { fetchJson } from "../../lib/api";
import { normalizeSessionDetail } from "../../lib/message-normalizer";
import {
  API_ENDPOINTS,
  sessionMessagesUrl,
} from "../../lib/api-endpoints";
import { useKnowledgeStore } from "../../stores/use-knowledge-store";
import { useAuthorizationStore } from "../../stores/use-authorization-store";
import { useProjectStore } from "../../stores/use-project-store";

// ── Props ───────────────────────────────────────────────────────

export interface ComposerProps {
  /** Placeholder text for the textarea */
  placeholder?: string;
  /** Additional CSS class names for the root element */
  className?: string;
  /** Called after a message is successfully sent */
  onMessageSent?: () => void;
}

// ── Component ───────────────────────────────────────────────────

export const Composer: React.FC<ComposerProps> = ({
  placeholder = "输入消息...",
  className,
  onMessageSent,
}) => {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const isSubmitting = useSessionStore((state) => state.isSubmitting);
  const setSubmitting = useSessionStore((state) => state.setSubmitting);
  const selectedSessionId = useSessionStore((state) => state.selectedSessionId);
  const selectedProjectId = useProjectStore((state) => state.selectedProjectId);
  const canSend = Boolean(selectedSessionId || selectedProjectId);
  const selectedKnowledgeBaseIds = useKnowledgeStore(
    (state) => state.selectedKnowledgeBaseIds,
  );
  const authorizationDraft = useAuthorizationStore(
    (state) => state.authorizationDraft,
  );

  // ── Command autocomplete ──────────────────────────────────────

  const autocomplete = useCommandAutocomplete();

  // ── Auto-resize textarea ──────────────────────────────────────

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
  }, [text]);

  // ── Submit handler ────────────────────────────────────────────

  const handleSubmit = useCallback(
    async (e?: FormEvent) => {
      e?.preventDefault();
      if (isSubmitting) return;

      const content = text.trim();
      if (!content) {
        textareaRef.current?.focus();
        return;
      }
      if (!selectedSessionId && !selectedProjectId) {
        window.alert("Please select a project first.");
        textareaRef.current?.focus();
        return;
      }

      setSubmitting(true);

      try {
        if (selectedSessionId) {
          // Send message to existing session
          const detail = await fetchJson<Record<string, unknown>>(
            sessionMessagesUrl(selectedSessionId),
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ content }),
            },
          );
          const normalizedDetail = normalizeSessionDetail(detail as Record<string, unknown>);
          useSessionStore.getState().setSessionDetail(
            selectedSessionId,
            normalizedDetail,
          );
          useSessionStore.getState().upsertSessionSummary(normalizedDetail);
        } else {
          // Create new session with message
          const defaultConfigPath =
            useSessionStore.getState().defaultConfigPath;
          const detail = await fetchJson<Record<string, unknown>>(
            API_ENDPOINTS.SESSIONS,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                config_path: defaultConfigPath,
                project_id: selectedProjectId,
                message: content,
                engagement_name: authorizationDraft.name || null,
                authorization: authorizationDraft.authorization || null,
                start_url: authorizationDraft.start_url || null,
                allowed_hosts: authorizationDraft.allowed_hosts || [],
                allow_subdomains: authorizationDraft.allow_subdomains ?? true,
                engagement_notes: authorizationDraft.notes || null,
                knowledge_base_ids: selectedKnowledgeBaseIds,
              }),
            },
          );

          const sessionId = String(
            (detail as Record<string, unknown>).id || "",
          );
          console.log("[Composer] Created session:", sessionId, detail);
          const normalizedDetail = normalizeSessionDetail(detail as Record<string, unknown>);
          console.log("[Composer] Normalized detail:", normalizedDetail);
          useSessionStore.getState().setSessionDetail(sessionId, normalizedDetail);
          console.log("[Composer] After setSessionDetail, selectedSessionId:", useSessionStore.getState().selectedSessionId);
          useSessionStore.getState().selectSession(sessionId);
          console.log("[Composer] After selectSession, selectedSessionId:", useSessionStore.getState().selectedSessionId);
          useSessionStore.getState().upsertSessionSummary(normalizedDetail);
          console.log("[Composer] After upsertSessionSummary, sessions count:", useSessionStore.getState().sessions.length);
          useSessionStore.getState().clearFindings();
          useSessionStore.getState().clearSteps();
        }

        setText("");
        onMessageSent?.();
      } catch (error) {
        let message = "未知错误";
        if (error instanceof Error) {
          message = error.message;
        } else if (typeof error === "object" && error !== null) {
          try {
            message = JSON.stringify(error);
          } catch {
            message = String(error);
          }
        } else {
          message = String(error);
        }
        window.alert(`发送失败：${message}`);
      } finally {
        setSubmitting(false);
        textareaRef.current?.focus();
      }
    },
    [
      text,
      isSubmitting,
      selectedSessionId,
      selectedProjectId,
      authorizationDraft,
      selectedKnowledgeBaseIds,
      setSubmitting,
      onMessageSent,
    ],
  );

  // ── Keyboard handler ──────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Ignore if composing (IME input)
      if (e.nativeEvent.isComposing) return;

      // ── Command autocomplete navigation ───────────────────────
      if (autocomplete.isOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          autocomplete.selectNext();
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          autocomplete.selectPrevious();
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          const selected = getSelectedCommand(
            autocomplete.suggestions,
            autocomplete.selectedIndex,
          );
          if (selected && textareaRef.current) {
            e.preventDefault();
            applyCommandToTextarea(textareaRef.current, selected.name);
            const textarea = textareaRef.current;
            setText(textarea.value);
            autocomplete.close();
            return;
          }
        }
        if (e.key === "Escape") {
          autocomplete.close();
          return;
        }
      }

      // ── Cmd/Ctrl + Enter: send message ────────────────────────
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmit();
        return;
      }

      // ── Enter (without Shift): send message ───────────────────
      // Note: This matches the original app.js behavior where
      // Enter sends (Shift+Enter for newline)
      if (e.key === "Enter" && !e.shiftKey && !autocomplete.isOpen) {
        e.preventDefault();
        handleSubmit();
        return;
      }
    },
    [autocomplete, handleSubmit],
  );

  // ── Input handler ─────────────────────────────────────────────

  const handleInput = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    setText(textarea.value);
    autocomplete.updateFilter(textarea.value, textarea.selectionStart || 0);
  }, [autocomplete]);

  // ── Command select handler ────────────────────────────────────

  const handleCommandSelect = useCallback(
    (cmd: { name: string }, _index: number) => {
      if (textareaRef.current) {
        applyCommandToTextarea(textareaRef.current, cmd.name);
        setText(textareaRef.current.value);
        autocomplete.close();
      }
    },
    [autocomplete],
  );

  // ── Click outside to close suggestions ────────────────────────

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        textareaRef.current &&
        !textareaRef.current.contains(target)
      ) {
        autocomplete.close();
      }
    }
    document.addEventListener("click", handleClickOutside);
    return () => {
      document.removeEventListener("click", handleClickOutside);
    };
  }, [autocomplete]);

  // ── Render ────────────────────────────────────────────────────

  return (
    <div className={cn("composer-shell", className)}>
      <form
        ref={formRef}
        onSubmit={handleSubmit}
        className="composer-form"
      >
        <div className="composer-input-container relative">
          <label className="composer-input-wrap">
            <span className="sr-only">输入消息</span>
            <textarea
              ref={textareaRef}
              id="goal"
              name="goal"
              rows={3}
              value={text}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              autoComplete="off"
              required
              disabled={isSubmitting}
              className={cn(
                "w-full resize-none rounded-lg border border-border bg-background",
                "px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                "min-h-[80px] max-h-[200px]",
              )}
            />
          </label>

          {/* Command suggestions dropdown */}
          {autocomplete.isOpen && (
            <CommandSuggestions
              suggestions={autocomplete.suggestions}
              selectedIndex={autocomplete.selectedIndex}
              onSelect={handleCommandSelect}
            />
          )}
        </div>

        <div className="composer-toolbar flex items-center justify-between px-2 py-1">
          <button
            className="composer-attach-button inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
            id="attachment-button"
            type="button"
            aria-label="附件功能预留"
            title="附件功能预留"
            disabled
          >
            <Paperclip className="h-4 w-4" />
          </button>

          <button
            className="composer-send-button inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
            id="submit-button"
            type="submit"
            aria-label={isSubmitting ? "发送中..." : "发送消息"}
            disabled={isSubmitting || !text.trim() || !canSend}
          >
            {isSubmitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
};

export default Composer;
