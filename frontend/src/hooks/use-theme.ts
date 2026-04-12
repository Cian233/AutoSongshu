// ── Theme Management Hook ───────────────────────────────────────
// Manages the application theme (light/dark/system) by:
//   - Reading the theme from the UI store
//   - Applying the appropriate CSS class to the document root
//   - Listening for system preference changes when in "system" mode

import { useEffect } from "react";
import { useUIStore, type ThemeMode } from "../stores/use-ui-store";

/**
 * Resolve the effective theme based on the mode and system preference.
 */
function resolveTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return mode;
}

/**
 * Apply the theme to the document root element.
 */
function applyTheme(theme: "light" | "dark"): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
}

/**
 * Hook that synchronizes the theme from the UI store with the DOM.
 * Should be mounted once at the app root level.
 *
 * Features:
 *   - Applies the resolved theme class to <html>
 *   - Listens for system preference changes when mode is "system"
 *   - Reacts to theme changes from the store
 */
export function useTheme(): {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  effectiveTheme: "light" | "dark";
} {
  const theme = useUIStore((state) => state.theme);
  const setTheme = useUIStore((state) => state.setTheme);

  const effectiveTheme = resolveTheme(theme);

  // Apply theme to DOM whenever it changes
  useEffect(() => {
    applyTheme(effectiveTheme);
  }, [effectiveTheme]);

  // Listen for system preference changes when in "system" mode
  useEffect(() => {
    if (theme !== "system") {
      return;
    }

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      applyTheme(resolveTheme("system"));
    };

    mediaQuery.addEventListener("change", handler);
    return () => {
      mediaQuery.removeEventListener("change", handler);
    };
  }, [theme]);

  return {
    theme,
    setTheme,
    effectiveTheme,
  };
}
