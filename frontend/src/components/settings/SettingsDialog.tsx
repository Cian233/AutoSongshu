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
} from "lucide-react";
import { cn } from "../../lib/cn";
import { fetchJson } from "../../lib/api";
import { API_ENDPOINTS } from "../../lib/api-endpoints";
import { useUIStore } from "../../stores/use-ui-store";
import { useAuthorizationStore } from "../../stores/use-authorization-store";
import { useKnowledgeStore } from "../../stores/use-knowledge-store";
import { useModelStore } from "../../stores/use-model-store";
import type { ModelProfile } from "../../stores/use-model-store";
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
    fetchProfiles,
    setActiveProfile,
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
      fetchProfiles().catch(() => {});

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
      const ok = await setActiveProfile(name);
      if (!ok) {
        setSwitchingModel(null);
      }
      // Keep spinner until profiles are re-fetched
      setTimeout(() => setSwitchingModel(null), 600);
    },
    [activeProfile, setActiveProfile],
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
      await fetchProfiles();
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
              switchingModel={switchingModel}
              onSwitch={handleSwitchModel}
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

function ModelsTab({
  profiles,
  activeProfile,
  isLoading,
  switchingModel,
  onSwitch,
}: {
  profiles: ModelProfile[];
  activeProfile: string | null;
  isLoading: boolean;
  switchingModel: string | null;
  onSwitch: (name: string) => Promise<void>;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-[var(--muted)] text-sm">
        正在加载模型配置...
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-[var(--muted)]">
          当前使用单模型配置。要启用多模型切换，请在 YAML 配置文件中添加
          <code className="mx-1 rounded bg-[var(--bg)] px-1.5 py-0.5 text-xs">
            model.profiles
          </code>
          。
        </p>
        <div className="rounded-lg border border-[var(--line)] bg-[var(--bg)] p-4 space-y-2">
          <p className="text-xs text-[var(--muted)]">
            示例配置（configs/pentest.example.yaml）：
          </p>
          <pre className="text-xs text-[var(--text)] overflow-x-auto whitespace-pre">
{`model:
  active: qwen-plus
  profiles:
    - name: qwen-plus
      provider: dashscope
      model_name: qwen3.6-plus
      api_key: \${AUTOSONGSHU_MODEL_API_KEY}
      base_url: \${AUTOSONGSHU_MODEL_BASE_URL}
      tasks: [reasoning, general]
    - name: deepseek
      provider: deepseek
      model_name: deepseek-chat
      api_key: \${DEEPSEEK_API_KEY}
      base_url: https://api.deepseek.com/v1
      tasks: [code_gen, search]`}
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--muted)]">
        选择当前会话使用的模型。切换后立即生效，新消息将使用所选模型。
      </p>
      {profiles.map((profile) => {
        const isActive = profile.name === activeProfile;
        const isSwitching = profile.name === switchingModel;
        return (
          <button
            key={profile.name}
            type="button"
            className={cn(
              "w-full flex items-center gap-4 rounded-lg border p-4 text-left transition-all",
              isActive
                ? "border-[var(--accent)] bg-[var(--accent)]/5"
                : "border-[var(--line)] hover:border-[var(--muted)] hover:bg-[var(--bg)]",
            )}
            onClick={() => onSwitch(profile.name)}
            disabled={isSwitching}
          >
            {/* Active indicator */}
            <div
              className={cn(
                "flex-shrink-0 w-5 h-5 rounded-full border-2 flex items-center justify-center",
                isActive ? "border-[var(--accent)]" : "border-[var(--muted)]",
              )}
            >
              {isActive && <Check className="w-3 h-3 text-[var(--accent)]" />}
            </div>

            {/* Profile info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[var(--text)] truncate">
                  {profile.display_name}
                </span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--bg)] text-[var(--muted)]">
                  {PROVIDER_LABELS[profile.provider] || profile.provider}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-1 text-xs text-[var(--muted)]">
                <span className="truncate">{profile.model_name}</span>
                {profile.temperature !== 1.0 && (
                  <span>temp {profile.temperature}</span>
                )}
                {profile.tasks.length > 0 && (
                  <span className="truncate">
                    {profile.tasks.join(", ")}
                  </span>
                )}
              </div>
            </div>

            {/* Switching spinner */}
            {isSwitching && (
              <RefreshCw className="h-4 w-4 text-[var(--muted)] animate-spin flex-shrink-0" />
            )}
          </button>
        );
      })}
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
