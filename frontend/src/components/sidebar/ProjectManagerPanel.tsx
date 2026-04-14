import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderKanban, Plus, Trash2, Check, Loader2, Upload, X } from "lucide-react";
import { useProjectStore } from "../../stores/use-project-store";
import { cn } from "../../lib/cn";

// ── Upload Modal ────────────────────────────────────────────────

function UploadModal({
  projectId,
  projectName,
  onClose,
}: {
  projectId: string;
  projectName: string;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<Array<{ name: string; path: string; is_directory: boolean; size?: number; children?: Array<{ name: string; path: string; is_directory: boolean; size?: number }> }>>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadTarget, setUploadTarget] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const loadWorkspace = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetch(`/api/projects/${projectId}/workspace`);
      const json = await data.json();
      setFiles(json.files || []);
    } catch {
      // Silently fail
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  const handleUpload = useCallback(
    async (targetPath: string, fileList: FileList) => {
      for (const file of Array.from(fileList)) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("path", targetPath ? `${targetPath}/${file.name}` : file.name);

        try {
          await fetch(`/api/projects/${projectId}/workspace/upload`, {
            method: "POST",
            body: formData,
          });
        } catch {
          // Silently fail
        }
      }
      loadWorkspace();
    },
    [projectId, loadWorkspace],
  );

  const handleDelete = useCallback(
    async (filePath: string) => {
      if (!confirm(`确定要删除 ${filePath} 吗？`)) return;

      try {
        await fetch(
          `/api/projects/${projectId}/workspace?path=${encodeURIComponent(filePath)}`,
          { method: "DELETE" },
        );
        loadWorkspace();
      } catch {
        // Silently fail
      }
    },
    [projectId, loadWorkspace],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        handleUpload(uploadTarget, e.dataTransfer.files);
      }
    },
    [handleUpload, uploadTarget],
  );

  const handleClickUpload = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        handleUpload(uploadTarget, input.files);
      }
    };
    input.click();
  }, [handleUpload, uploadTarget]);

  // Load workspace on mount
  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="flex h-[80vh] w-[600px] flex-col rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text)]">上传文件 - {projectName}</h3>
            <p className="text-[11px] text-[var(--muted)]">上传到: {uploadTarget || "/"}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Upload Drop Zone */}
        <div
          className={cn(
            "mx-4 mt-3 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-4 transition-colors cursor-pointer",
            isDragging
              ? "border-[var(--accent)] bg-[var(--accent-soft)]"
              : "border-[var(--line)] hover:border-[var(--muted)]",
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={handleClickUpload}
        >
          <Upload className="h-6 w-6 text-[var(--muted)]" />
          <p className="text-xs text-[var(--muted)]">
            {isDragging ? "松开以上传文件" : "拖拽文件到此处，或点击上传"}
          </p>
        </div>

        {/* File Tree */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {isLoading ? (
            <div className="py-4 text-center text-xs text-[var(--muted)]">加载中...</div>
          ) : files.length === 0 ? (
            <div className="py-4 text-center text-xs text-[var(--muted)]">工作空间为空，上传文件开始</div>
          ) : (
            <div className="space-y-0.5">
              {files.map((file) => (
                <FileTreeItem
                  key={file.path}
                  file={file}
                  onUpload={(path) => {
                    setUploadTarget(path);
                    const input = document.createElement("input");
                    input.type = "file";
                    input.multiple = true;
                    input.onchange = () => {
                      if (input.files && input.files.length > 0) {
                        handleUpload(path, input.files);
                      }
                    };
                    input.click();
                  }}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── File Tree Item ──────────────────────────────────────────────

function FileTreeItem({
  file,
  depth = 0,
  onUpload,
  onDelete,
}: {
  file: { name: string; path: string; is_directory: boolean; size?: number; children?: Array<{ name: string; path: string; is_directory: boolean; size?: number }> };
  depth?: number;
  onUpload: (path: string) => void;
  onDelete: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isDirectory = file.is_directory;

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
          "hover:bg-[var(--sidebar-hover)]",
          depth > 0 && "ml-4",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => isDirectory && setExpanded(!expanded)}
      >
        {isDirectory && (
          <span className="text-[var(--muted)]">
            {expanded ? (
              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 9l6 6 6-6" />
              </svg>
            ) : (
              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            )}
          </span>
        )}
        {!isDirectory && <span className="w-3" />}

        <span className="flex-1 truncate text-[var(--text)]">{file.name}</span>

        {file.size && file.size > 0 && (
          <span className="text-xs text-[var(--muted)]">
            {file.size < 1024
              ? `${file.size} B`
              : file.size < 1024 * 1024
                ? `${(file.size / 1024).toFixed(1)} KB`
                : `${(file.size / (1024 * 1024)).toFixed(1)} MB`}
          </span>
        )}

        {hovered && (
          <div className="flex items-center gap-1">
            {isDirectory && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onUpload(file.path);
                }}
                className="rounded p-1 hover:bg-[var(--bg-soft)]"
                title="上传到该目录"
              >
                <Upload className="h-3 w-3 text-[var(--muted)]" />
              </button>
            )}
            {!isDirectory && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(file.path);
                }}
                className="rounded p-1 hover:bg-[var(--bg-soft)]"
                title="删除"
              >
                <svg className="h-3 w-3 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                </svg>
              </button>
            )}
          </div>
        )}
      </div>

      {isDirectory && expanded && file.children && (
        <div>
          {file.children.map((child) => (
            <FileTreeItem
              key={child.path}
              file={child}
              depth={depth + 1}
              onUpload={onUpload}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────

export function ProjectManagerPanel() {
  const projects = useProjectStore((s) => s.projects);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const selectProject = useProjectStore((s) => s.selectProject);
  const createProject = useProjectStore((s) => s.createProject);
  const deleteProject = useProjectStore((s) => s.deleteProject);
  const isLoading = useProjectStore((s) => s.isLoading);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newWorkspace, setNewWorkspace] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadProjectId, setUploadProjectId] = useState<string | null>(null);

  const selectedProject = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  );

  const uploadProject = useMemo(
    () => projects.find((p) => p.id === uploadProjectId) || null,
    [projects, uploadProjectId],
  );

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name || submitting) return;

    setSubmitting(true);
    const created = await createProject(name, newWorkspace.trim() || undefined);
    setSubmitting(false);

    if (created) {
      selectProject(created.id);
      setNewName("");
      setNewWorkspace("");
      setCreating(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    const ok = confirm(`确定删除项目"${name}"？该操作不可撤销。`);
    if (!ok) return;
    await deleteProject(id);
  };

  return (
    <>
      <section className="rounded-xl border border-[var(--line)] bg-[var(--sidebar-soft)]/70 p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-[var(--text)]">
            <FolderKanban className="h-4 w-4 text-[var(--accent)]" />
            <h3 className="text-[13px] font-semibold">项目管理</h3>
          </div>
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--line)] bg-[var(--panel)] px-2 text-[11px] text-[var(--muted)] transition-colors hover:text-[var(--text)]"
          >
            <Plus className="h-3.5 w-3.5" />
            新建
          </button>
        </div>

        {creating && (
          <div className="mb-3 grid gap-2 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-2.5">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="项目名称（必填）"
              className="h-8 w-full rounded-md border border-[var(--line)] bg-transparent px-2 text-xs outline-none focus:border-[var(--accent)]"
            />
            <input
              value={newWorkspace}
              onChange={(e) => setNewWorkspace(e.target.value)}
              placeholder="工作区路径（可选）"
              className="h-8 w-full rounded-md border border-[var(--line)] bg-transparent px-2 text-xs outline-none focus:border-[var(--accent)]"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="h-7 rounded-md px-2 text-xs text-[var(--muted)] hover:bg-[var(--bg-soft)]"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!newName.trim() || submitting}
                onClick={handleCreate}
                className="inline-flex h-7 items-center gap-1 rounded-md bg-[var(--accent)] px-2 text-xs text-white disabled:opacity-60"
              >
                {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                创建
              </button>
            </div>
          </div>
        )}

        <div className="max-h-48 space-y-1 overflow-y-auto pr-0.5">
          {isLoading ? (
            <div className="py-3 text-center text-xs text-[var(--muted)]">项目加载中...</div>
          ) : projects.length === 0 ? (
            <div className="py-3 text-center text-xs text-[var(--muted)]">暂无项目，请先创建</div>
          ) : (
            projects.map((project) => {
              const active = project.id === selectedProjectId;
              return (
                <div
                  key={project.id}
                  className={cn(
                    "group flex items-center justify-between gap-2 rounded-lg border px-2 py-1.5",
                    active
                      ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                      : "border-transparent bg-[var(--panel)] hover:border-[var(--line)]",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => selectProject(project.id)}
                    className="min-w-0 flex-1 cursor-pointer text-left"
                    title={project.workspace_dir || project.name}
                  >
                    <div className="truncate text-xs font-medium text-[var(--text)]">{project.name}</div>
                    <div className="truncate text-[11px] text-[var(--muted)]">
                      {project.session_count ?? 0} 会话 · {project.isolation_mode}
                    </div>
                  </button>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => setUploadProjectId(project.id)}
                      className="invisible rounded p-1 text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--accent)] group-hover:visible"
                      title="上传文件"
                    >
                      <Upload className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(project.id, project.name)}
                      className="invisible rounded p-1 text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--danger)] group-hover:visible"
                      title="删除项目"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {selectedProject && (
          <div className="mt-2 truncate rounded-md bg-[var(--panel)] px-2 py-1 text-[11px] text-[var(--muted)]" title={selectedProject.workspace_dir}>
            当前工作区: {selectedProject.workspace_dir || "未设置"}
          </div>
        )}
      </section>

      {/* Upload Modal */}
      {uploadProject && (
        <UploadModal
          projectId={uploadProject.id}
          projectName={uploadProject.name}
          onClose={() => setUploadProjectId(null)}
        />
      )}
    </>
  );
}
