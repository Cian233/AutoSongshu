// ── SSE Connection Hook ─────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/api.js — connectRealtime()
//
// Manages the SSE (Server-Sent Events) connection lifecycle:
//   - Creates and manages the EventSource instance
//   - Listens for all SSE event types and dispatches to stores
//   - Handles automatic reconnection with exponential backoff
//   - Triggers data resync after reconnection

import { useEffect, useRef, useCallback } from "react";
import { useConnectionStore } from "../stores/use-connection-store";
import { useSessionStore } from "../stores/use-session-store";
import { API_ENDPOINTS } from "../lib/api-endpoints";
import { getApiToken } from "../lib/auth";
import { fetchJson } from "../lib/api";
import { isTransientTransportError, sleep } from "../lib/utils";
import type {
  SessionUpsertPayload,
  MessageUpsertPayload,
  MessageCompactedPayload,
  FindingUpsertPayload,
  StepUpsertPayload,
  ProgressUpdatePayload,
  ApprovalRequestPayload,
} from "../types/sse";

// ── Constants ───────────────────────────────────────────────────

const API_RECOVERY_TIMEOUT_MS = 15_000;
const API_RECOVERY_RETRY_MS = 500;

// ── Safe JSON parse helper ──────────────────────────────────────

function safeParseJson<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T;
  } catch (parseError) {
    console.warn("Failed to parse SSE event data:", parseError);
    return null;
  }
}

// ── Hook ────────────────────────────────────────────────────────

/**
 * Hook that manages the SSE connection lifecycle.
 * Should be mounted once at the app root level.
 *
 * Features:
 *   - Automatically connects on mount, disconnects on unmount
 *   - Listens for all SSE event types and dispatches to stores
 *   - Handles reconnection with recovery logic
 *   - Triggers data resync after reconnection
 */
export function useSSE() {
  const recoveryPromiseRef = useRef<Promise<void> | null>(null);
  const realtimeResyncNeededRef = useRef(false);
  const mountedRef = useRef(true);

  const {
    connectionState,
    setConnectionState,
    setEventSource,
  } = useConnectionStore();

  const {
    upsertSessionSummary,
    upsertMessage: storeUpsertMessage,
    compactMessages,
    setFindings,
    upsertStep,
    setProgress,
  } = useSessionStore();

  // ── Refresh data (resync after reconnection) ──────────────────

  const refreshData = useCallback(
    async ({ suppressRecovery = false } = {}) => {
      try {
        // Load bootstrap data (includes default_config_path, authorizations, etc.)
        try {
          const bootstrap = await fetchJson<{
            default_config_path?: string;
            authorizations?: unknown[];
            knowledge_bases?: unknown[];
          }>(API_ENDPOINTS.BOOTSTRAP);
          if (bootstrap.default_config_path) {
            useSessionStore.getState().setDefaultConfigPath(
              bootstrap.default_config_path,
            );
          }
          // Sync authorizations if available
          if (bootstrap.authorizations) {
            const { useAuthorizationStore } = await import("../stores/use-authorization-store");
            useAuthorizationStore.getState().setAuthorizations(
              bootstrap.authorizations as import("../types/authorization").AuthorizationRecord[],
            );
          }
        } catch {
          // Bootstrap failure is non-fatal; continue with defaults
        }

        const payload = await fetchJson<{ sessions: unknown[] }>(
          API_ENDPOINTS.SESSIONS,
        );
        useSessionStore.getState().setSessions(
          (payload.sessions || []) as import("../types/session").SessionSummary[],
        );

        const state = useSessionStore.getState();
        if (state.selectedSessionId) {
          const selectedId = String(state.selectedSessionId);
          const exists = state.sessions.some(
            (item) => String(item.id) === selectedId,
          );
          if (exists) {
            await loadSessionDetail(selectedId, { suppressRecovery });
          } else {
            const firstId = state.sessions[0]?.id
              ? String(state.sessions[0].id)
              : null;
            useSessionStore.getState().selectSession(firstId);
            if (firstId) {
              await loadSessionDetail(firstId, { suppressRecovery });
            }
          }
        } else if (state.sessions.length) {
          const firstId = String(state.sessions[0].id);
          useSessionStore.getState().selectSession(firstId);
          await loadSessionDetail(firstId, { suppressRecovery });
        }
      } catch (error) {
        if (
          !suppressRecovery &&
          isTransientTransportError(error)
        ) {
          await recoverServerConnection({ refresh: true });
          return;
        }
        throw error;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // ── Load session detail ───────────────────────────────────────

  const loadSessionDetail = useCallback(
    async (
      sessionId: string,
      { suppressRecovery = false } = {},
    ) => {
      try {
        const { normalizeSessionDetail } = await import(
          "../lib/message-normalizer"
        );
        const raw = await fetchJson<Record<string, unknown>>(
          `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
        );
        const detail = normalizeSessionDetail(raw);
        useSessionStore.getState().setSessionDetail(sessionId, detail);
        useSessionStore.getState().upsertSessionSummary(detail);

        // Load findings
        try {
          const findingsData = await fetchJson<{ findings: unknown[] }>(
            `/api/chat/sessions/${encodeURIComponent(sessionId)}/findings`,
          );
          if (findingsData && Array.isArray(findingsData.findings)) {
            useSessionStore
              .getState()
              .setFindings(
                sessionId,
                findingsData.findings as import("../types/session").Finding[],
              );
          }
        } catch (e) {
          console.warn("Failed to load findings:", e);
        }

        // Load steps
        try {
          const stepsData = await fetchJson<{ steps: unknown[] }>(
            `/api/chat/sessions/${encodeURIComponent(sessionId)}/trajectory`,
          );
          if (stepsData && Array.isArray(stepsData.steps)) {
            useSessionStore
              .getState()
              .setSteps(
                sessionId,
                stepsData.steps as import("../types/session").Step[],
              );
          }
        } catch (e) {
          console.warn("Failed to load steps:", e);
        }
      } catch (error) {
        if (
          !suppressRecovery &&
          isTransientTransportError(error)
        ) {
          await recoverServerConnection({ refresh: false });
          return loadSessionDetail(sessionId, { suppressRecovery: true });
        }
        throw error;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // ── Schedule realtime resync ──────────────────────────────────

  const scheduleRealtimeResync = useCallback(() => {
    if (!realtimeResyncNeededRef.current) {
      return;
    }
    realtimeResyncNeededRef.current = false;
    refreshData({ suppressRecovery: true }).catch(() => {
      realtimeResyncNeededRef.current = true;
    });
  }, [refreshData]);

  // ── Recover server connection ─────────────────────────────────

  const recoverServerConnection = useCallback(
    async ({ refresh = true } = {}) => {
      if (recoveryPromiseRef.current) {
        return recoveryPromiseRef.current;
      }

      recoveryPromiseRef.current = (async () => {
        realtimeResyncNeededRef.current = true;
        setConnectionState("reconnecting");

        const deadline = Date.now() + API_RECOVERY_TIMEOUT_MS;
        let lastError = new Error("服务暂时不可用");

        while (Date.now() < deadline) {
          try {
            await fetchJson(
              `${API_ENDPOINTS.HEALTH}?_=${Date.now()}`,
              { timeoutMs: 3000 },
            );
            // Reconnect SSE
            if (mountedRef.current) {
              createEventSource();
            }
            if (refresh) {
              await refreshData({ suppressRecovery: true });
            }
            return;
          } catch (error) {
            lastError =
              error instanceof Error
                ? error
                : new Error(
                    String(error || "服务暂时不可用"),
                  );
            await sleep(API_RECOVERY_RETRY_MS);
          }
        }

        throw lastError;
      })();

      try {
        await recoveryPromiseRef.current;
      } finally {
        recoveryPromiseRef.current = null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [refreshData],
  );

  // ── Create EventSource ────────────────────────────────────────

  const createEventSource = useCallback(() => {
    // Close existing connection
    const existing = useConnectionStore.getState().eventSource;
    if (existing) {
      existing.close();
    }

    setConnectionState("connecting");

    const token = getApiToken();
    const eventsUrl = token
      ? `${API_ENDPOINTS.EVENTS}?token=${encodeURIComponent(token)}`
      : API_ENDPOINTS.EVENTS;

    const es = new EventSource(eventsUrl);
    setEventSource(es);

    // ── Connection opened ──
    const onOpen = () => {
      if (!mountedRef.current) return;
      setConnectionState("connected");
      // Always refresh data on connection open (first connect or reconnect).
      // This loads the session list and ensures the UI is in sync.
      refreshData({ suppressRecovery: true }).catch(() => {
        realtimeResyncNeededRef.current = true;
      });
    };

    es.addEventListener("open", onOpen);
    es.addEventListener("connected", onOpen);

    // ── session.upsert ──
    es.addEventListener("session.upsert", (event: MessageEvent) => {
      const payload = safeParseJson<SessionUpsertPayload>(event.data);
      if (!payload) return;
      upsertSessionSummary(payload.session);
    });

    // ── message.upsert ──
    es.addEventListener("message.upsert", (event: MessageEvent) => {
      const payload = safeParseJson<MessageUpsertPayload>(event.data);
      if (!payload) return;
      const sessionId = payload.session_id;

      const detail = useSessionStore
        .getState()
        .sessionDetails.get(sessionId);
      if (detail) {
        storeUpsertMessage(sessionId, payload.message as unknown as Record<string, unknown>);
      } else if (
        sessionId === useSessionStore.getState().selectedSessionId
      ) {
        loadSessionDetail(sessionId).catch(() => {});
        return;
      }
    });

    // ── message.compacted ──
    es.addEventListener("message.compacted", (event: MessageEvent) => {
      const payload = safeParseJson<MessageCompactedPayload>(event.data);
      if (!payload) return;
      const sessionId = payload.session_id;
      const deletedIds = Array.isArray(payload.deleted_message_ids)
        ? payload.deleted_message_ids.map((id) => String(id))
        : [];

      if (
        !deletedIds.length ||
        sessionId !== useSessionStore.getState().selectedSessionId
      ) {
        return;
      }
      compactMessages(sessionId, deletedIds);
    });

    // ── finding.upsert ──
    es.addEventListener("finding.upsert", (event: MessageEvent) => {
      const payload = safeParseJson<FindingUpsertPayload>(event.data);
      if (!payload) return;
      if (payload.session_id !== useSessionStore.getState().selectedSessionId)
        return;
      if (Array.isArray(payload.findings)) {
        setFindings(payload.session_id, payload.findings);
      }
    });

    // ── step.upsert ──
    es.addEventListener("step.upsert", (event: MessageEvent) => {
      const payload = safeParseJson<StepUpsertPayload>(event.data);
      if (!payload) return;
      if (payload.session_id !== useSessionStore.getState().selectedSessionId)
        return;
      if (payload.step) {
        upsertStep(payload.session_id, payload.step);
      }
    });

    // ── progress.update ──
    es.addEventListener("progress.update", (event: MessageEvent) => {
      const payload = safeParseJson<ProgressUpdatePayload>(event.data);
      if (!payload) return;
      if (payload.session_id !== useSessionStore.getState().selectedSessionId)
        return;
      if (payload.progress) {
        setProgress(payload.session_id, payload.progress);
      }
    });

    // ── approval.request ──
    es.addEventListener("approval.request", (event: MessageEvent) => {
      const payload = safeParseJson<ApprovalRequestPayload>(event.data);
      if (!payload) return;
      // Dispatch to a callback or event bus for the approval modal
      // The modal component will handle this via a separate mechanism
      window.dispatchEvent(
        new CustomEvent("approval:request", { detail: payload }),
      );
    });

    // ── approval.response ──
    es.addEventListener("approval.response", () => {
      window.dispatchEvent(new CustomEvent("approval:response"));
    });

    // ── Error handler ──
    es.onerror = () => {
      if (useConnectionStore.getState().eventSource !== es) {
        return;
      }
      setConnectionState("reconnecting");
      realtimeResyncNeededRef.current = true;
      recoverServerConnection({ refresh: true }).catch(() => {});
    };
  }, [
    setConnectionState,
    setEventSource,
    upsertSessionSummary,
    storeUpsertMessage,
    compactMessages,
    setFindings,
    upsertStep,
    setProgress,
    scheduleRealtimeResync,
    recoverServerConnection,
    loadSessionDetail,
  ]);

  // ── Connect / Disconnect ─────────────────────────────────────

  const connect = useCallback(() => {
    mountedRef.current = true;
    createEventSource();
  }, [createEventSource]);

  const disconnect = useCallback(() => {
    mountedRef.current = false;
    const es = useConnectionStore.getState().eventSource;
    if (es) {
      es.close();
    }
    setEventSource(null);
    setConnectionState("disconnected");
  }, [setEventSource, setConnectionState]);

  // ── Lifecycle ─────────────────────────────────────────────────

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  // ── Return ────────────────────────────────────────────────────

  return {
    connectionState,
    connect,
    disconnect,
  };
}
