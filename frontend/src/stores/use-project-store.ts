// ── Project Store ────────────────────────────────────────────────
// Zustand store managing project list, selected project, and project-level state.
// Codex-style: one project can have multiple sessions sharing a workspace.

import { create } from "zustand";
import type { Project } from "../types/session";
import { fetchJson } from "../lib/api";

// ── State Shape ─────────────────────────────────────────────────

interface ProjectState {
  /** Ordered list of projects */
  projects: Project[];
  /** Currently selected project ID */
  selectedProjectId: string | null;
  /** Whether projects are being loaded */
  isLoading: boolean;
}

// ── Actions ─────────────────────────────────────────────────────

interface ProjectActions {
  /** Select a project by ID */
  selectProject: (projectId: string | null) => void;

  /** Set the full projects list */
  setProjects: (projects: Project[]) => void;

  /** Insert or update a project */
  upsertProject: (project: Project) => void;

  /** Remove a project */
  removeProject: (projectId: string) => void;

  /** Load projects from API */
  loadProjects: () => Promise<void>;

  /** Create a new project */
  createProject: (name: string, workspaceDir?: string) => Promise<Project | null>;

  /** Delete a project */
  deleteProject: (projectId: string) => Promise<boolean>;

  /** Set loading state */
  setLoading: (value: boolean) => void;
}

// ── Store ───────────────────────────────────────────────────────

export const useProjectStore = create<ProjectState & ProjectActions>((set, get) => ({
  // ── Initial state ──
  projects: [],
  selectedProjectId: null,
  isLoading: false,

  // ── Actions ──
  selectProject: (projectId) => {
    set({ selectedProjectId: projectId });
  },

  setProjects: (projects) => {
    set({ projects });
  },

  upsertProject: (project) => {
    set((state) => {
      const projects = [...state.projects];
      const existing = projects.findIndex((p) => p.id === project.id);
      if (existing >= 0) {
        projects[existing] = { ...projects[existing], ...project };
      } else {
        projects.push(project);
      }
      return { projects };
    });
  },

  removeProject: (projectId) => {
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== projectId),
      selectedProjectId: state.selectedProjectId === projectId ? null : state.selectedProjectId,
    }));
  },

  loadProjects: async () => {
    set({ isLoading: true });
    try {
      const data = await fetchJson<{ projects?: Record<string, unknown>[] }>("/api/projects");
      const projects: Project[] = (data.projects || []).map((p: Record<string, unknown>) => ({
        id: String(p.id || ""),
        name: String(p.name || "Untitled"),
        workspace_dir: String(p.workspace_dir || ""),
        artifacts_dir: String(p.artifacts_dir || ""),
        isolation_mode: (p.isolation_mode as Project["isolation_mode"]) || "project",
        created_at: String(p.created_at || ""),
        updated_at: String(p.updated_at || ""),
        session_count: Number(p.session_count || 0),
      }));
      set({ projects, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  createProject: async (name, workspaceDir) => {
    try {
      const data = await fetchJson<Record<string, unknown>>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, workspace_dir: workspaceDir }),
      });
      const project: Project = {
        id: String(data.id || ""),
        name: String(data.name || name),
        workspace_dir: String(data.workspace_dir || ""),
        artifacts_dir: String(data.artifacts_dir || ""),
        isolation_mode: (data.isolation_mode as Project["isolation_mode"]) || "project",
        created_at: String(data.created_at || ""),
        updated_at: String(data.updated_at || ""),
        session_count: 0,
      };
      get().upsertProject(project);
      return project;
    } catch {
      return null;
    }
  },

  deleteProject: async (projectId) => {
    try {
      await fetchJson(`/api/projects/${projectId}`, { method: "DELETE" });
      get().removeProject(projectId);
      return true;
    } catch {
      return false;
    }
  },

  setLoading: (value) => {
    set({ isLoading: value });
  },
}));
