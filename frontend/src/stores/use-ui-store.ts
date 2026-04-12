// ── UI Store ─────────────────────────────────────────────────────
// Zustand store managing UI preferences and transient state that
// does not belong to any specific domain (session, knowledge, etc.).

import { create } from "zustand";

// ── Types ───────────────────────────────────────────────────────

export type ThemeMode = "system" | "light" | "dark";

export interface PanelExpansion {
  steps: boolean;
  findings: boolean;
  shortcuts: boolean;
}

// ── State Shape ─────────────────────────────────────────────────

interface UIState {
  /** Whether the settings panel is open */
  settingsOpen: boolean;
  /** Current theme mode */
  theme: ThemeMode;
  /** Expansion state of side panels */
  panelExpansion: PanelExpansion;
  /** Expansion state of individual assistant message parts, keyed by part identifier */
  assistantPartExpansion: Map<string, boolean>;
  /** Whether the chat view auto-scrolls to the latest message */
  chatAutoFollow: boolean;
}

// ── Actions ─────────────────────────────────────────────────────

interface UIActions {
  /** Toggle the settings panel */
  toggleSettings: () => void;
  /** Set the settings panel open state */
  setSettingsOpen: (open: boolean) => void;

  /** Set the theme mode */
  setTheme: (theme: ThemeMode) => void;

  /** Toggle a side panel's expansion state */
  togglePanel: (panelKey: keyof PanelExpansion) => void;
  /** Set a side panel's expansion state */
  setPanelExpansion: (panelKey: keyof PanelExpansion, expanded: boolean) => void;

  /** Get whether an assistant part is expanded (with fallback default) */
  isAssistantPartExpanded: (key: string, fallback?: boolean) => boolean;
  /** Set an assistant part's expansion state */
  setAssistantPartExpanded: (key: string, expanded: boolean) => void;

  /** Toggle chat auto-follow */
  toggleChatAutoFollow: () => void;
  /** Set chat auto-follow */
  setChatAutoFollow: (value: boolean) => void;
}

// ── Store ───────────────────────────────────────────────────────

export const useUIStore = create<UIState & UIActions>((set, get) => ({
  // ── Initial state ──
  settingsOpen: false,
  theme: "system",
  panelExpansion: {
    steps: true,
    findings: true,
    shortcuts: false,
  },
  assistantPartExpansion: new Map(),
  chatAutoFollow: true,

  // ── Actions ──

  toggleSettings: () => {
    set((state) => ({ settingsOpen: !state.settingsOpen }));
  },

  setSettingsOpen: (open) => {
    set({ settingsOpen: open });
  },

  setTheme: (theme) => {
    set({ theme });
  },

  togglePanel: (panelKey) => {
    set((state) => ({
      panelExpansion: {
        ...state.panelExpansion,
        [panelKey]: !state.panelExpansion[panelKey],
      },
    }));
  },

  setPanelExpansion: (panelKey, expanded) => {
    set((state) => ({
      panelExpansion: {
        ...state.panelExpansion,
        [panelKey]: expanded,
      },
    }));
  },

  isAssistantPartExpanded: (key, fallback = false) => {
    const normalizedKey = String(key || "").trim();
    if (!normalizedKey) {
      return fallback;
    }
    const { assistantPartExpansion } = get();
    if (!assistantPartExpansion.has(normalizedKey)) {
      return fallback;
    }
    return Boolean(assistantPartExpansion.get(normalizedKey));
  },

  setAssistantPartExpanded: (key, expanded) => {
    const normalizedKey = String(key || "").trim();
    if (!normalizedKey) {
      return;
    }
    set((state) => {
      const assistantPartExpansion = new Map(state.assistantPartExpansion);
      assistantPartExpansion.set(normalizedKey, Boolean(expanded));
      return { assistantPartExpansion };
    });
  },

  toggleChatAutoFollow: () => {
    set((state) => ({ chatAutoFollow: !state.chatAutoFollow }));
  },

  setChatAutoFollow: (value) => {
    set({ chatAutoFollow: value });
  },
}));
