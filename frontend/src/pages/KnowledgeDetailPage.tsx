// ── KnowledgeDetailPage ─────────────────────────────────────────
// Migrated from knowledge-detail.js + knowledge-detail.html
//
// Knowledge base detail page with:
//   - Side navigation listing all knowledge bases
//   - Tab switching: Documents / Hit Testing
//   - Document management (CRUD, upload)
//   - Hit testing (query + results)
//   - Knowledge base settings (rename, delete)

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Search,
  RefreshCw,
  FileText,
  Layers,
  Trash2,
  Plus,
  Upload,
  Save,
  Eye,
  X,
  Zap,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { cn } from "../lib/cn";
import { fetchJson } from "../lib/api";
import {
  knowledgeBaseUrl,
  knowledgeDocumentsUrl,
  knowledgeDocumentUploadUrl,
  knowledgeDocumentUrl,
} from "../lib/api-endpoints";
import { useKnowledgeStore } from "../stores/use-knowledge-store";
import type {
  KnowledgeBaseSummary,
  KnowledgeBaseDetail,
  KnowledgeDocument,
  HitTestResult,
} from "../types/knowledge";

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

function baseDescription(base?: KnowledgeBaseSummary | KnowledgeBaseDetail): string {
  const description = String(base?.description || "").trim();
  return description || "未填写描述";
}

// ── Tab type ────────────────────────────────────────────────────

type TabType = "documents" | "hit-testing";

function normalizeTab(tab?: string): TabType {
  return tab === "hit-testing" ? "hit-testing" : "documents";
}

// ── Component ───────────────────────────────────────────────────

export default function KnowledgeDetailPage() {
  const { id, tab } = useParams<{ id: string; tab: string }>();
  const navigate = useNavigate();

  const {
    knowledgeBases,
    setKnowledgeBases,
    knowledgeBaseDetails,
    setKnowledgeBaseDetail,
    removeKnowledgeBaseDetail,
  } = useKnowledgeStore();

  const activeTab = normalizeTab(tab);
  const baseId = id || "";

  // ── Local state ───────────────────────────────────────────────

  const [sideKeyword, setSideKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Documents tab state
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [isSavingBase, setIsSavingBase] = useState(false);
  const [isDeletingBase, setIsDeletingBase] = useState(false);

  // Document import state
  const [showImport, setShowImport] = useState(false);
  const [docTitle, setDocTitle] = useState("");
  const [docSource, setDocSource] = useState("");
  const [docContent, setDocContent] = useState("");
  const [docFile, setDocFile] = useState<File | null>(null);
  const [isSavingDoc, setIsSavingDoc] = useState(false);

  // Document detail modal
  const [activeDocument, setActiveDocument] = useState<KnowledgeDocument | null>(null);
  const [isLoadingDoc, setIsLoadingDoc] = useState(false);

  // Hit testing state
  const [hitQuery, setHitQuery] = useState("");
  const [hitResults, setHitResults] = useState<HitTestResult[]>([]);
  const [isHitTesting, setIsHitTesting] = useState(false);

  // ── Derived state ─────────────────────────────────────────────

  const currentBase: KnowledgeBaseDetail | KnowledgeBaseSummary | undefined =
    knowledgeBaseDetails.get(baseId) ||
    knowledgeBases.find((b) => String(b.id) === baseId);

  const documents: KnowledgeDocument[] =
    "documents" in (currentBase || {})
      ? (currentBase as KnowledgeBaseDetail).documents || []
      : [];

  // ── Filtered side nav ─────────────────────────────────────────

  const filteredBases = sideKeyword.trim()
    ? knowledgeBases.filter((item) => {
        const kw = sideKeyword.trim().toLowerCase();
        return (
          item.name.toLowerCase().includes(kw) ||
          (item.description || "").toLowerCase().includes(kw)
        );
      })
    : knowledgeBases;

  // ── Load bases list ───────────────────────────────────────────

  const refreshBases = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchJson<{ items: KnowledgeBaseSummary[] }>(
        "/api/knowledge/bases",
      );
      setKnowledgeBases(payload.items || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [setKnowledgeBases]);

  // ── Load base detail ──────────────────────────────────────────

  const loadBaseDetail = useCallback(
    async (kbId: string) => {
      if (!kbId) return;
      try {
        const detail = await fetchJson<KnowledgeBaseDetail>(
          knowledgeBaseUrl(kbId),
        );
        setKnowledgeBaseDetail(kbId, detail);
        setEditName(detail.name || "");
        setEditDescription(detail.description || "");
      } catch {
        // ignore individual load errors
      }
    },
    [setKnowledgeBaseDetail],
  );

  // ── Initial load ──────────────────────────────────────────────

  useEffect(() => {
    refreshBases();
  }, [refreshBases]);

  useEffect(() => {
    if (baseId) {
      loadBaseDetail(baseId);
    }
  }, [baseId, loadBaseDetail]);

  // ── Save base settings ────────────────────────────────────────

  const handleSaveBase = useCallback(async () => {
    if (!baseId) return;
    const name = editName.trim();
    if (!name) {
      window.alert("名称不能为空");
      return;
    }

    setIsSavingBase(true);
    try {
      await fetchJson(knowledgeBaseUrl(baseId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description: editDescription.trim() || null,
        }),
      });
      await loadBaseDetail(baseId);
      await refreshBases();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      window.alert(message);
    } finally {
      setIsSavingBase(false);
    }
  }, [baseId, editName, editDescription, loadBaseDetail, refreshBases]);

  // ── Delete base ───────────────────────────────────────────────

  const handleDeleteBase = useCallback(async () => {
    if (!baseId) return;
    if (!window.confirm("确认删除这个知识库及其全部文档吗？")) return;

    setIsDeletingBase(true);
    try {
      await fetchJson(knowledgeBaseUrl(baseId), { method: "DELETE" });
      removeKnowledgeBaseDetail(baseId);
      navigate("/knowledge");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      window.alert(message);
    } finally {
      setIsDeletingBase(false);
    }
  }, [baseId, removeKnowledgeBaseDetail, navigate]);

  // ── Save document ─────────────────────────────────────────────

  const handleSaveDocument = useCallback(async () => {
    if (!baseId) return;
    const title = docTitle.trim();
    if (!title) {
      window.alert("请输入文档标题");
      return;
    }
    if (!docFile && !docContent.trim()) {
      window.alert("请填写文档内容或上传文件");
      return;
    }

    setIsSavingDoc(true);
    try {
      if (docFile) {
        const form = new FormData();
        form.set("title", title);
        if (docSource.trim()) form.set("source", docSource.trim());
        form.set("file", docFile);
        await fetchJson(knowledgeDocumentUploadUrl(baseId), {
          method: "POST",
          body: form,
          timeoutMs: 30000,
        });
      } else {
        await fetchJson(knowledgeDocumentsUrl(baseId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            source: docSource.trim() || null,
            source_type: "text",
            content: docContent.trim(),
          }),
          timeoutMs: 30000,
        });
      }

      setDocTitle("");
      setDocSource("");
      setDocContent("");
      setDocFile(null);
      setShowImport(false);
      await loadBaseDetail(baseId);
      await refreshBases();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      window.alert(message);
    } finally {
      setIsSavingDoc(false);
    }
  }, [baseId, docTitle, docSource, docContent, docFile, loadBaseDetail, refreshBases]);

  // ── Delete document ───────────────────────────────────────────

  const handleDeleteDocument = useCallback(
    async (docId: string) => {
      if (!baseId) return;
      if (!window.confirm("确认删除这个文档吗？")) return;

      try {
        await fetchJson(knowledgeDocumentUrl(baseId, docId), {
          method: "DELETE",
        });
        if (activeDocument && String(activeDocument.id) === docId) {
          setActiveDocument(null);
        }
        await loadBaseDetail(baseId);
        await refreshBases();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        window.alert(message);
      }
    },
    [baseId, activeDocument, loadBaseDetail, refreshBases],
  );

  // ── Open document detail ──────────────────────────────────────

  const handleViewDocument = useCallback(
    async (docId: string) => {
      if (!baseId) return;
      setIsLoadingDoc(true);
      try {
        const doc = await fetchJson<KnowledgeDocument>(
          knowledgeDocumentUrl(baseId, docId),
        );
        setActiveDocument(doc);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        window.alert(message);
      } finally {
        setIsLoadingDoc(false);
      }
    },
    [baseId],
  );

  // ── Hit testing ───────────────────────────────────────────────

  const handleHitTest = useCallback(async () => {
    if (!baseId) return;
    const query = hitQuery.trim();
    if (!query) {
      setHitResults([]);
      return;
    }

    setIsHitTesting(true);
    try {
      const payload = await fetchJson<{ items: HitTestResult[] }>(
        "/api/knowledge/hit-testing",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            knowledge_base_id: baseId,
            query,
            limit: 10,
          }),
        },
      );
      setHitResults(payload.items || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      window.alert(message);
    } finally {
      setIsHitTesting(false);
    }
  }, [baseId, hitQuery]);

  // ── Escape key for modal ──────────────────────────────────────

  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape" && activeDocument) {
        setActiveDocument(null);
      }
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [activeDocument]);

  // ── File input ref ────────────────────────────────────────────

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Render: Error ─────────────────────────────────────────────

  if (error && !currentBase) {
    return (
      <div className="min-h-[100dvh] bg-[var(--bg)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-8 shadow-[var(--shadow)]">
          <AlertCircle className="h-8 w-8 text-[var(--danger)]" />
          <h3 className="text-base font-semibold text-[var(--text)]">加载失败</h3>
          <p className="text-sm text-[var(--muted)]">{error}</p>
          <Link
            to="/knowledge"
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] transition-colors"
          >
            返回知识库列表
          </Link>
        </div>
      </div>
    );
  }

  // ── Render: Not found ─────────────────────────────────────────

  if (!currentBase) {
    return (
      <div className="min-h-[100dvh] bg-[var(--bg)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-8 shadow-[var(--shadow)]">
          <AlertCircle className="h-8 w-8 text-[var(--warning)]" />
          <h3 className="text-base font-semibold text-[var(--text)]">找不到该知识库</h3>
          <p className="text-sm text-[var(--muted)]">该知识库可能已删除，返回列表后重新选择。</p>
          <Link
            to="/knowledge"
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] transition-colors"
          >
            返回知识库列表
          </Link>
        </div>
      </div>
    );
  }

  // ── Render: Main layout ───────────────────────────────────────

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)]">
      {/* Header */}
      <header className="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-[var(--line)] bg-[var(--panel)] px-6 py-3">
        <div className="flex items-center gap-3">
          <Link
            to="/knowledge"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white text-xs font-bold hover:bg-[var(--accent-hover)] transition-colors"
          >
            KB
          </Link>
          <div>
            <p className="text-xs text-[var(--muted)] font-medium tracking-wide uppercase">
              Knowledge Base
            </p>
            <h1 className="text-base font-semibold text-[var(--text)]">
              {currentBase.name || currentBase.id}
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              loadBaseDetail(baseId);
              refreshBases();
            }}
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
          <Link
            to="/knowledge"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] px-3 py-1.5",
              "text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
              "transition-colors duration-150",
            )}
          >
            返回知识库列表
          </Link>
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

      {/* Body: side nav + main */}
      <div className="flex min-h-[calc(100dvh-57px)]">
        {/* Side navigation */}
        <aside className="hidden lg:flex w-60 shrink-0 flex-col border-r border-[var(--line)] bg-[var(--sidebar)]">
          <div className="px-4 pt-4 pb-2">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">
                知识库导航
              </h3>
              <span className="text-xs text-[var(--muted)]">
                {knowledgeBases.length} 个
              </span>
            </div>
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--muted)]" />
              <input
                type="search"
                value={sideKeyword}
                onChange={(e) => setSideKeyword(e.target.value)}
                placeholder="筛选知识库名称"
                className={cn(
                  "w-full rounded-md border border-[var(--line)] bg-[var(--panel)] py-1 pl-7 pr-2",
                  "text-xs text-[var(--text)] placeholder:text-[var(--muted-soft)]",
                  "focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
                )}
              />
            </div>
          </div>
          <nav className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
            {filteredBases.map((item) => {
              const isActive = String(item.id) === baseId;
              return (
                <Link
                  key={item.id}
                  to={`/knowledge/bases/${encodeURIComponent(String(item.id))}/${activeTab}`}
                  className={cn(
                    "flex flex-col rounded-md px-3 py-2 text-left",
                    "transition-colors duration-150",
                    isActive
                      ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--sidebar-hover)]",
                  )}
                >
                  <span className="text-xs font-medium truncate" title={item.name || item.id}>
                    {item.name || item.id}
                  </span>
                  <span className="text-[10px] text-[var(--muted)] mt-0.5">
                    {formatCount(item.document_count)} 文档 &middot; {formatCount(item.chunk_count)} 分片
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          <div className="mx-auto max-w-4xl px-6 py-6 space-y-6">
            {/* Detail head */}
            <section className="space-y-2">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-bold text-[var(--text)]">
                    {currentBase.name || currentBase.id}
                  </h2>
                  <p className="text-sm text-[var(--muted)] mt-1">
                    {baseDescription(currentBase)}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--muted-soft)]">
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  {formatCount(currentBase.document_count)} 文档
                </span>
                <span className="inline-flex items-center gap-1">
                  <Layers className="h-3 w-3" />
                  {formatCount(currentBase.chunk_count)} 分片
                </span>
                <span title={currentBase.id}>ID {shortId(currentBase.id)}</span>
                <span>更新于 {formatDate(currentBase.updated_at || currentBase.created_at)}</span>
              </div>
            </section>

            {/* Tabs */}
            <nav className="flex items-center gap-1 border-b border-[var(--line)]">
              <Link
                to={`/knowledge/bases/${encodeURIComponent(baseId)}/documents`}
                className={cn(
                  "inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors",
                  activeTab === "documents"
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--muted)] hover:text-[var(--text)]",
                )}
              >
                <FileText className="h-3.5 w-3.5" />
                文档管理
              </Link>
              <Link
                to={`/knowledge/bases/${encodeURIComponent(baseId)}/hit-testing`}
                className={cn(
                  "inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors",
                  activeTab === "hit-testing"
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--muted)] hover:text-[var(--text)]",
                )}
              >
                <Zap className="h-3.5 w-3.5" />
                命中测试
              </Link>
            </nav>

            {/* Tab content */}
            {activeTab === "documents" ? (
              <DocumentsTab
                base={currentBase}
                documents={documents}
                editName={editName}
                editDescription={editDescription}
                isSavingBase={isSavingBase}
                isDeletingBase={isDeletingBase}
                showImport={showImport}
                docTitle={docTitle}
                docSource={docSource}
                docContent={docContent}
                isSavingDoc={isSavingDoc}
                onEditNameChange={setEditName}
                onEditDescriptionChange={setEditDescription}
                onSaveBase={handleSaveBase}
                onDeleteBase={handleDeleteBase}
                onToggleImport={() => setShowImport((v) => !v)}
                onDocTitleChange={setDocTitle}
                onDocSourceChange={setDocSource}
                onDocContentChange={setDocContent}
                onDocFileChange={(file) => setDocFile(file)}
                onSaveDocument={handleSaveDocument}
                onViewDocument={handleViewDocument}
                onDeleteDocument={handleDeleteDocument}
                fileInputRef={fileInputRef}
              />
            ) : (
              <HitTestingTab
                baseName={currentBase.name || currentBase.id}
                hitQuery={hitQuery}
                hitResults={hitResults}
                isHitTesting={isHitTesting}
                onQueryChange={setHitQuery}
                onRunHitTest={handleHitTest}
              />
            )}
          </div>
        </main>
      </div>

      {/* Document detail modal */}
      {activeDocument && (
        <DocumentDetailModal
          document={activeDocument}
          isLoading={isLoadingDoc}
          onClose={() => setActiveDocument(null)}
        />
      )}
    </div>
  );
}

// ── DocumentsTab ────────────────────────────────────────────────

interface DocumentsTabProps {
  base: KnowledgeBaseSummary | KnowledgeBaseDetail;
  documents: KnowledgeDocument[];
  editName: string;
  editDescription: string;
  isSavingBase: boolean;
  isDeletingBase: boolean;
  showImport: boolean;
  docTitle: string;
  docSource: string;
  docContent: string;
  isSavingDoc: boolean;
  onEditNameChange: (v: string) => void;
  onEditDescriptionChange: (v: string) => void;
  onSaveBase: () => void;
  onDeleteBase: () => void;
  onToggleImport: () => void;
  onDocTitleChange: (v: string) => void;
  onDocSourceChange: (v: string) => void;
  onDocContentChange: (v: string) => void;
  onDocFileChange: (file: File | null) => void;
  onSaveDocument: () => void;
  onViewDocument: (docId: string) => void;
  onDeleteDocument: (docId: string) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
}

function DocumentsTab({
  documents,
  editName,
  editDescription,
  isSavingBase,
  isDeletingBase,
  showImport,
  docTitle,
  docSource,
  docContent,
  isSavingDoc,
  onEditNameChange,
  onEditDescriptionChange,
  onSaveBase,
  onDeleteBase,
  onToggleImport,
  onDocTitleChange,
  onDocSourceChange,
  onDocContentChange,
  onDocFileChange,
  onSaveDocument,
  onViewDocument,
  onDeleteDocument,
  fileInputRef,
}: DocumentsTabProps) {
  const inputClass = cn(
    "w-full rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5",
    "text-sm text-[var(--text)] placeholder:text-[var(--muted-soft)]",
    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent",
  );

  return (
    <div className="space-y-5">
      {/* Settings panel */}
      <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-xs)]">
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-[var(--text)]">知识库设置</h3>
          <p className="text-xs text-[var(--muted)] mt-0.5">
            调整名称和描述，便于团队检索与复用。
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 mb-4">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-[var(--text-secondary)]">名称</span>
            <input
              type="text"
              value={editName}
              onChange={(e) => onEditNameChange(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-[var(--text-secondary)]">描述</span>
            <input
              type="text"
              value={editDescription}
              onChange={(e) => onEditDescriptionChange(e.target.value)}
              className={inputClass}
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSaveBase}
            disabled={isSavingBase}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5",
              "text-sm font-medium text-white",
              "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
              "transition-colors duration-150 disabled:opacity-50",
            )}
          >
            <Save className="h-3.5 w-3.5" />
            {isSavingBase ? "保存中..." : "保存设置"}
          </button>
          <button
            type="button"
            onClick={onDeleteBase}
            disabled={isDeletingBase}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-[var(--danger)] px-3 py-1.5",
              "text-sm font-medium text-[var(--danger)]",
              "hover:bg-[var(--danger-soft)]",
              "transition-colors duration-150 disabled:opacity-50",
            )}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {isDeletingBase ? "删除中..." : "删除知识库"}
          </button>
        </div>
      </section>

      {/* Documents panel */}
      <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-[var(--shadow-xs)]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--line)]">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text)]">文档列表</h3>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              面向检索的文档视图，支持详情与删除。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--muted)]">{documents.length} 个文档</span>
            <button
              type="button"
              onClick={onToggleImport}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5",
                "text-xs font-medium text-white",
                "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
                "transition-colors duration-150",
              )}
            >
              <Plus className="h-3 w-3" />
              新增文档
            </button>
          </div>
        </div>

        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-5">
            <FileText className="h-8 w-8 text-[var(--muted-soft)] mb-2" />
            <h4 className="text-sm font-medium text-[var(--text-secondary)]">还没有文档</h4>
            <p className="text-xs text-[var(--muted)] mt-1">
              可直接粘贴文本，或上传 txt / md / html 文件。
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--line)]">
            {documents.map((doc) => (
              <article key={doc.id} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex-1 min-w-0">
                  <strong className="text-sm font-medium text-[var(--text)] truncate block" title={doc.title || doc.id}>
                    {doc.title || doc.id}
                  </strong>
                  {doc.source && (
                    <span className="inline-flex items-center rounded bg-[var(--bg-soft)] px-1.5 py-0.5 text-[10px] text-[var(--muted)] mt-1" title={doc.source}>
                      {doc.source}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 text-[10px] text-[var(--muted-soft)] shrink-0">
                  <span className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5">
                    {formatCount(doc.word_count)} words
                  </span>
                  <span className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5">
                    {formatCount(doc.chunk_count)} chunks
                  </span>
                  <span className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5">
                    {formatCount(doc.content_length)} chars
                  </span>
                  <span className="hidden sm:inline">
                    {formatDate(doc.updated_at || doc.created_at)}
                  </span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => onViewDocument(String(doc.id))}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-1",
                      "text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
                      "transition-colors duration-150",
                    )}
                  >
                    <Eye className="h-3 w-3" />
                    详情
                  </button>
                  <button
                    type="button"
                    onClick={() => onDeleteDocument(String(doc.id))}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-1",
                      "text-xs text-[var(--danger)] hover:bg-[var(--danger-soft)]",
                      "transition-colors duration-150",
                    )}
                  >
                    <Trash2 className="h-3 w-3" />
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Import panel */}
      {showImport && (
        <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-xs)]">
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-[var(--text)]">导入文档</h3>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              支持文本直贴与文件上传，导入后自动分块与向量化。
            </p>
          </div>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-[var(--text-secondary)]">文档标题</span>
                <input
                  type="text"
                  value={docTitle}
                  onChange={(e) => onDocTitleChange(e.target.value)}
                  placeholder="例如：登录流程说明"
                  className={inputClass}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-[var(--text-secondary)]">来源（可选）</span>
                <input
                  type="text"
                  value={docSource}
                  onChange={(e) => onDocSourceChange(e.target.value)}
                  placeholder="wiki / URL / 文件路径"
                  className={inputClass}
                />
              </label>
            </div>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-[var(--text-secondary)]">文本内容</span>
              <textarea
                rows={6}
                value={docContent}
                onChange={(e) => onDocContentChange(e.target.value)}
                placeholder="可直接粘贴文档内容"
                className={cn(inputClass, "resize-none")}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-[var(--text-secondary)]">或上传文件</span>
              <input
                ref={fileInputRef}
                type="file"
                onChange={(e) => onDocFileChange(e.target.files?.[0] || null)}
                className="block w-full text-sm text-[var(--text-secondary)] file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-medium file:bg-[var(--accent-soft)] file:text-[var(--accent)] hover:file:bg-[var(--accent-muted)]"
              />
            </label>
            <button
              type="button"
              onClick={onSaveDocument}
              disabled={isSavingDoc}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-4 py-2",
                "text-sm font-medium text-white",
                "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
                "transition-colors duration-150 disabled:opacity-50",
              )}
            >
              {isSavingDoc ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              {isSavingDoc ? "保存中..." : "保存文档"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

// ── HitTestingTab ───────────────────────────────────────────────

interface HitTestingTabProps {
  baseName: string;
  hitQuery: string;
  hitResults: HitTestResult[];
  isHitTesting: boolean;
  onQueryChange: (v: string) => void;
  onRunHitTest: () => void;
}

function HitTestingTab({
  baseName,
  hitQuery,
  hitResults,
  isHitTesting,
  onQueryChange,
  onRunHitTest,
}: HitTestingTabProps) {
  const inputClass = cn(
    "w-full rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5",
    "text-sm text-[var(--text)] placeholder:text-[var(--muted-soft)]",
    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent",
  );

  return (
    <div className="space-y-5">
      {/* Query panel */}
      <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-xs)]">
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-[var(--text)]">命中测试</h3>
          <p className="text-xs text-[var(--muted)] mt-0.5">
            用于验证分块与检索策略是否覆盖关键知识点。
          </p>
        </div>
        <label className="block space-y-1 mb-3">
          <span className="text-xs font-medium text-[var(--text-secondary)]">查询问题</span>
          <textarea
            rows={4}
            value={hitQuery}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="例如：登录接口限流策略有哪些？"
            className={cn(inputClass, "resize-none")}
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onRunHitTest}
            disabled={isHitTesting}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-4 py-2",
              "text-sm font-medium text-white",
              "bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
              "transition-colors duration-150 disabled:opacity-50",
            )}
          >
            {isHitTesting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Zap className="h-3.5 w-3.5" />
            )}
            {isHitTesting ? "测试中..." : "测试命中"}
          </button>
          <span className="text-xs text-[var(--muted)]">
            当前知识库：{baseName}
          </span>
        </div>
      </section>

      {/* Results panel */}
      <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-[var(--shadow-xs)]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--line)]">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text)]">检索结果</h3>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              按重排分数展示最相关片段。
            </p>
          </div>
          <span className="text-xs text-[var(--muted)]">{hitResults.length} 条</span>
        </div>

        {hitResults.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-5">
            <Zap className="h-8 w-8 text-[var(--muted-soft)] mb-2" />
            <h4 className="text-sm font-medium text-[var(--text-secondary)]">暂无命中结果</h4>
            <p className="text-xs text-[var(--muted)] mt-1">
              输入问题并点击"测试命中"查看检索效果。
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--line)]">
            {hitResults.map((item, index) => (
              <article key={`${item.document_id}-${item.chunk_index}-${index}`} className="px-5 py-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-sm font-medium text-[var(--text)] truncate">
                    #{index + 1} {item.document_title || item.document_id}
                  </strong>
                  <span className="inline-flex items-center rounded-full bg-[var(--success-soft)] px-2 py-0.5 text-xs font-semibold text-[var(--success)]">
                    {Number(item.score || 0).toFixed(2)}
                  </span>
                </div>
                <p className="text-xs text-[var(--muted)]">
                  chunk {Number(item.chunk_index || 0)} &middot; {item.knowledge_base_name || ""}
                </p>
                <div className="rounded-lg bg-[var(--bg)] p-3 text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                  {item.content || ""}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// ── DocumentDetailModal ─────────────────────────────────────────

interface DocumentDetailModalProps {
  document: KnowledgeDocument;
  isLoading: boolean;
  onClose: () => void;
}

function DocumentDetailModal({ document, isLoading, onClose }: DocumentDetailModalProps) {
  const content = (document.content || document.content_preview || "").trim();

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Modal */}
      <div
        className="relative z-50 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-[var(--shadow-float)]"
        role="dialog"
        aria-modal="true"
        aria-label="文档详情"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-[var(--line)] px-5 py-4">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-[var(--text)] truncate">
              {document.title || document.id || "文档详情"}
            </h3>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              {document.source ? `来源：${document.source}` : "无来源信息"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={cn(
              "inline-flex items-center justify-center rounded-md p-1.5 ml-3 shrink-0",
              "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--bg-hover)]",
              "transition-colors duration-150",
            )}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Meta */}
        <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-[var(--line)]">
          <span className="rounded bg-[var(--bg-soft)] px-2 py-0.5 text-xs text-[var(--muted)]">
            {formatCount(document.word_count)} words
          </span>
          <span className="rounded bg-[var(--bg-soft)] px-2 py-0.5 text-xs text-[var(--muted)]">
            {formatCount(document.chunk_count)} chunks
          </span>
          <span className="rounded bg-[var(--bg-soft)] px-2 py-0.5 text-xs text-[var(--muted)]">
            {formatCount(document.content_length)} chars
          </span>
          <span className="text-xs text-[var(--muted)]">
            {formatDate(document.updated_at || document.created_at)}
          </span>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--muted)]" />
            </div>
          ) : (
            <pre className="whitespace-pre-wrap break-words text-xs text-[var(--text-secondary)] leading-relaxed font-[var(--font-mono)]">
              {content || "暂无文档内容"}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
