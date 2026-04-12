// ── Session Store ────────────────────────────────────────────────
// Zustand store managing session list, session details, messages,
// findings, steps, and progress state.

import { create } from "zustand";
import type {
  SessionSummary,
  SessionDetail,
  Finding,
  Step,
  Progress,
} from "../types/session";
import {
  normalizeSessionSummary,
  normalizeSessionDetail,
  upsertMessage,
} from "../lib/message-normalizer";
import { fetchJson } from "../lib/api";

// ── State Shape ─────────────────────────────────────────────────

interface SessionState {
  /** Ordered list of session summaries (sorted by updated_at desc) */
  sessions: SessionSummary[];
  /** Detailed session data keyed by session ID */
  sessionDetails: Map<string, SessionDetail>;
  /** Currently selected session ID */
  selectedSessionId: string | null;
  /** Whether a message is currently being submitted */
  isSubmitting: boolean;
  /** Findings for the selected session */
  findings: Finding[];
  /** Session ID that the findings belong to */
  findingsSessionId: string | null;
  /** Steps (trajectory) for the selected session */
  steps: Step[];
  /** Session ID that the steps belong to */
  stepsSessionId: string | null;
  /** Current progress indicator */
  progress: Progress | null;
  /** Session ID that the progress belongs to */
  progressSessionId: string | null;
  /** Default config path from bootstrap */
  defaultConfigPath: string;
}

// ── Actions ─────────────────────────────────────────────────────

interface SessionActions {
  /** Select a session by ID */
  selectSession: (sessionId: string | null) => void;

  /** Insert or update a session summary in the list */
  upsertSessionSummary: (summary: SessionSummary | Record<string, unknown>) => void;

  /** Insert or update a message in a session detail */
  upsertMessage: (sessionId: string, message: Record<string, unknown>) => void;

  /** Set a session detail (full replace) */
  setSessionDetail: (sessionId: string, detail: SessionDetail) => void;

  /** Remove deleted message IDs from a session */
  removeMessages: (sessionId: string, deletedIds: string[]) => void;

  /** Set the submitting state */
  setSubmitting: (value: boolean) => void;

  /** Set findings for a session */
  setFindings: (sessionId: string, findings: Finding[]) => void;

  /** Set steps for a session */
  setSteps: (sessionId: string, steps: Step[]) => void;

  /** Upsert a single step (by index) */
  upsertStep: (sessionId: string, step: Step) => void;

  /** Set progress for a session */
  setProgress: (sessionId: string, progress: Progress | null) => void;

  /** Clear all findings */
  clearFindings: () => void;

  /** Clear all steps */
  clearSteps: () => void;

  /** Clear all progress */
  clearProgress: () => void;

  /** Set the full sessions list (e.g. from bootstrap / refresh) */
  setSessions: (sessions: SessionSummary[]) => void;

  /** Sort sessions by updated_at descending */
  sortSessions: () => void;

  /** Set the default config path */
  setDefaultConfigPath: (path: string) => void;
}

// ── Sort helper ─────────────────────────────────────────────────

function sortSessionsDescending(sessions: SessionSummary[]): SessionSummary[] {
  return [...sessions].sort((left, right) =>
    String(right.updated_at || "").localeCompare(String(left.updated_at || "")),
  );
}

// ── Store ───────────────────────────────────────────────────────

export const useSessionStore = create<SessionState & SessionActions>(
  (set) => ({
    // ── Initial state ──
    sessions: [],
    sessionDetails: new Map(),
    selectedSessionId: null,
    isSubmitting: false,
    findings: [],
    findingsSessionId: null,
    steps: [],
    stepsSessionId: null,
    progress: null,
    progressSessionId: null,
    defaultConfigPath: "configs/pentest.example.yaml",

    // ── Actions ──

    selectSession: (sessionId) => {
      set({ selectedSessionId: sessionId });
      // If the target session's detail is not cached, load it now.
      if (sessionId) {
        const existing = useSessionStore.getState().sessionDetails.get(sessionId);
        if (!existing) {
          loadSessionDetailFromStore(sessionId).catch((err) => {
            console.warn("Failed to load session detail on switch:", err);
          });
        }
      }
    },

    upsertSessionSummary: (summary) => {
      const normalized =
        summary instanceof Object && "id" in summary && "messages" in summary
          ? (summary as unknown as SessionSummary)
          : normalizeSessionSummary(summary as Record<string, unknown>);

      const summaryId = String(normalized.id || "");
      set((state) => {
        const sessions = [...state.sessions];
        const index = sessions.findIndex(
          (item) => String(item.id) === summaryId,
        );
        if (index === -1) {
          sessions.push(normalized);
        } else {
          sessions[index] = { ...sessions[index], ...normalized };
        }
        const sorted = sortSessionsDescending(sessions);

        // Also update session detail if loaded
        const sessionDetails = new Map(state.sessionDetails);
        const detail = sessionDetails.get(summaryId);
        if (detail) {
          sessionDetails.set(summaryId, { ...detail, ...normalized });
        }

        return { sessions: sorted, sessionDetails };
      });
    },

    upsertMessage: (sessionId, message) => {
      set((state) => {
        const sessionDetails = new Map(state.sessionDetails);
        const detail = sessionDetails.get(sessionId);
        if (detail) {
          sessionDetails.set(sessionId, upsertMessage(detail, message));
        }
        return { sessionDetails };
      });
    },

    setSessionDetail: (sessionId, detail) => {
      set((state) => {
        const sessionDetails = new Map(state.sessionDetails);
        sessionDetails.set(sessionId, detail);
        return { sessionDetails };
      });
    },

    removeMessages: (sessionId, deletedIds) => {
      if (!deletedIds.length) return;
      set((state) => {
        const sessionDetails = new Map(state.sessionDetails);
        const detail = sessionDetails.get(sessionId);
        if (!detail || !Array.isArray(detail.messages)) {
          return state;
        }
        const removedSet = new Set(deletedIds.map(String));
        const filtered = detail.messages.filter(
          (msg) => !removedSet.has(String(msg.id)),
        );
        sessionDetails.set(sessionId, { ...detail, messages: filtered });
        return { sessionDetails };
      });
    },

    setSubmitting: (value) => {
      set({ isSubmitting: value });
    },

    setFindings: (sessionId, findings) => {
      set({ findings, findingsSessionId: sessionId });
    },

    setSteps: (sessionId, steps) => {
      set({ steps, stepsSessionId: sessionId });
    },

    upsertStep: (sessionId, step) => {
      set((state) => {
        if (sessionId !== state.stepsSessionId) {
          return state;
        }
        const steps = [...state.steps];
        const existing = steps.findIndex((s) => s.index === step.index);
        if (existing >= 0) {
          steps[existing] = step;
        } else {
          steps.push(step);
        }
        return { steps };
      });
    },

    setProgress: (sessionId, progress) => {
      set({ progress, progressSessionId: sessionId });
    },

    clearFindings: () => {
      set({ findings: [], findingsSessionId: null });
    },

    clearSteps: () => {
      set({ steps: [], stepsSessionId: null });
    },

    clearProgress: () => {
      set({ progress: null, progressSessionId: null });
    },

    setSessions: (sessions) => {
      set({ sessions: sortSessionsDescending(sessions) });
    },

    sortSessions: () => {
      set((state) => ({
        sessions: sortSessionsDescending(state.sessions),
      }));
    },

    setDefaultConfigPath: (path) => {
      set({ defaultConfigPath: path });
    },
  }),
);

// ── Standalone session detail loader ─────────────────────────────
// Extracted so it can be called from store actions without React hooks.

async function loadSessionDetailFromStore(sessionId: string) {
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
      useSessionStore.getState().setFindings(sessionId, findingsData.findings as Finding[]);
    }
  } catch (e) {
    // Non-critical
  }

  // Load steps
  try {
    const stepsData = await fetchJson<{ steps: unknown[] }>(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/trajectory`,
    );
    if (stepsData && Array.isArray(stepsData.steps)) {
      useSessionStore.getState().setSteps(sessionId, stepsData.steps as Step[]);
    }
  } catch (e) {
    // Non-critical
  }
}
