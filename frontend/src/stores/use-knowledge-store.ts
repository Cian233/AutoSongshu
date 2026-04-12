// ── Knowledge Store ─────────────────────────────────────────────
// Zustand store managing knowledge base state: list of knowledge
// bases, selected IDs, details, and modal state.

import { create } from "zustand";
import type {
  KnowledgeBaseSummary,
  KnowledgeBaseDetail,
} from "../types/knowledge";

// ── State Shape ─────────────────────────────────────────────────

interface KnowledgeState {
  /** List of all knowledge bases */
  knowledgeBases: KnowledgeBaseSummary[];
  /** Detailed knowledge base data keyed by ID */
  knowledgeBaseDetails: Map<string, KnowledgeBaseDetail>;
  /** Currently selected knowledge base ID (for detail view) */
  selectedKnowledgeBaseId: string | null;
  /** IDs of knowledge bases selected for attachment to a session */
  selectedKnowledgeBaseIds: string[];
  /** Whether the knowledge base modal is open */
  knowledgeModalOpen: boolean;
  /** Whether a knowledge distillation is in progress */
  isDistillingKnowledge: boolean;
}

// ── Actions ─────────────────────────────────────────────────────

interface KnowledgeActions {
  /** Set the full list of knowledge bases */
  setKnowledgeBases: (bases: KnowledgeBaseSummary[]) => void;

  /** Set a knowledge base detail */
  setKnowledgeBaseDetail: (
    id: string,
    detail: KnowledgeBaseDetail,
  ) => void;

  /** Remove a knowledge base detail */
  removeKnowledgeBaseDetail: (id: string) => void;

  /** Select a knowledge base for detail view */
  setSelectedKnowledgeBaseId: (id: string | null) => void;

  /** Set the selected knowledge base IDs for session attachment */
  setSelectedKnowledgeBaseIds: (ids: string[]) => void;

  /** Toggle the knowledge base modal */
  toggleKnowledgeModal: () => void;
  /** Set the knowledge base modal open state */
  setKnowledgeModalOpen: (open: boolean) => void;

  /** Set the distilling state */
  setDistillingKnowledge: (value: boolean) => void;
}

// ── Store ───────────────────────────────────────────────────────

export const useKnowledgeStore = create<
  KnowledgeState & KnowledgeActions
>((set) => ({
  // ── Initial state ──
  knowledgeBases: [],
  knowledgeBaseDetails: new Map(),
  selectedKnowledgeBaseId: null,
  selectedKnowledgeBaseIds: [],
  knowledgeModalOpen: false,
  isDistillingKnowledge: false,

  // ── Actions ──

  setKnowledgeBases: (knowledgeBases) => {
    set({ knowledgeBases });
  },

  setKnowledgeBaseDetail: (id, detail) => {
    set((state) => {
      const knowledgeBaseDetails = new Map(state.knowledgeBaseDetails);
      knowledgeBaseDetails.set(id, detail);
      return { knowledgeBaseDetails };
    });
  },

  removeKnowledgeBaseDetail: (id) => {
    set((state) => {
      const knowledgeBaseDetails = new Map(state.knowledgeBaseDetails);
      knowledgeBaseDetails.delete(id);
      return { knowledgeBaseDetails };
    });
  },

  setSelectedKnowledgeBaseId: (selectedKnowledgeBaseId) => {
    set({ selectedKnowledgeBaseId });
  },

  setSelectedKnowledgeBaseIds: (selectedKnowledgeBaseIds) => {
    set({ selectedKnowledgeBaseIds });
  },

  toggleKnowledgeModal: () => {
    set((state) => ({ knowledgeModalOpen: !state.knowledgeModalOpen }));
  },

  setKnowledgeModalOpen: (knowledgeModalOpen) => {
    set({ knowledgeModalOpen });
  },

  setDistillingKnowledge: (isDistillingKnowledge) => {
    set({ isDistillingKnowledge });
  },
}));
