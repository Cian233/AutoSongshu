// ── Authorization Store ─────────────────────────────────────────
// Zustand store managing authorization configuration state:
// saved authorization records and the current form draft.

import { create } from "zustand";
import type {
  AuthorizationRecord,
  AuthorizationDraft,
} from "../types/authorization";

// ── State Shape ─────────────────────────────────────────────────

interface AuthorizationState {
  /** List of saved authorization records */
  authorizations: AuthorizationRecord[];
  /** Current authorization form draft */
  authorizationDraft: AuthorizationDraft;
  /** Default authorization draft (from bootstrap) */
  defaultAuthorizationDraft: AuthorizationDraft | null;
}

// ── Actions ─────────────────────────────────────────────────────

interface AuthorizationActions {
  /** Set the full list of authorization records */
  setAuthorizations: (records: AuthorizationRecord[]) => void;

  /** Set the current authorization form draft */
  setAuthorizationDraft: (draft: AuthorizationDraft) => void;

  /** Update a single field in the authorization draft */
  updateAuthorizationDraft: (
    patch: Partial<AuthorizationDraft>,
  ) => void;

  /** Reset the authorization draft to the default */
  resetAuthorizationDraft: () => void;

  /** Set the default authorization draft (from bootstrap) */
  setDefaultAuthorizationDraft: (
    draft: AuthorizationDraft | null,
  ) => void;

  /** Fill the draft from a saved authorization record */
  fillDraftFromRecord: (record: AuthorizationRecord) => void;
}

// ── Empty draft ─────────────────────────────────────────────────

const EMPTY_DRAFT: AuthorizationDraft = {
  name: "",
  authorization: "",
  start_url: "",
  allowed_hosts: [],
  allow_subdomains: true,
  notes: null,
};

// ── Store ───────────────────────────────────────────────────────

export const useAuthorizationStore = create<
  AuthorizationState & AuthorizationActions
>((set, get) => ({
  // ── Initial state ──
  authorizations: [],
  authorizationDraft: { ...EMPTY_DRAFT },
  defaultAuthorizationDraft: null,

  // ── Actions ──

  setAuthorizations: (authorizations) => {
    set({ authorizations });
  },

  setAuthorizationDraft: (authorizationDraft) => {
    set({ authorizationDraft });
  },

  updateAuthorizationDraft: (patch) => {
    set((state) => ({
      authorizationDraft: { ...state.authorizationDraft, ...patch },
    }));
  },

  resetAuthorizationDraft: () => {
    const { defaultAuthorizationDraft } = get();
    set({
      authorizationDraft: defaultAuthorizationDraft
        ? { ...defaultAuthorizationDraft }
        : { ...EMPTY_DRAFT },
    });
  },

  setDefaultAuthorizationDraft: (defaultAuthorizationDraft) => {
    set({ defaultAuthorizationDraft });
  },

  fillDraftFromRecord: (record) => {
    set({
      authorizationDraft: {
        name: record.name,
        authorization: record.authorization,
        start_url: record.start_url,
        allowed_hosts: record.allowed_hosts
          ? [...record.allowed_hosts]
          : [],
        allow_subdomains: record.allow_subdomains ?? true,
        notes: record.notes ?? null,
      },
    });
  },
}));
