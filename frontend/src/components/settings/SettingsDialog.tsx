// ── Settings Dialog ─────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/templates/index.html —
//   settings modal HTML
// And from /src/autosongshu_agent/web/static/api.js —
//   getConfig(), reloadConfig()
// And from /src/autosongshu_agent/web/static/app.js —
//   settings button wiring, reset logic
//
// Provides a modal dialog for configuring new session defaults:
//   - Configuration file path
//   - Authorization profile selection and management
//   - Engagement name, authorization code, start URL
//   - Allowed hosts
//   - Engagement notes
//   - Skill directories
//   - Knowledge base association
//   - Reload config, save, and reset buttons

import React, { useState, useCallback, useEffect, useRef } from "react";
import { X, RotateCcw, Save, RefreshCw, ExternalLink } from "lucide-react";
import { cn } from "../../lib/cn";
import { fetchJson } from "../../lib/api";
import { API_ENDPOINTS } from "../../lib/api-endpoints";
import { useUIStore } from "../../stores/use-ui-store";
import { useAuthorizationStore } from "../../stores/use-authorization-store";
import { useKnowledgeStore } from "../../stores/use-knowledge-store";
import { normalizeLines } from "../../lib/utils";
import type { AuthorizationRecord } from "../../types/authorization";

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

  // ── Local form state ──────────────────────────────────────────

  const [configPath, setConfigPath] = useState("");
  const [skillDirs, setSkillDirs] = useState("");
  const [selectedAuthProfile, setSelectedAuthProfile] = useState("");
  const [authFeedback, setAuthFeedback] = useState({ text: "", tone: "muted" as "muted" | "success" | "error" });
  const [isReloading, setIsReloading] = useState(false);
  const [isSavingAuth, setIsSavingAuth] = useState(false);

  // ── Refs ──────────────────────────────────────────────────────

  const dialogRef = useRef<HTMLDivElement>(null);
  const initialConfigPathRef = useRef(configPath);

  // ── Load authorizations on open ───────────────────────────────

  useEffect(() => {
    if (!settingsOpen) return;

    async function loadAuths() {
      try {
        const payload = await fetchJson<{ authorizations: AuthorizationRecord[] }>(
          "/api/authorizations",
        );
        setAuthorizations(payload.authorizations || []);
      } catch {
        // Ignore errors
      }
    }
    loadAuths();
  }, [settingsOpen, setAuthorizations]);

  // ── Escape key ────────────────────────────────────────────────

  useEffect(() => {
    if (!settingsOpen) return;

    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSettingsOpen(false);
      }
    }

    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
    };
  }, [settingsOpen, setSettingsOpen]);

  // ── Handlers ──────────────────────────────────────────────────

  const handleReloadConfig = useCallback(async () => {
    setIsReloading(true);
    try {
      const body = configPath ? { config_path: configPath } : {};
      await fetchJson(API_ENDPOINTS.CONFIG_RELOAD, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      window.alert("配置已重新加载成功");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      window.alert(`配置热更新失败：${message}`);
    } finally {
      setIsReloading(false);
    }
  }, [configPath]);

  const handleSaveAuth = useCallback(async () => {
    if (!authorizationDraft.name || !authorizationDraft.authorization || !authorizationDraft.start_url) {
      setAuthFeedback({ text: "请至少填写评估名称、授权编号和起始 URL。", tone: "error" });
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
      // Reload authorizations
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
  }, [
    resetAuthorizationDraft,
    setSelectedKnowledgeBaseIds,
  ]);

  const handleClose = useCallback(() => {
    setSettingsOpen(false);
  }, [setSettingsOpen]);

  const handleBackdropClick = useCallback(() => {
    setSettingsOpen(false);
  }, [setSettingsOpen]);

  // ── Knowledge base toggle ─────────────────────────────────────

  const toggleKnowledgeBase = useCallback(
    (id: string) => {
      const current = new Set(selectedKnowledgeBaseIds);
      if (current.has(id)) {
        current.delete(id);
      } else {
        current.add(id);
      }
      setSelectedKnowledgeBaseIds(Array.from(current));
    },
    [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds],
  );

  // ── Don't render if closed ────────────────────────────────────

  if (!settingsOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleBackdropClick}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        ref={dialogRef}
        className={cn(
          "relative z-50 flex max-h-[85vh] w-full max-w-2xl flex-col",
          "rounded-xl border border-border bg-background shadow-2xl",
          "animate-in fade-in zoom-in-95 duration-200",
        )}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-6 py-4">
          <div>
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              会话默认配置
            </span>
            <h3
              id="settings-title"
              className="text-base font-semibold text-foreground"
            >
              新会话默认配置
            </h3>
          </div>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground hover:text-foreground"
            onClick={handleClose}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body (scrollable) */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {/* Config path */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              配置文件
            </span>
            <input
              type="text"
              value={configPath}
              onChange={(e) => setConfigPath(e.target.value)}
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
              )}
            />
          </label>

          {/* Authorization profile */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              授权配置库
            </span>
            <div className="flex items-center gap-2">
              <select
                value={selectedAuthProfile}
                onChange={(e) => handleAuthProfileChange(e.target.value)}
                className={cn(
                  "flex-1 rounded-md border border-border bg-background px-3 py-2",
                  "text-sm text-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-ring",
                )}
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
                  "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-2",
                  "text-sm text-foreground hover:bg-accent",
                  "disabled:opacity-50",
                )}
                onClick={handleSaveAuth}
                disabled={isSavingAuth}
              >
                {isSavingAuth ? "保存中..." : "保存到库"}
              </button>
            </div>
          </label>

          {/* Authorization feedback */}
          {authFeedback.text && (
            <div
              className={cn(
                "text-sm rounded-md px-3 py-2",
                authFeedback.tone === "error" &&
                  "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400",
                authFeedback.tone === "success" &&
                  "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400",
                authFeedback.tone === "muted" && "text-muted-foreground",
              )}
              role="status"
              aria-live="polite"
            >
              {authFeedback.text}
            </div>
          )}

          {/* Engagement name */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              评估名称
            </span>
            <input
              type="text"
              value={authorizationDraft.name || ""}
              onChange={(e) =>
                updateAuthorizationDraft({ name: e.target.value })
              }
              placeholder="authorized-web-assessment"
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
              )}
            />
          </label>

          {/* Authorization code */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              授权编号
            </span>
            <input
              type="text"
              value={authorizationDraft.authorization || ""}
              onChange={(e) =>
                updateAuthorizationDraft({ authorization: e.target.value })
              }
              placeholder="SEC-2026-001"
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
              )}
            />
          </label>

          {/* Start URL */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              起始 URL
            </span>
            <input
              type="url"
              value={authorizationDraft.start_url || ""}
              onChange={(e) =>
                updateAuthorizationDraft({ start_url: e.target.value })
              }
              placeholder="留空表示无限制，或输入起始 URL"
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
              )}
            />
          </label>

          {/* Allowed hosts */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              允许主机（每行一个，支持 *.example.com）
            </span>
            <textarea
              rows={4}
              value={(authorizationDraft.allowed_hosts || []).join("\n")}
              onChange={(e) =>
                updateAuthorizationDraft({
                  allowed_hosts: normalizeLines(e.target.value),
                })
              }
              placeholder={"留空表示无限制\nexample.com\n*.example.com"}
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
                "resize-none",
              )}
            />
          </label>

          {/* Allow subdomains */}
          <label className="inline-flex items-center gap-2 text-sm text-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={authorizationDraft.allow_subdomains ?? true}
              onChange={(e) =>
                updateAuthorizationDraft({
                  allow_subdomains: e.target.checked,
                })
              }
              className="rounded border-border"
            />
            <span>允许子域名</span>
          </label>

          {/* Engagement notes */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              授权备注
            </span>
            <textarea
              rows={3}
              value={authorizationDraft.notes || ""}
              onChange={(e) =>
                updateAuthorizationDraft({ notes: e.target.value || null })
              }
              placeholder="例如：仅测试登录、账号、密码重置流程。"
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
                "resize-none",
              )}
            />
          </label>

          {/* Skill directories */}
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              额外技能目录（每行一个）
            </span>
            <textarea
              rows={4}
              value={skillDirs}
              onChange={(e) => setSkillDirs(e.target.value)}
              placeholder=".\skills\custom-recon"
              className={cn(
                "w-full rounded-md border border-border bg-background px-3 py-2",
                "text-sm text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
                "resize-none",
              )}
            />
          </label>

          {/* Knowledge base association */}
          <div className="space-y-1.5">
            <span className="text-sm font-medium text-foreground">
              关联知识库（可多选）
            </span>
            {knowledgeBases.length > 0 ? (
              <div className="space-y-1 max-h-40 overflow-y-auto rounded-md border border-border p-2">
                {knowledgeBases.map((kb) => {
                  const isSelected = selectedKnowledgeBaseIds.includes(
                    String(kb.id),
                  );
                  return (
                    <label
                      key={kb.id}
                      className={cn(
                        "flex items-center gap-2 rounded px-2 py-1.5 text-sm cursor-pointer",
                        "hover:bg-accent",
                        isSelected && "bg-accent",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleKnowledgeBase(String(kb.id))}
                        className="rounded border-border"
                      />
                      <span className="text-foreground">{kb.name}</span>
                      <span className="text-muted-foreground text-xs">
                        ({kb.document_count} 文档)
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                暂无知识库
              </p>
            )}
            <a
              href="/knowledge"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-3 w-3" />
              打开知识库页面
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2",
              "text-sm font-medium text-foreground",
              "hover:bg-accent hover:text-accent-foreground",
              "transition-colors duration-150",
              "disabled:opacity-50",
            )}
            onClick={handleReloadConfig}
            disabled={isReloading}
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", isReloading && "animate-spin")}
            />
            重新加载配置
          </button>

          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2",
              "text-sm font-medium text-foreground",
              "hover:bg-accent hover:text-accent-foreground",
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
              "text-sm font-medium bg-primary text-primary-foreground",
              "hover:bg-primary/90",
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

export default SettingsDialog;
