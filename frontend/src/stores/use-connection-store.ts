// ── Connection Store ─────────────────────────────────────────────
// Zustand store managing SSE (Server-Sent Events) connection state.

import { create } from "zustand";
import type { SSEConnectionState } from "../types/sse";

// ── State Shape ─────────────────────────────────────────────────

interface ConnectionState {
  /** Current SSE connection state */
  connectionState: SSEConnectionState;
  /** The active EventSource instance (null when disconnected) */
  eventSource: EventSource | null;
}

// ── Actions ─────────────────────────────────────────────────────

interface ConnectionActions {
  /** Update the connection state */
  setConnectionState: (state: SSEConnectionState) => void;

  /** Store the active EventSource instance */
  setEventSource: (es: EventSource | null) => void;

  /** Connect to the SSE event stream */
  connect: () => void;

  /** Disconnect from the SSE event stream */
  disconnect: () => void;
}

// ── Store ───────────────────────────────────────────────────────

export const useConnectionStore = create<ConnectionState & ConnectionActions>(
  (set, get) => ({
    // ── Initial state ──
    connectionState: "connecting",
    eventSource: null,

    // ── Actions ──

    setConnectionState: (connectionState) => {
      set({ connectionState });
    },

    setEventSource: (eventSource) => {
      set({ eventSource });
    },

    connect: () => {
      const { eventSource } = get();
      // Close existing connection if any
      if (eventSource) {
        eventSource.close();
      }
      set({ connectionState: "connecting" });
      // The actual EventSource creation is handled by the useSSE hook
    },

    disconnect: () => {
      const { eventSource } = get();
      if (eventSource) {
        eventSource.close();
      }
      set({ eventSource: null, connectionState: "disconnected" });
    },
  }),
);
