// ── ChatPage ───────────────────────────────────────────────────
// Main chat page composing AppShell with all sub-components.

import { useCallback } from "react";
import { AppShell } from "../components/layout/AppShell";
import { Sidebar } from "../components/layout/Sidebar";
import { SessionList } from "../components/session/SessionList";
import { ChatHeader } from "../components/sidebar/ChatHeader";
import { MetricsCard } from "../components/sidebar/MetricsCard";
import { TokenUsageBar } from "../components/sidebar/TokenUsageBar";
import { StepsPanel } from "../components/sidebar/StepsPanel";
import { FindingsPanel } from "../components/sidebar/FindingsPanel";
import { ShortcutsPanel } from "../components/sidebar/ShortcutsPanel";
import { ChatThread } from "../components/chat/ChatThread";
import { Composer } from "../components/chat/Composer";
import { SearchPanel } from "../components/chat/SearchPanel";
import { EmptyStage } from "../components/chat/EmptyStage";
import { ApprovalModal } from "../components/approval/ApprovalModal";
import { useSessionStore } from "../stores/use-session-store";
import { useSearchStore } from "../stores/use-search-store";
import { useTheme } from "../hooks/use-theme";
import { useSSE } from "../hooks/use-sse";
import { useKeyboardShortcuts } from "../hooks/use-keyboard-shortcuts";
import { fetchJson } from "../lib/api";
import {
  sessionInterruptUrl,
  sessionForkUrl,
  sessionExportUrl,
} from "../lib/api-endpoints";

export default function ChatPage() {
  // ── Global hooks (must be mounted at root level) ──────────────
  useTheme();
  useSSE();
  useKeyboardShortcuts();

  const selectedSessionId = useSessionStore((s) => s.selectedSessionId);
  const sessionDetails = useSessionStore((s) => s.sessionDetails);
  const selectSession = useSessionStore((s) => s.selectSession);
  const searchOpen = useSearchStore((s) => s.searchOpen);

  const currentSession = selectedSessionId
    ? sessionDetails.get(selectedSessionId)
    : undefined;

  const messages = currentSession?.messages ?? [];

  // ── Callbacks ────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    selectSession(null);
  }, [selectSession]);

  const handlePause = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      await fetchJson(sessionInterruptUrl(selectedSessionId), {
        method: "POST",
      });
    } catch (err) {
      console.error("Failed to interrupt session:", err);
    }
  }, [selectedSessionId]);

  const handleDistill = useCallback(() => {
    // Distill (knowledge extraction) is not yet available as a backend API.
    // This is a placeholder for future implementation.
    console.log("Distill knowledge — not yet implemented");
  }, []);

  const handleExport = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      const blob = await fetchJson<Blob>(sessionExportUrl(selectedSessionId));
      // If the response is JSON, create a JSON file; otherwise try to download directly
      const url = URL.createObjectURL(
        blob instanceof Blob ? blob : new Blob([JSON.stringify(blob, null, 2)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `session-${selectedSessionId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to export session:", err);
    }
  }, [selectedSessionId]);

  const handleRefresh = useCallback(async () => {
    // Refresh is handled by SSE reconnection in useSSE hook.
    // This callback can trigger a manual re-sync if needed.
    console.log("Refresh — SSE will auto-reconnect");
  }, []);

  const handleFork = useCallback(
    async (sessionId: string, messageIndex: number) => {
      try {
        const result = await fetchJson<{ session_id: string }>(
          sessionForkUrl(sessionId),
          {
            method: "POST",
            body: JSON.stringify({ message_index: messageIndex }),
          },
        );
        // Select the new forked session
        selectSession(result.session_id);
      } catch (err) {
        console.error("Failed to fork session:", err);
      }
    },
    [selectSession],
  );

  const handleRegenerate = useCallback(
    async (_sessionId: string) => {
      // Regenerate is not yet available as a dedicated backend API.
      // The user can re-send the last message as a workaround.
      console.log("Regenerate — not yet implemented as a dedicated API");
    },
    [],
  );

  // ── Render ──────────────────────────────────────────────────

  return (
    <AppShell
      sidebar={
        <Sidebar
          sessionList={<SessionList />}
          onNewChat={handleNewChat}
        />
      }
      rightPanel={
        <div className="flex flex-col gap-4 min-h-0">
          <ChatHeader
            onPause={handlePause}
            onDistill={handleDistill}
            onExport={handleExport}
            onRefresh={handleRefresh}
          />
          <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-2 pt-2">
            <MetricsCard />
            <TokenUsageBar />
            <StepsPanel />
            <FindingsPanel />
            <ShortcutsPanel />
          </div>
        </div>
      }
    >
      {/* Chat Thread Area */}
      <div className="flex-1 min-h-0 flex flex-col relative">
        {selectedSessionId ? (
          <div className="max-w-[var(--content-width)] mx-auto px-6 py-4 flex-1 min-h-0 flex flex-col">
            <ChatThread
              messages={messages}
              sessionId={selectedSessionId}
              onFork={handleFork}
              onRegenerate={handleRegenerate}
            />
          </div>
        ) : (
          <div className="max-w-[var(--content-width)] mx-auto px-6 py-4 flex-1 min-h-0 flex flex-col">
            <EmptyStage />
          </div>
        )}

        {/* Search overlay */}
        {searchOpen && <SearchPanel />}
      </div>

      {/* Composer — always visible, creates a new session if none selected */}
      <div className="border-t border-[var(--line)] bg-[var(--panel)] p-4 shrink-0">
        <div className="max-w-[var(--content-width)] mx-auto">
          <Composer />
        </div>
      </div>

      {/* Approval modal (global, rendered once) */}
      <ApprovalModal />
    </AppShell>
  );
}
