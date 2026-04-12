// ── KnowledgeListPage ───────────────────────────────────────────
// Migrated from knowledge-list.js + knowledge.html
//
// Knowledge base list page with:
//   - Overview stats (bases, documents, chunks)
//   - Search / filter
//   - Create knowledge base form
//   - Card grid of knowledge bases with navigation to detail

import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  RefreshCw,
  Plus,
  Database,
  FileText,
  Layers,
  ArrowRight,
  Trash2,
  AlertCircle,
} from "lucide-react";
import { cn } from "../lib/cn";
import { fetchJson } from "../lib/api";
import { API_ENDPOINTS } from "../lib/api-endpoints";
import { useKnowledgeStore } from "../stores/use-knowledge-store";
import type { KnowledgeBaseSummary } from "../types/knowledge";

// ── Helpers ─────────────────────────────────────────────────────

function formatDate(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatCount(value?: number | null): string {
  return Number(value || 0).toLocaleString();
}

function shortId(value?: string, maxLength = 12): string {
  const text = String(value || "");
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function baseDescription(base?: KnowledgeBaseSummary): string {
  const description = String(base?.description || "").trim();
  return description || "未填写描述";
}

// ── Component ───────────────────────────────────────────────────

export default function KnowledgeListPage() {
  const navigate = useNavigate();

  const { knowledgeBases, setKnowledgeBases } = useKnowledgeStore();

  const [keyword, setKeyword] = useState("");
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Filtered bases ────────────────────────────────────────────

  const filteredBases = keyword.trim()
    ? knowledgeBases.filter((item) => {
        const kw = keyword.trim().toLowerCase();
        return (
          item.name.toLowerCase().includes(kw) ||
          (item.description || "").toLowerCase().includes(kw)
        );
      })
    : knowledgeBases;

  // ── Stats ─────────────────────────────────────────────────────

  const totalBases = knowledgeBases.length;
  const totalDocs = knowledgeBases.reduce(
    (sum, item) => sum + Number(item.document_count || 0),
    0,
  );
  const totalChunks = knowledgeBases.reduce(
    (sum, item) => sum + Number(item.chunk_count || 0),
    0,
  );

  // ── Refresh ───────────────────────────────────────────────────

  const refreshBases = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchJson<{ items: KnowledgeBaseSummary[] }>(
        API_ENDPOINTS.KNOWLEDGE_BASES,
      );
      setKnowledgeBases(payload.items || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [setKnowledgeBases]);

  useEffect(() => {
    refreshBases();
  }, [refreshBases]);

  // ── Create base ───────────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    const name = createName.trim();
    if (!name) {
      window.alert("请输入知识库名称");
      return;
    }

    setIsCreating(true);
    try {
      await fetchJson(API_ENDPOINTS.KNOWLEDGE_BASES, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description: createDescription.trim() || null,
        }),
      });
      setCreateName("");
      setCreateDescription("");
      await refreshBases();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      window.alert(message);
    } finally {
      setIsCreating(false);
    }
  }, [createName, createDescription, refreshBases]);

  // ── Delete base ───────────────────────────────────────────────

  const handleDelete = useCallback(
    async (e: React.MouseEvent, baseId: string) => {
      e.stopPropagation();
      e.preventDefault();
      if (!window.confirm("确认删除这个知识库及其全部文档吗？")) return;

      try {
        await fetchJson(`/api/knowledge/bases/${encodeURIComponent(baseId)}`, {
          method: "DELETE",
        });
        await refreshBases();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        window.alert(message);
      }
    },
    [refreshBases],
  );

  // ── Navigate to detail ────────────────────────────────────────

  const handleCardClick = useCallback(
    (baseId: string) => {
      navigate(`/knowledge/bases/${encodeURIComponent(baseId)}/documents`);
    },
    [navigate],
  );

  // ── Create on Enter ───────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleCreate();
      }
    },
    [handleCreate],
  );

  // ── Render ────────────────────────────────────────────────────

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)]">
      {/* Header */}
      <header className="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-[var(--line)] bg-[var(--panel)] px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white text-xs font-bold">
            KB
          </div>
          <div>
            <p className="text-xs text-[var(--muted)] font-medium tracking-wide uppercase">
              Knowledge Base
            </p>
            <h1 className="text-base font-semibold text-[var(--text)]">
              知识库工作台
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <input
              type="search"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索知识库名称"
              className={cn(
                "w-56 rounded-md border border-[var(--line)] bg-[var(--panel)] py-1.5 pl-8 pr-3",
                "text-sm text-[var(--text)] placeholder:text-[var(--muted-soft)]",
                "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent",
              )}
            />
          </div>

          <button
            type="button"
            onClick={refreshBases}
            disabled={isLoading}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-3 py-1.5",
              "text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
              "transition-colors duration-150 disabled:opacity-50",
            )}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            刷新
          </button>

          <a
            href="/"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-3 py-1.5",
              "text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
              "transition-colors duration-150",
            )}
          >
            返回对话
          </a>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-6 space-y-6">
        {/* Overview Section */}
        <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-sm)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-2">
              <h2 className="text-lg font-semibold text-[var(--text)]">
                知识沉淀与检索管理
              </h2>
              <p className="text-sm text-[var(--muted)]">
                支持创建知识库、导入文档、命中测试，并与当前对话会话绑定复用。
              </p>
              <div className="flex items-center gap-6 pt-2">
                <article className="flex flex-col">
                  <span className="text-xs text-[var(--muted)]">知识库</span>
                  <strong className="text-xl font-bold text-[var(--text)]">
                    {formatCount(totalBases)}
                  </strong>
                </article>
                <article className="flex flex-col">
                  <span className="text-xs text-[var(--muted)]">文档</span>
                  <strong className="text-xl font-bold text-[var(--text)]">
                    {formatCount(totalDocs)}
                  </strong>
                </article>
                <article className="flex flex-col">
                  <span className="text-xs text-[var(--muted)]">分片</span>
                  <strong className="text-xl font-bold text-[var(--text)]">
                    {formatCount(totalChunks)}
                  </strong>
                </article>
              </div>
            </div>

            {/* Create form */}
            <div className="flex flex-col gap-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-3 lg:min-w-[320px]">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-[var(--text-secondary)]">
                  知识库名称
                </span>
                <input
                  type="text"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="例如：产品手册 / FAQ / 规章制度"
                  className={cn(
                    "w-full rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5",
                    "text-sm text-[var(--text)] placeholder:text-[var(--muted-soft)]",
                    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent",
                  )}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-[var(--text-secondary)]">
                  描述（可选）
                </span>
                <input
                  type="text"
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="用途、范围、维护负责人"
                  className={cn(
                    "w-full rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5",
                    "text-sm text-[var(--text)] placeholder:text-[var(--muted-soft)]",
                    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent",
                  )}
                />
              </label>
              <button
                type="button"
                onClick={handleCreate}
                disabled={isCreating}
                className={cn(
                  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5",
                  "text-sm font-medium text-white",
                  "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
                  "transition-colors duration-150 disabled:opacity-50",
                )}
              >
                <Plus className="h-3.5 w-3.5" />
                {isCreating ? "创建中..." : "创建知识库"}
              </button>
            </div>
          </div>
        </section>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--danger)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Base list header */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--text)]">
            知识库列表
          </h3>
          <span className="text-xs text-[var(--muted)]">
            {keyword
              ? `${filteredBases.length} / ${knowledgeBases.length}`
              : `${filteredBases.length} 个`}
          </span>
        </div>

        {/* Base card grid */}
        {filteredBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[var(--line)] py-16">
            <Database className="h-10 w-10 text-[var(--muted-soft)] mb-3" />
            <h4 className="text-sm font-medium text-[var(--text-secondary)]">
              {keyword ? "没有匹配的知识库" : "暂无知识库"}
            </h4>
            <p className="text-xs text-[var(--muted)] mt-1">
              {keyword
                ? "你可以清空搜索词，或者先创建新的知识库。"
                : "先创建一个知识库，再导入文档开始沉淀经验。"}
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredBases.map((item) => (
              <article
                key={item.id}
                onClick={() => handleCardClick(String(item.id))}
                className={cn(
                  "group relative flex flex-col rounded-xl border border-[var(--line)] bg-[var(--panel)]",
                  "p-4 shadow-[var(--shadow-xs)] cursor-pointer",
                  "hover:shadow-[var(--shadow-md)] hover:border-[var(--line-strong)]",
                  "transition-all duration-200",
                )}
              >
                {/* Head */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <strong
                    className="text-sm font-semibold text-[var(--text)] truncate"
                    title={item.name || item.id}
                  >
                    {item.name || item.id}
                  </strong>
                  <span className="inline-flex items-center gap-1 shrink-0 rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
                    <FileText className="h-3 w-3" />
                    {formatCount(item.document_count)} 文档
                  </span>
                </div>

                {/* Description */}
                <p className="text-xs text-[var(--muted)] line-clamp-2 mb-3 flex-1">
                  {baseDescription(item)}
                </p>

                {/* Stats */}
                <div className="flex items-center gap-3 text-xs text-[var(--muted-soft)] mb-3">
                  <span className="inline-flex items-center gap-1">
                    <Layers className="h-3 w-3" />
                    {formatCount(item.chunk_count)} 分片
                  </span>
                  <span title={item.id}>ID {shortId(item.id)}</span>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between border-t border-[var(--line)] pt-3">
                  <span className="text-xs text-[var(--muted-soft)]">
                    更新于 {formatDate(item.updated_at || item.created_at)}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={(e) => handleDelete(e, String(item.id))}
                      className={cn(
                        "inline-flex items-center justify-center rounded-md p-1",
                        "text-[var(--muted-soft)] hover:text-[var(--danger)] hover:bg-[var(--danger-soft)]",
                        "transition-colors duration-150",
                      )}
                      title="删除知识库"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <span className="inline-flex items-center gap-0.5 text-xs text-[var(--accent)] font-medium">
                      打开
                      <ArrowRight className="h-3 w-3" />
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
