// ── Search Store ─────────────────────────────────────────────────
// Zustand store managing search/filter state for sessions,
// knowledge bases, and other list views.

import { create } from "zustand";

// ── State Shape ─────────────────────────────────────────────────

interface SearchState {
  /** Current search query string */
  searchQuery: string;
  /** Whether the search panel / UI is visible */
  searchOpen: boolean;
}

// ── Actions ─────────────────────────────────────────────────────

interface SearchActions {
  /** Set the search query */
  setSearchQuery: (query: string) => void;
  /** Clear the search query */
  clearSearch: () => void;
  /** Toggle the search panel visibility */
  toggleSearch: () => void;
  /** Set the search panel visibility */
  setSearchOpen: (open: boolean) => void;
}

// ── Store ───────────────────────────────────────────────────────

export const useSearchStore = create<SearchState & SearchActions>(
  (set) => ({
    // ── Initial state ──
    searchQuery: "",
    searchOpen: false,

    // ── Actions ──

    setSearchQuery: (searchQuery) => {
      set({ searchQuery });
    },

    clearSearch: () => {
      set({ searchQuery: "" });
    },

    toggleSearch: () => {
      set((state) => ({ searchOpen: !state.searchOpen }));
    },

    setSearchOpen: (searchOpen) => {
      set({ searchOpen });
    },
  }),
);
