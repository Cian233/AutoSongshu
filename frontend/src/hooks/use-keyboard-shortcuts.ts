// ── Keyboard Shortcuts Hook ─────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/app.js —
//   keyboard shortcut bindings (Cmd+N, Cmd+Shift+D, Cmd+F, Cmd+,, Escape)
//
// Provides global keyboard shortcuts that:
//   - Do not conflict with browser defaults (e.g. Cmd+R for refresh)
//   - Only fire when the user is not typing in an input/textarea/contenteditable
//   - Can be conditionally enabled/disabled

import { useEffect, useCallback } from "react";
import { useUIStore, type ThemeMode } from "../stores/use-ui-store";
import { useSearchStore } from "../stores/use-search-store";
import { useSessionStore } from "../stores/use-session-store";

// ── Theme cycle ─────────────────────────────────────────────────

const THEME_CYCLE: ThemeMode[] = ["system", "light", "dark"];

function cycleTheme(current: ThemeMode): ThemeMode {
  const currentIndex = THEME_CYCLE.indexOf(current);
  const nextIndex = (currentIndex + 1) % THEME_CYCLE.length;
  return THEME_CYCLE[nextIndex];
}

// ── Hook ────────────────────────────────────────────────────────

/**
 * Hook that registers global keyboard shortcuts.
 * Should be mounted once at the app root level.
 *
 * Shortcuts:
 *   - Cmd/Ctrl + Enter:  Submit message (delegated to Composer)
 *   - Cmd/Ctrl + N:      New chat
 *   - Cmd/Ctrl + Shift + D: Toggle theme
 *   - Cmd/Ctrl + F:      Open search panel
 *   - Cmd/Ctrl + ,:      Open settings
 *   - Escape:            Close open panels (search, settings)
 *
 * Shortcuts are suppressed when the user is focused on:
 *   - <input>, <textarea>, <select>
 *   - Elements with contenteditable="true"
 */
export function useKeyboardShortcuts(
  overrides?: Partial<{
    onNewChat: () => void;
    onToggleTheme: () => void;
    onOpenSearch: () => void;
    onCloseSearch: () => void;
    onOpenSettings: () => void;
    onCloseSettings: () => void;
  }>,
): void {
  const setTheme = useUIStore((state) => state.setTheme);
  const theme = useUIStore((state) => state.theme);
  const settingsOpen = useUIStore((state) => state.settingsOpen);
  const setSettingsOpen = useUIStore((state) => state.setSettingsOpen);
  const searchOpen = useSearchStore((state) => state.searchOpen);
  const setSearchOpen = useSearchStore((state) => state.setSearchOpen);
  const selectSession = useSessionStore((state) => state.selectSession);

  // ── Handlers ──────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    if (overrides?.onNewChat) {
      overrides.onNewChat();
    } else {
      selectSession(null);
    }
  }, [overrides, selectSession]);

  const handleToggleTheme = useCallback(() => {
    if (overrides?.onToggleTheme) {
      overrides.onToggleTheme();
    } else {
      const next = cycleTheme(theme);
      setTheme(next);
      try {
        localStorage.setItem("autosongshu-theme", next);
      } catch {
        // Ignore storage errors
      }
    }
  }, [overrides, theme, setTheme]);

  const handleOpenSearch = useCallback(() => {
    if (overrides?.onOpenSearch) {
      overrides.onOpenSearch();
    } else {
      setSearchOpen(true);
    }
  }, [overrides, setSearchOpen]);

  const handleCloseSearch = useCallback(() => {
    if (overrides?.onCloseSearch) {
      overrides.onCloseSearch();
    } else {
      setSearchOpen(false);
    }
  }, [overrides, setSearchOpen]);

  const handleOpenSettings = useCallback(() => {
    if (overrides?.onOpenSettings) {
      overrides.onOpenSettings();
    } else {
      setSettingsOpen(true);
    }
  }, [overrides, setSettingsOpen]);

  const handleCloseSettings = useCallback(() => {
    if (overrides?.onCloseSettings) {
      overrides.onCloseSettings();
    } else {
      setSettingsOpen(false);
    }
  }, [overrides, setSettingsOpen]);

  // ── Effect ────────────────────────────────────────────────────

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;

      // ── Escape: close panels ─────────────────────────────────
      if (e.key === "Escape") {
        if (searchOpen) {
          handleCloseSearch();
          return;
        }
        if (settingsOpen) {
          handleCloseSettings();
          return;
        }
        return;
      }

      // ── Mod shortcuts: only when mod key is pressed ──────────
      if (!mod) {
        return;
      }

      // Check if the user is typing in an input element
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        // Allow Cmd+N and Cmd+Shift+D even in inputs
        // Block Cmd+F and Cmd+, in inputs to avoid browser conflicts
        const key = e.key.toLowerCase();
        if (key === "n" && !e.shiftKey) {
          e.preventDefault();
          handleNewChat();
          return;
        }
        if (key === "d" && e.shiftKey) {
          e.preventDefault();
          handleToggleTheme();
          return;
        }
        // Do not intercept other mod shortcuts when focused on inputs
        return;
      }

      switch (e.key.toLowerCase()) {
        case "n":
          if (!e.shiftKey) {
            e.preventDefault();
            handleNewChat();
          }
          break;

        case "d":
          if (e.shiftKey) {
            e.preventDefault();
            handleToggleTheme();
          }
          break;

        case "f":
          e.preventDefault();
          handleOpenSearch();
          break;

        case ",":
          e.preventDefault();
          handleOpenSettings();
          break;
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [
    searchOpen,
    settingsOpen,
    handleNewChat,
    handleToggleTheme,
    handleOpenSearch,
    handleCloseSearch,
    handleOpenSettings,
    handleCloseSettings,
  ]);
}
