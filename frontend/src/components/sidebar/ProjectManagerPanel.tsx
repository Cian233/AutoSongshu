import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderKanban, Plus, Trash2, Check, Loader2, Upload, X, RefreshCw, File, Folder, FolderOpen, ChevronRight, ChevronDown } from "lucide-react";
import { useProjectStore } from "../../stores/use-project-store";
import { cn } from "../../lib/cn";

// ── Types ──────────────────────────────────────────────

interface WorkspaceFile {
  name: string;
  path: string;
  is_directory: boolean;
  size?: number;
  children?: WorkspaceFile[];
}

// ── Workspace Modal (Browse + Upload) ────────────────────────────────────────────────

function WorkspaceModal({
  projectId,
  projectName,
  onClose,
}: {
  projectId: string;
  projectName: string;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadTarget, setUploadTarget] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<FileList | null>(null);
  const [uploadStatus, setUploadStatus] = useState<{ type: "success" | "error" | "uploading"; message: string } | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());

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

  const executeUpload = useCallback(
    async (targetPath: string, fileList: FileList) => {
      setUploadStatus({ type: "uploading", message: `正在上传 ${fileList.length} 个文件...` });
      let successCount = 0;
      let errorCount = 0;

      for (const file of Array.from(fileList)) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("path", targetPath ? `${targetPath}/${file.name}` : file.name);

        try {
          const response = await fetch(`/api/projects/${projectId}/workspace/upload`, {
            method: "POST",
            body: formData,
          });
          if (response.ok) {
            successCount++;
          } else {
            errorCount++;
          }
        } catch {
          errorCount++;
        }
      }

      if (errorCount === 0) {
        setUploadStatus({ type: "success", message: `成功上传 ${successCount} 个文件` });
      } else {
        setUploadStatus({ type: "error", message: `上传完成: ${successCount} 成功, ${errorCount} 失败` });
      }

      setPendingFiles(null);
      loadWorkspace();

      // Clear status after 3 seconds
      setTimeout(() => setUploadStatus(null), 3000);
    },
    [projectId, loadWorkspace],
  );

  const handleUpload = useCallback(
    (targetPath: string, fileList: FileList) => {
      setPendingFiles(fileList);
      setUploadTarget(targetPath);
    },
    [],
  );

  const confirmUpload = useCallback(() => {
    if (pendingFiles) {
      executeUpload(uploadTarget, pendingFiles);
    }
  }, [pendingFiles, uploadTarget, executeUpload]);

  const cancelUpload = useCallback(() => {
    setPendingFiles(null);
    setUploadStatus(null);
  }, []);

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

  const toggleDir = useCallback((path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    const allDirs = new Set<string>();
    const collect = (items: WorkspaceFile[]) => {
      for (const item of items) {
        if (item.is_directory) {
          allDirs.add(item.path);
          if (item.children) collect(item.children);
        }
      }
    };
    collect(files);
    setExpandedDirs(allDirs);
  }, [files]);

  const collapseAll = useCallback(() => {
    setExpandedDirs(new Set());
  }, []);

  // Load workspace on mount
  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  const totalFiles = useMemo(() => {
    let count = 0;
    const countFiles = (items: WorkspaceFile[]) => {
      for (const item of items) {
        if (item.is_directory) {
          if (item.children) countFiles(item.children);
        } else {
          count++;
        }
      }
    };
    countFiles(files);
    return count;
  }, [files]);

  const totalDirs = useMemo(() => {
    let count = 0;
    const countDirs = (items: WorkspaceFile[]) => {
      for (const item of items) {
        if (item.is_directory) {
          count++;
          if (item.children) countDirs(item.children);
        }
      }
    };
    countDirs(files);
    return count;
  }, [files]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="flex h-[80vh] w-[640px] flex-col rounded-xl border border-[var(--line)] bg-[var(--panel)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3">
          <div className="flex items-center gap-3">
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">工作空间 - {projectName}</h3>
              <p className="text-[11px] text-[var(--muted)]">
                {totalDirs} 个目录 · {totalFiles} 个文件
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={loadWorkspace}
              className="rounded-lg p-1.5 text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--text)]"
              title="刷新"
            >
              <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--text)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Upload Drop Zone */}
        <div
          className={cn(
            "mx-4 mt-3 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-3 transition-colors",
            isDragging
              ? "border-[var(--accent)] bg-[var(--accent-soft)]"
              : "border-[var(--line)] hover:border-[var(--muted)]",
            pendingFiles ? "cursor-default" : "cursor-pointer",
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={pendingFiles ? undefined : handleClickUpload}
        >
          <Upload className="h-5 w-5 text-[var(--muted)]" />
          {pendingFiles ? (
            <div className="text-center">
              <p className="text-xs text-[var(--text)]">
                已选择 {pendingFiles.length} 个文件
              </p>
              <p className="text-[11px] text-[var(--muted)] truncate max-w-[400px]">
                {Array.from(pendingFiles).map(f => f.name).join(", ")}
              </p>
              <div className="mt-2 flex items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={confirmUpload}
                  className="inline-flex h-7 items-center gap-1 rounded-md bg-[var(--accent)] px-3 text-xs text-white"
                >
                  <Check className="h-3.5 w-3.5" />
                  确认上传
                </button>
                <button
                  type="button"
                  onClick={cancelUpload}
                  className="h-7 rounded-md px-3 text-xs text-[var(--muted)] hover:bg-[var(--bg-soft)]"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-[var(--muted)]">
              {isDragging ? "松开以上传文件" : "拖拽文件到此处，或点击上传"}
            </p>
          )}
        </div>

        {/* Upload Status */}
        {uploadStatus && (
          <div className={cn(
            "mx-4 mt-2 rounded-md px-3 py-2 text-xs",
            uploadStatus.type === "success" && "bg-green-500/10 text-green-500",
            uploadStatus.type === "error" && "bg-red-500/10 text-red-500",
            uploadStatus.type === "uploading" && "bg-blue-500/10 text-blue-500",
          )}>
            {uploadStatus.message}
          </div>
        )}

        {/* Toolbar */}
        <div className="mx-4 mt-3 flex items-center justify-between">
          <span className="text-[11px] text-[var(--muted)]">文件列表</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={expandAll}
              className="rounded px-2 py-0.5 text-[11px] text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--text)]"
            >
              全部展开
            </button>
            <button
              type="button"
              onClick={collapseAll}
              className="rounded px-2 py-0.5 text-[11px] text-[var(--muted)] hover:bg-[var(--bg-soft)] hover:text-[var(--text)]"
            >
              全部折叠
            </button>
          </div>
        </div>

        {/* File Tree */}
        <div className="flex-1 overflow-y-auto px-4 py-2">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-[var(--muted)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              加载中...
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-8 text-xs text-[var(--muted)]">
              <Folder className="h-8 w-8 opacity-30" />
              <span>工作空间为空，上传文件开始</span>
            </div>
          ) : (
            <div className="space-y-0.5">
              {files.map((file) => (
                <FileTreeItem
                  key={file.path}
                  file={file}
                  expandedDirs={expandedDirs}
                  onToggleDir={toggleDir}
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
  expandedDirs,
  onToggleDir,
  onUpload,
  onDelete,
}: {
  file: WorkspaceFile;
  depth?: number;
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  onUpload: (path: string) => void;
  onDelete: (path: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  const isDirectory = file.is_directory;
  const isExpanded = expandedDirs.has(file.path);

  const formatSize = (size?: number) => {
    if (!size || size === 0) return "";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div>
      <div
        className={cn(
          "group flex items-center gap-1.5 rounded-md px-2 py-1 text-sm transition-colors",
          "hover:bg-[var(--sidebar-hover)]",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {isDirectory ? (
          <button
            type="button"
            onClick={() => onToggleDir(file.path)}
            className="flex items-center gap-1 flex-1 min-w-0 text-left"
          >
            <span className="text-[var(--muted)] flex-shrink-0">
              {isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </span>
            <span className="flex-shrink-0">
              {isExpanded ? (
                <FolderOpen className="h-4 w-4 text-[var(--accent)]" />
              ) : (
                <Folder className="h-4 w-4 text-[var(--accent)]" />
              )}
            </span>
            <span className="flex-1 truncate text-[var(--text)]">{file.name}</span>
          </button>
        ) : (
          <>
            <span className="w-5 flex-shrink-0" />
            <File className="h-4 w-4 flex-shrink-0 text-[var(--muted)]" />
            <span className="flex-1 truncate text-[var(--text)]">{file.name}</span>
          </>
        )}

        {file.size && file.size > 0 && (
          <span className="flex-shrink-0 text-[11px] text-[var(--muted)] tabular-nums">
            {formatSize(file.size)}
          </span>
        )}

        {hovered && (
          <div className="flex items-center gap-0.5 flex-shrink-0">
            {isDirectory && (
              <button
                type="button"
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
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(file.path);
              }}
              className="rounded p-1 hover:bg-[var(--bg-soft)]"
              title="删除"
            >
              <Trash2 className="h-3 w-3 text-red-500/70 hover:text-red-500" />
            </button>
          </div>
        )}
      </div>

      {isDirectory && isExpanded && file.children && (
        <div>
          {file.children.map((child) => (
            <FileTreeItem
              key={child.path}
              file={child}
              depth={depth + 1}
              expandedDirs={expandedDirs}
              onToggleDir={onToggleDir}
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

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newWorkspace, setNewWorkspace] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [workspaceProjectId, setWorkspaceProjectId] = useState<string | null>(null);

  const workspaceProject = useMemo(
    () => projects.find((p) => p.id === workspaceProjectId) || null,
    [projects, workspaceProjectId],
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
                {submitting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                创建
              </button>
            </div>
          </div>
        )}

        <div className="grid gap-1">
          {projects.map((project) => (
            <div
              key={project.id}
              className={cn(
                "group flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors",
                selectedProjectId === project.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "hover:bg-[var(--sidebar-hover)]",
              )}
            >
              <button
                type="button"
                onClick={() => selectProject(project.id)}
                className="flex-1 text-left"
              >
                <div className="truncate text-[13px] font-medium">{project.name}</div>
                <div className="truncate text-[11px] text-[var(--muted)]">
                  {project.session_count ?? 0} 会话 · {project.isolation_mode}
                </div>
              </button>
              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  type="button"
                  onClick={() => setWorkspaceProjectId(project.id)}
                  className="rounded p-1 hover:bg-[var(--bg-soft)]"
                  title="管理工作空间"
                >
                  <FolderKanban className="h-3.5 w-3.5 text-[var(--muted)]" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(project.id, project.name)}
                  className="rounded p-1 hover:bg-[var(--bg-soft)]"
                  title="删除项目"
                >
                  <Trash2 className="h-3.5 w-3.5 text-red-500/70" />
                </button>
              </div>
            </div>
          ))}
          {projects.length === 0 && !creating && (
            <div className="py-4 text-center text-xs text-[var(--muted)]">
              暂无项目，点击"新建"创建
            </div>
          )}
        </div>
      </section>

      {workspaceProject && (
        <WorkspaceModal
          projectId={workspaceProject.id}
          projectName={workspaceProject.name}
          onClose={() => setWorkspaceProjectId(null)}
        />
      )}
    </>
  );
}
