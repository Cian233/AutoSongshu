// ── Model Store ──────────────────────────────────────────────────
// Manages model profile state: list of profiles, active profile,
// and switching at runtime.

import { create } from "zustand";
import { fetchJson } from "../lib/api";
import { API_ENDPOINTS } from "../lib/api-endpoints";

// ── Types ────────────────────────────────────────────────────────

export interface ModelProfile {
  name: string;
  display_name: string;
  provider: string;
  model_name: string;
  base_url: string | null;
  temperature: number;
  top_p: number;
  max_tokens: number | null;
  tasks: string[];
  enabled: boolean;
  is_active: boolean;
  cost_per_1m_input: number;
  cost_per_1m_output: number;
}

interface ModelState {
  profiles: ModelProfile[];
  activeProfile: string | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchProfiles: () => Promise<void>;
  setActiveProfile: (name: string) => Promise<boolean>;
}

// ── Store ────────────────────────────────────────────────────────

export const useModelStore = create<ModelState>((set) => ({
  profiles: [],
  activeProfile: null,
  isLoading: false,
  error: null,

  fetchProfiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const payload = await fetchJson<{ profiles: ModelProfile[] }>(
        API_ENDPOINTS.MODELS,
      );
      const profiles = payload.profiles || [];
      const active = profiles.find((p) => p.is_active);
      set({
        profiles,
        activeProfile: active?.name || null,
        isLoading: false,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message, isLoading: false });
    }
  },

  setActiveProfile: async (name: string) => {
    try {
      await fetchJson(API_ENDPOINTS.MODELS_ACTIVE, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: name }),
      });
      set((state) => ({
        activeProfile: name,
        profiles: state.profiles.map((p) => ({
          ...p,
          is_active: p.name === name,
        })),
      }));
      return true;
    } catch {
      return false;
    }
  },
}));
