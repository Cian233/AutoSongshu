// ── Model Store ──────────────────────────────────────────────────
// Manages model profile state: list of profiles, active profile,
// switching at runtime, and CRUD operations.

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
  compaction?: Record<string, number | boolean>;
}

/** Input for creating a new profile (subset of fields). */
export interface NewProfileInput {
  name: string;
  display_name?: string;
  provider?: string;
  model_name: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
  top_p?: number;
  max_tokens?: number | null;
  tasks?: string[];
}

interface ModelState {
  profiles: ModelProfile[];
  activeProfile: string | null;
  isLoading: boolean;
  error: string | null;
  isSaving: boolean;

  // Actions
  fetchProfiles: () => Promise<void>;
  setActiveProfile: (name: string) => Promise<boolean>;
  addProfile: (input: NewProfileInput) => Promise<boolean>;
  deleteProfile: (name: string) => Promise<boolean>;
  updateProfile: (name: string, patch: Record<string, unknown>) => Promise<boolean>;
}

// ── Store ────────────────────────────────────────────────────────

export const useModelStore = create<ModelState>((set, get) => ({
  profiles: [],
  activeProfile: null,
  isLoading: false,
  error: null,
  isSaving: false,

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

  addProfile: async (input: NewProfileInput) => {
    set({ isSaving: true, error: null });
    try {
      const result = await fetchJson<{ ok: boolean; profile: ModelProfile }>(
        API_ENDPOINTS.MODELS_ADD,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: input }),
        },
      );
      if (result.ok && result.profile) {
        // Re-fetch to get the full updated list
        await get().fetchProfiles();
        return true;
      }
      set({ isSaving: false });
      return false;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message, isSaving: false });
      return false;
    }
  },

  deleteProfile: async (name: string) => {
    set({ isSaving: true, error: null });
    try {
      await fetchJson(`/api/models/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      await get().fetchProfiles();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message, isSaving: false });
      return false;
    }
  },

  updateProfile: async (name: string, patch: Record<string, unknown>) => {
    set({ isSaving: true, error: null });
    try {
      await fetchJson(API_ENDPOINTS.MODELS_UPDATE(name), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      await get().fetchProfiles();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message, isSaving: false });
      return false;
    }
  },
}));
