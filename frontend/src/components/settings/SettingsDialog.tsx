// ── Settings Dialog ─────────────────────────────────────────────
// Modal dialog with tabbed layout:
//   Tab 1: Model Configuration — view/switch model profiles
//   Tab 2: Session Defaults — authorization, skills, knowledge base
//
// Fixed: component is now properly mounted in ChatPage.

import React, { useState, useCallback, useEffect, useRef } from "react";
import {
  X,
  RotateCcw,
  Save,
  RefreshCw,
  ExternalLink,
  Cpu,
  Sliders,
  Check,
  Plus,
  Trash2,
} from "lucide-react";
import { cn } from "../../lib/cn";
import { fetchJson } from "../../lib/api";
import { API_ENDPOINTS } from "../../lib/api-endpoints";
import { useUIStore } from "../../stores/use-ui-store";
import { useAuthorizationStore } from "../../stores/use-authorization-store";
import { useKnowledgeStore } from "../../stores/use-knowledge-store";
import { useModelStore } from "../../stores/use-model-store";
import type { ModelProfile, NewProfileInput } from "../../stores/use-model-store";
import { normalizeLines } from "../../lib/utils";
import type { AuthorizationRecord, AuthorizationDraft } from "../../types/authorization";

// ── Tab type ─────────────────────────────────────────────────────

type SettingsTab = "models" | "session";

const TABS: { key: SettingsTab; label: string; icon: React.ReactNode }[] = [
  { key: "models", label: "模型配置", icon: <Cpu className="w-4 h-4" /> },
  { key: "session", label: "会话默认配置", icon: <Sliders className="w-4 h-4" /> },
];

// ── Provider display names ───────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure OpenAI",
  anthropic: "Anthropic",
  dashscope: "阿里云 DashScope",
  deepseek: "DeepSeek",
  zhipu: "智谱 AI",
  moonshot: "Moonshot (月之暗面)",
  siliconflow: "SiliconFlow",
  custom: "自定义",
};

// ── Component ───────────────────────────────────────────────────

export const SettingsDialog: React.FC = () => {
  const settingsOpen = useUIStore((state) => state.settingsOpen);
  const setSettingsOpen = useUIStore((state) => state.setSettingsOpen);

  const {
    authorizations,
    authorizationDraft,
    updateAuthorizationDraft,
    resetAuthorizationDraft,
    setAuthorizations,
    fillDraftFromRecord,
  } = useAuthorizationStore();

  const {
    knowledgeBases,
    selectedKnowledgeBaseIds,
    setSelectedKnowledgeBaseIds,
  } = useKnowledgeStore();

  const {
    profiles,
    activeProfile,
    isLoading: modelsLoading,
    isSaving: modelsSaving,
    fetchProfiles,
    setActiveProfile,
    addProfile,
    deleteProfile,
    updateProfile,
  } = useModelStore();

  // ── Local state ───────────────────────────────────────────────

  const [activeTab, setActiveTab] = useState<SettingsTab>("models");
  const [configPath, setConfigPath] = useState("");
  const [skillDirs, setSkillDirs] = useState("");
  const [selectedAuthProfile, setSelectedAuthProfile] = useState("");
  const [authFeedback, setAuthFeedback] = useState({
    text: "",
    tone: "muted" as "muted" | "success" | "error",
  });
  const [isReloading, setIsReloading] = useState(false);
  const [isSavingAuth, setIsSavingAuth] = useState(false);
  const [switchingModel, setSwitchingModel] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const initialConfigPathRef = useRef(configPath);

  // ── Load data on open ─────────────────────────────────────────

  useEffect(() => {
    if (!settingsOpen) return;

    async function loadData() {
      // Load models
      fetchProfiles(configPath || undefined).catch(() => {});

      // Load authorizations
      try {
        const payload = await fetchJson<{ authorizations: AuthorizationRecord[] }>(
          "/api/authorizations",
        );
        setAuthorizations(payload.authorizations || []);
      } catch {
        // Ignore
      }
    }
    loadData();
  }, [settingsOpen, fetchProfiles, setAuthorizations]);

  // ── Escape key ────────────────────────────────────────────────

  useEffect(() => {
    if (!settingsOpen) return;
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setSettingsOpen(false);
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [settingsOpen, setSettingsOpen]);

  // ── Handlers ──────────────────────────────────────────────────

  const handleSwitchModel = useCallback(
    async (name: string) => {
      if (name === activeProfile) return;
      setSwitchingModel(name);
      const ok = await setActiveProfile(name, configPath || undefined);
      if (!ok) {
        setSwitchingModel(null);
      }
      // Keep spinner until profiles are re-fetched
      setTimeout(() => setSwitchingModel(null), 600);
    },
    [activeProfile, setActiveProfile, configPath],
  );

  const handleReloadConfig = useCallback(async () => {
    setIsReloading(true);
    try {
      const body = configPath ? { config_path: configPath } : {};
      await fetchJson(API_ENDPOINTS.CONFIG_RELOAD, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      // Re-fetch models after config reload
      await fetchProfiles(configPath || undefined);
      window.alert("配置已重新加载成功");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      window.alert(`配置热更新失败：${message}`);
    } finally {
      setIsReloading(false);
    }
  }, [configPath, fetchProfiles]);

  const handleSaveAuth = useCallback(async () => {
    if (
      !authorizationDraft.name ||
      !authorizationDraft.authorization ||
      !authorizationDraft.start_url
    ) {
      setAuthFeedback({
        text: "请至少填写评估名称、授权编号和起始 URL。",
        tone: "error",
      });
      return;
    }
    setIsSavingAuth(true);
    setAuthFeedback({ text: "正在保存授权配置...", tone: "muted" });
    try {
      const created = await fetchJson<AuthorizationRecord>(
        "/api/authorizations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(authorizationDraft),
        },
      );
      const payload = await fetchJson<{ authorizations: AuthorizationRecord[] }>(
        "/api/authorizations",
      );
      setAuthorizations(payload.authorizations || []);
      setSelectedAuthProfile(String(created.id));
      setAuthFeedback({
        text: `已保存到授权配置库：${created.name}`,
        tone: "success",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setAuthFeedback({ text: `保存失败：${message}`, tone: "error" });
    } finally {
      setIsSavingAuth(false);
    }
  }, [authorizationDraft, setAuthorizations]);

  const handleAuthProfileChange = useCallback(
    (id: string) => {
      setSelectedAuthProfile(id);
      if (!id) {
        setAuthFeedback({ text: "新会话会使用当前表单内容。", tone: "muted" });
        return;
      }
      const record = authorizations.find((item) => String(item.id) === id);
      if (record) {
        fillDraftFromRecord(record);
        setAuthFeedback({
          text: `已载入授权配置：${record.name}`,
          tone: "success",
        });
      }
    },
    [authorizations, fillDraftFromRecord],
  );

  const handleReset = useCallback(() => {
    setSelectedAuthProfile("");
    setConfigPath(initialConfigPathRef.current);
    setSkillDirs("");
    setSelectedKnowledgeBaseIds([]);
    resetAuthorizationDraft();
    setAuthFeedback({ text: "已重置为默认设置。", tone: "success" });
  }, [resetAuthorizationDraft, setSelectedKnowledgeBaseIds]);

  const handleClose = useCallback(() => setSettingsOpen(false), [setSettingsOpen]);

  const toggleKnowledgeBase = useCallback(
    (id: string) => {
      const current = new Set(selectedKnowledgeBaseIds);
      if (current.has(id)) current.delete(id);
      else current.add(id);
      setSelectedKnowledgeBaseIds(Array.from(current));
    },
    [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds],
  );

  // ── Don't render if closed ────────────────────────────────────

  if (!settingsOpen) return null;

  // ── Shared input classes ───────────────────────────────────────

  const inputCls = cn(
    "w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 py-2",
    "text-sm text-[var(--text)] placeholder:text-[var(--muted)]",
    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)]",
  );
  const labelCls = "block space-y-1.5";
  const labelTitleCls = "text-sm font-medium text-[var(--text)]";

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        ref={dialogRef}
        className={cn(
          "relative z-50 flex max-h-[85vh] w-full max-w-2xl flex-col",
          "rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-2xl",
        )}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        {/* ── Header ──────────────────────────────────────────── */}
        <div className="flex items-center justify-between border-b border-[var(--line)] px-6 py-4">
          <h3 id="settings-title" className="text-base font-semibold text-[var(--text)]">
            设置
          </h3>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md p-1 text-[var(--muted)] hover:text-[var(--text)]"
            onClick={handleClose}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* ── Tabs ────────────────────────────────────────────── */}
        <div className="flex border-b border-[var(--line)] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={cn(
                "flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                activeTab === tab.key
                  ? "border-[var(--accent)] text-[var(--text)]"
                  : "border-transparent text-[var(--muted)] hover:text-[var(--text)]",
              )}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* ── Body ────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {activeTab === "models" && (
            <ModelsTab
              profiles={profiles}
              activeProfile={activeProfile}
              isLoading={modelsLoading}
              isSaving={modelsSaving}
              switchingModel={switchingModel}
              onSwitch={handleSwitchModel}
              onAdd={(input) => addProfile(input, configPath || undefined)}
              onDelete={(name) => deleteProfile(name, configPath || undefined)}
              onUpdate={(name, patch) =>
                updateProfile(name, patch, configPath || undefined)
              }
            />
          )}

          {activeTab === "session" && (
            <SessionTab
              configPath={configPath}
              setConfigPath={setConfigPath}
              selectedAuthProfile={selectedAuthProfile}
              authorizations={authorizations}
              authFeedback={authFeedback}
              isSavingAuth={isSavingAuth}
              authorizationDraft={authorizationDraft}
              updateAuthorizationDraft={updateAuthorizationDraft}
              onAuthProfileChange={handleAuthProfileChange}
              onSaveAuth={handleSaveAuth}
              skillDirs={skillDirs}
              setSkillDirs={setSkillDirs}
              knowledgeBases={knowledgeBases}
              selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
              onToggleKnowledgeBase={toggleKnowledgeBase}
              inputCls={inputCls}
              labelCls={labelCls}
              labelTitleCls={labelTitleCls}
            />
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────── */}
        <div className="flex items-center justify-end gap-2 border-t border-[var(--line)] px-6 py-4">
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-4 py-2",
              "text-sm font-medium text-[var(--text)]",
              "hover:bg-[var(--sidebar-hover)]",
              "transition-colors duration-150",
              "disabled:opacity-50",
            )}
            onClick={handleReloadConfig}
            disabled={isReloading}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isReloading && "animate-spin")} />
            重新加载配置
          </button>

          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-4 py-2",
              "text-sm font-medium text-[var(--text)]",
              "hover:bg-[var(--sidebar-hover)]",
              "transition-colors duration-150",
            )}
            onClick={handleReset}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            重置
          </button>

          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-4 py-2",
              "text-sm font-medium bg-[var(--accent)] text-white",
              "hover:opacity-90",
              "transition-colors duration-150",
            )}
            onClick={handleClose}
          >
            <Save className="h-3.5 w-3.5" />
            完成
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Models Tab ───────────────────────────────────────────────────

const ALL_TASKS = [
  "reasoning", "memory", "search", "tool_planning", "code_gen", "knowledge", "general",
];

const COMPACTION_FIELDS = [
  { key: "compact_after_tokens", label: "触发 Token 数", hint: "上下文超过此值触发压缩", min: 1000, max: 2000000 },
  { key: "compact_after_turns", label: "触发轮数", hint: "对话轮数超过此值触发压缩", min: 2, max: 100 },
  { key: "context_window_tokens", label: "上下文窗口", hint: "模型上下文窗口大小 (Token)", min: 8000, max: 2000000 },
  { key: "keep_last_turns", label: "保留最后轮数", hint: "压缩后保留最后几轮完整对话", min: 1, max: 20 },
  { key: "min_turns", label: "最少轮数", hint: "至少多少轮后才允许压缩", min: 1, max: 50 },
];

function ModelsTab({
  profiles,
  activeProfile,
  isLoading,
  isSaving,
  switchingModel,
  onSwitch,
  onAdd,
  onDelete,
  onUpdate,
}: {
  profiles: ModelProfile[];
  activeProfile: string | null;
  isLoading: boolean;
  isSaving: boolean;
  switchingModel: string | null;
  onSwitch: (name: string) => Promise<void>;
  onAdd: (input: NewProfileInput) => Promise<boolean>;
  onDelete: (name: string) => Promise<boolean>;
  onUpdate: (name: string, patch: Record<string, unknown>) => Promise<boolean>;
}) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null);
  const [compactionEdits, setCompactionEdits] = useState<Record<string, Record<string, number | boolean>>>({});
  const [newProfile, setNewProfile] = useState<NewProfileInput>({
    name: "",
    model_name: "",
    provider: "custom",
    base_url: "",
    api_key: "",
    temperature: 1.0,
    top_p: 0.95,
    tasks: ["general"],
  });
  const [addError, setAddError] = useState("");

  const inputCls = cn(
    "w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 py-2",
    "text-sm text-[var(--text)] placeholder:text-[var(--muted)]",
    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)]",
  );

  const handleAdd = useCallback(async () => {
    if (!newProfile.name.trim() || !newProfile.model_name.trim()) {
      setAddError("名称和模型 ID 为必填项");
      return;
    }
    setAddError("");
    const ok = await onAdd(newProfile);
    if (ok) {
      setShowAddForm(false);
      setNewProfile({
        name: "", model_name: "", provider: "custom",
        base_url: "", api_key: "", temperature: 1.0, top_p: 0.95,
        tasks: ["general"],
      });
    } else {
      setAddError("添加失败，请检查名称是否重复");
    }
  }, [newProfile, onAdd]);

  const handleDelete = useCallback(
    async (name: string) => {
      if (!confirm(`确定删除模型配置「${name}」？`)) return;
      await onDelete(name);
    },
    [onDelete],
  );

  const toggleTask = useCallback((task: string) => {
    setNewProfile((prev) => {
      const tasks = new Set(prev.tasks || []);
      if (tasks.has(task)) tasks.delete(task);
      else tasks.add(task);
      return { ...prev, tasks: Array.from(tasks) };
    });
  }, []);

  const handleSaveCompaction = useCallback(async (profileName: string) => {
    const edits = compactionEdits[profileName];
    if (!edits) return;
    const ok = await onUpdate(profileName, { compaction: edits });
    if (ok) {
      setCompactionEdits((prev) => {
        const next = { ...prev };
        delete next[profileName];
        return next;
      });
    }
  }, [compactionEdits, onUpdate]);

  const getCompactionValue = useCallback((profile: ModelProfile, key: string, fallback: number) => {
    const edit = compactionEdits[profile.name]?.[key];
    if (edit !== undefined) return edit as number;
    return (profile.compaction?.[key] as number) ?? fallback;
  }, [compactionEdits]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-[var(--muted)] text-sm">
        正在加载模型配置...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header with add button */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--muted)]">
          {profiles.length > 0
            ? "点击切换模型，新消息将使用所选模型。"
            : "尚未配置模型，点击右侧按钮添加。"}
        </p>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium",
            "border border-[var(--line)] text-[var(--text)]",
            "hover:bg-[var(--sidebar-hover)] transition-colors",
            showAddForm && "bg-[var(--sidebar-hover)]",
          )}
          onClick={() => { setShowAddForm(!showAddForm); setAddError(""); }}
          disabled={isSaving}
        >
          <Plus className="w-3.5 h-3.5" />
          添加模型
        </button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <div className="rounded-lg border border-[var(--line)] bg-[var(--bg)] p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--text)]">名称 *</span>
              <input
                type="text"
                value={newProfile.name}
                onChange={(e) => setNewProfile((p) => ({ ...p, name: e.target.value }))}
                placeholder="my-model"
                className={inputCls}
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--text)]">模型 ID *</span>
              <input
                type="text"
                value={newProfile.model_name}
                onChange={(e) => setNewProfile((p) => ({ ...p, model_name: e.target.value }))}
                placeholder="gpt-4o / deepseek-chat"
                className={inputCls}
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--text)]">Provider</span>
              <select
                value={newProfile.provider}
                onChange={(e) => setNewProfile((p) => ({ ...p, provider: e.target.value }))}
                className={inputCls}
              >
                {Object.entries(PROVIDER_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-medium text-[var(--text)]">显示名称</span>
              <input
                type="text"
                value={newProfile.display_name || ""}
                onChange={(e) => setNewProfile((p) => ({ ...p, display_name: e.target.value || undefined }))}
                placeholder="留空则使用名称"
                className={inputCls}
              />
            </label>
            <label className="space-y-1 col-span-2">
              <span className="text-xs font-medium text-[var(--text)]">Base URL</span>
              <input
                type="text"
                value={newProfile.base_url || ""}
                onChange={(e) => setNewProfile((p) => ({ ...p, base_url: e.target.value || undefined }))}
                placeholder="https://api.openai.com/v1"
                className={inputCls}
              />
            </label>
            <label className="space-y-1 col-span-2">
              <span className="text-xs font-medium text-[var(--text)]">API Key</span>
              <input
                type="password"
                value={newProfile.api_key || ""}
                onChange={(e) => setNewProfile((p) => ({ ...p, api_key: e.target.value || undefined }))}
                placeholder="sk-..."
                className={inputCls}
              />
            </label>
          </div>

          {/* Task selection */}
          <div className="space-y-1.5">
            <span className="text-xs font-medium text-[var(--text)]">适用任务</span>
            <div className="flex flex-wrap gap-1.5">
              {ALL_TASKS.map((task) => {
                const selected = (newProfile.tasks || []).includes(task);
                return (
                  <button
                    key={task}
                    type="button"
                    className={cn(
                      "text-xs px-2 py-1 rounded-md border transition-colors",
                      selected
                        ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                        : "border-[var(--line)] text-[var(--muted)] hover:text-[var(--text)]",
                    )}
                    onClick={() => toggleTask(task)}
                  >
                    {task}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Error + Actions */}
          {addError && (
            <p className="text-xs text-red-500">{addError}</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              className="text-xs text-[var(--muted)] hover:text-[var(--text)]"
              onClick={() => setShowAddForm(false)}
            >
              取消
            </button>
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium",
                "bg-[var(--accent)] text-white hover:opacity-90",
                "disabled:opacity-50",
              )}
              onClick={handleAdd}
              disabled={isSaving || !newProfile.name.trim() || !newProfile.model_name.trim()}
            >
              {isSaving ? "保存中..." : "确认添加"}
            </button>
          </div>
        </div>
      )}

      {/* Profile list */}
      {profiles.length === 0 && !showAddForm ? (
        <div className="text-center py-8 text-sm text-[var(--muted)]">
          暂无模型配置，点击上方「添加模型」开始。
        </div>
      ) : (
        <div className="space-y-2">
          {profiles.map((profile) => {
            const isActive = profile.name === activeProfile;
            const isSwitching = profile.name === switchingModel;
            const isExpanded = expandedProfile === profile.name;
            const hasEdits = !!compactionEdits[profile.name];
            return (
              <div
                key={profile.name}
                className={cn(
                  "rounded-lg border transition-all",
                  isActive
                    ? "border-[var(--accent)] bg-[var(--accent)]/5"
                    : "border-[var(--line)] hover:border-[var(--muted)]",
                )}
              >
                {/* Main row */}
                <div className="flex items-center gap-3 p-3">
                  <button
                    type="button"
                    className="flex-1 flex items-center gap-3 text-left min-w-0"
                    onClick={() => onSwitch(profile.name)}
                    disabled={isSwitching}
                  >
                    <div
                      className={cn(
                        "flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center",
                        isActive ? "border-[var(--accent)]" : "border-[var(--muted)]",
                      )}
                    >
                      {isActive && <Check className="w-2.5 h-2.5 text-[var(--accent)]" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--text)] truncate">
                          {profile.display_name}
                        </span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--bg)] text-[var(--muted)]">
                          {PROVIDER_LABELS[profile.provider] || profile.provider}
                        </span>
                        {profile.compaction && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
                            自定义压缩
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-[var(--muted)]">
                        <span className="truncate">{profile.model_name}</span>
                        {profile.tasks.length > 0 && (
                          <span className="truncate">{profile.tasks.join(", ")}</span>
                        )}
                      </div>
                    </div>
                    {isSwitching && (
                      <RefreshCw className="h-3.5 w-3.5 text-[var(--muted)] animate-spin flex-shrink-0" />
                    )}
                  </button>

                  {/* Expand compaction */}
                  <button
                    type="button"
                    className={cn(
                      "flex-shrink-0 p-1.5 rounded-md text-[var(--muted)]",
                      "hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
                      "transition-colors",
                      isExpanded && "text-[var(--accent)]",
                    )}
                    onClick={(e) => { e.stopPropagation(); setExpandedProfile(isExpanded ? null : profile.name); }}
                    title="上下文压缩设置"
                  >
                    <Sliders className="w-3.5 h-3.5" />
                  </button>

                  {/* Delete */}
                  <button
                    type="button"
                    className={cn(
                      "flex-shrink-0 p-1.5 rounded-md text-[var(--muted)]",
                      "hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20",
                      "transition-colors",
                    )}
                    onClick={(e) => { e.stopPropagation(); handleDelete(profile.name); }}
                    title="删除此模型"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Expanded compaction settings */}
                {isExpanded && (
                  <div className="border-t border-[var(--line)] px-4 py-3 space-y-2 bg-[var(--bg)]/50">
                    <p className="text-xs text-[var(--muted)]">
                      上下文压缩设置（留空使用全局默认值，修改后点击保存）
                    </p>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                      {COMPACTION_FIELDS.map((field) => (
                        <label key={field.key} className="flex items-center justify-between gap-2">
                          <span className="text-xs text-[var(--text)] whitespace-nowrap">{field.label}</span>
                          <input
                            type="number"
                            value={getCompactionValue(profile, field.key, 0) || ""}
                            onChange={(e) => {
                              const val = parseInt(e.target.value);
                              if (!isNaN(val)) {
                                setCompactionEdits((prev) => ({
                                  ...prev,
                                  [profile.name]: { ...(prev[profile.name] || {}), [field.key]: val },
                                }));
                              }
                            }}
                            placeholder="默认"
                            min={field.min}
                            max={field.max}
                            className={cn(inputCls, "w-24 text-right text-xs")}
                          />
                        </label>
                      ))}
                    </div>
                    <div className="flex justify-end pt-1">
                      <button
                        type="button"
                        className={cn(
                          "text-xs px-3 py-1 rounded-md font-medium transition-colors",
                          hasEdits
                            ? "bg-[var(--accent)] text-white hover:opacity-90"
                            : "bg-[var(--line)] text-[var(--muted)]",
                        )}
                        onClick={() => handleSaveCompaction(profile.name)}
                        disabled={!hasEdits || isSaving}
                      >
                        {isSaving ? "保存中..." : "保存压缩设置"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Session Tab ─────────────────────────────────────────────────

function SessionTab({
  configPath,
  setConfigPath,
  selectedAuthProfile,
  authorizations,
  authFeedback,
  isSavingAuth,
  authorizationDraft,
  updateAuthorizationDraft,
  onAuthProfileChange,
  onSaveAuth,
  skillDirs,
  setSkillDirs,
  knowledgeBases,
  selectedKnowledgeBaseIds,
  onToggleKnowledgeBase,
  inputCls,
  labelCls,
  labelTitleCls,
}: {
  configPath: string;
  setConfigPath: (v: string) => void;
  selectedAuthProfile: string;
  authorizations: AuthorizationRecord[];
  authFeedback: { text: string; tone: string };
  isSavingAuth: boolean;
  authorizationDraft: AuthorizationDraft;
  updateAuthorizationDraft: (patch: Partial<AuthorizationDraft>) => void;
  onAuthProfileChange: (id: string) => void;
  onSaveAuth: () => void;
  skillDirs: string;
  setSkillDirs: (v: string) => void;
  knowledgeBases: { id: string | number; name: string; document_count: number }[];
  selectedKnowledgeBaseIds: string[];
  onToggleKnowledgeBase: (id: string) => void;
  inputCls: string;
  labelCls: string;
  labelTitleCls: string;
}) {
  return (
    <div className="space-y-5">
      {/* Config path */}
      <label className={labelCls}>
        <span className={labelTitleCls}>配置文件</span>
        <input
          type="text"
          value={configPath}
          onChange={(e) => setConfigPath(e.target.value)}
          className={inputCls}
        />
      </label>

      {/* Authorization profile */}
      <label className={labelCls}>
        <span className={labelTitleCls}>授权配置库</span>
        <div className="flex items-center gap-2">
          <select
            value={selectedAuthProfile}
            onChange={(e) => onAuthProfileChange(e.target.value)}
            className={cn(inputCls, "flex-1")}
          >
            <option value="">使用当前表单内容</option>
            {authorizations.map((auth) => (
              <option key={auth.id} value={String(auth.id)}>
                {auth.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-3 py-2",
              "text-sm text-[var(--text)] hover:bg-[var(--sidebar-hover)]",
              "disabled:opacity-50",
            )}
            onClick={onSaveAuth}
            disabled={isSavingAuth}
          >
            {isSavingAuth ? "保存中..." : "保存到库"}
          </button>
        </div>
      </label>

      {/* Auth feedback */}
      {authFeedback.text && (
        <div
          className={cn(
            "text-sm rounded-md px-3 py-2",
            authFeedback.tone === "error" &&
              "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400",
            authFeedback.tone === "success" &&
              "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400",
            authFeedback.tone === "muted" && "text-[var(--muted)]",
          )}
          role="status"
          aria-live="polite"
        >
          {authFeedback.text}
        </div>
      )}

      {/* Engagement fields */}
      <label className={labelCls}>
        <span className={labelTitleCls}>评估名称</span>
        <input
          type="text"
          value={authorizationDraft.name || ""}
          onChange={(e) => updateAuthorizationDraft({ name: e.target.value })}
          placeholder="authorized-web-assessment"
          className={inputCls}
        />
      </label>

      <label className={labelCls}>
        <span className={labelTitleCls}>授权编号</span>
        <input
          type="text"
          value={authorizationDraft.authorization || ""}
          onChange={(e) => updateAuthorizationDraft({ authorization: e.target.value })}
          placeholder="SEC-2026-001"
          className={inputCls}
        />
      </label>

      <label className={labelCls}>
        <span className={labelTitleCls}>起始 URL</span>
        <input
          type="url"
          value={authorizationDraft.start_url || ""}
          onChange={(e) => updateAuthorizationDraft({ start_url: e.target.value })}
          placeholder="留空表示无限制，或输入起始 URL"
          className={inputCls}
        />
      </label>

      <label className={labelCls}>
        <span className={labelTitleCls}>允许主机（每行一个，支持 *.example.com）</span>
        <textarea
          rows={3}
          value={(authorizationDraft.allowed_hosts || []).join("\n")}
          onChange={(e) =>
            updateAuthorizationDraft({ allowed_hosts: normalizeLines(e.target.value) })
          }
          placeholder={"留空表示无限制\nexample.com\n*.example.com"}
          className={cn(inputCls, "resize-none")}
        />
      </label>

      <label className="inline-flex items-center gap-2 text-sm text-[var(--text)] cursor-pointer">
        <input
          type="checkbox"
          checked={authorizationDraft.allow_subdomains ?? true}
          onChange={(e) => updateAuthorizationDraft({ allow_subdomains: e.target.checked })}
          className="rounded border-[var(--line)]"
        />
        <span>允许子域名</span>
      </label>

      <label className={labelCls}>
        <span className={labelTitleCls}>授权备注</span>
        <textarea
          rows={2}
          value={authorizationDraft.notes || ""}
          onChange={(e) => updateAuthorizationDraft({ notes: e.target.value || null })}
          placeholder="例如：仅测试登录、账号、密码重置流程。"
          className={cn(inputCls, "resize-none")}
        />
      </label>

      {/* Skill directories */}
      <label className={labelCls}>
        <span className={labelTitleCls}>额外技能目录（每行一个）</span>
        <textarea
          rows={3}
          value={skillDirs}
          onChange={(e) => setSkillDirs(e.target.value)}
          placeholder=".\skills\custom-recon"
          className={cn(inputCls, "resize-none")}
        />
      </label>

      {/* Knowledge base */}
      <div className="space-y-1.5">
        <span className={labelTitleCls}>关联知识库（可多选）</span>
        {knowledgeBases.length > 0 ? (
          <div className="space-y-1 max-h-32 overflow-y-auto rounded-md border border-[var(--line)] p-2">
            {knowledgeBases.map((kb) => {
              const isSelected = selectedKnowledgeBaseIds.includes(String(kb.id));
              return (
                <label
                  key={kb.id}
                  className={cn(
                    "flex items-center gap-2 rounded px-2 py-1.5 text-sm cursor-pointer",
                    "hover:bg-[var(--sidebar-hover)]",
                    isSelected && "bg-[var(--sidebar-hover)]",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleKnowledgeBase(String(kb.id))}
                    className="rounded border-[var(--line)]"
                  />
                  <span className="text-[var(--text)]">{kb.name}</span>
                  <span className="text-[var(--muted)] text-xs">
                    ({kb.document_count} 文档)
                  </span>
                </label>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">暂无知识库</p>
        )}
        <a
          href="/knowledge"
          className="inline-flex items-center gap-1 text-sm text-[var(--muted)] hover:text-[var(--text)]"
        >
          <ExternalLink className="h-3 w-3" />
          打开知识库页面
        </a>
      </div>
    </div>
  );
}

export default SettingsDialog;
