// ── Project Workspace Panel ─────────────────────────────────────
// Displays project workspace files with upload/download/delete support.
// Codex-style: all sessions in a project share this workspace.

import { useCallback, useState } from "react";
import {
  Upload,
  FolderOpen,
  File,
  FileText,
  FileCode,
  Image,
  Trash2,
  Download,
  Plus,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { cn } from "../../lib/cn";
import { useProjectStore } from "../../stores/use-project-store";

// ── Types ───────────────────────────────────────────────────────

interface WorkspaceFile {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number;
  modified_at?: string;
  children?: WorkspaceFile[];
}

// ── File Icon ───────────────────────────────────────────────────

function FileIcon({ name, type }: { name: string; type: "file" | "directory" }) {
  if (type === "directory") {
    return <FolderOpen className="w-4 h-4 text-yellow-500" />;
  }

  const ext = name.split(".").pop()?.toLowerCase() || "";
  const codeExts = ["py", "js", "ts", "tsx", "jsx", "html", "css", "json", "yaml", "yml", "sh", "bash"];
  const imageExts = ["png", "jpg", "jpeg", "gif", "svg", "webp"];
  const textExts = ["txt", "md", "log", "csv", "xml"];

  if (codeExts.includes(ext)) return <FileCode className="w-4 h-4 text-blue-500" />;
  if (imageExts.includes(ext)) return <Image className="w-4 h-4 text-green-500" />;
  if (textExts.includes(ext)) return <FileText className="w-4 h-4 text-gray-500" />;
  return <File className="w-4 h-4 text-gray-400" />;
}

// ── File Tree Item ──────────────────────────────────────────────

function FileTreeItem({
  file,
  depth = 0,
  onUpload,
  onDelete,
}: {
  file: WorkspaceFile;
  depth?: number;
  onUpload: (path: string) => void;
  onDelete: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isDirectory = file.type === "directory";

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-sm",
          "hover:bg-[var(--sidebar-hover)] transition-colors",
          depth > 0 && "ml-4"
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => isDirectory && setExpanded(!expanded)}
      >
        {isDirectory && (
          <span className="text-muted-foreground">
            {expanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
          </span>
        )}
        {!isDirectory && <span className="w-3" />}

        <FileIcon name={file.name} type={file.type} />

        <span className="flex-1 truncate">{file.name}</span>

        {file.size && file.size > 0 && (
          <span className="text-xs text-muted-foreground">
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
                className="p-1 rounded hover:bg-[var(--bg-soft)]"
                title="上传到该目录"
              >
                <Upload className="w-3 h-3 text-muted-foreground" />
              </button>
            )}
            {!isDirectory && (
              <>
                <button
                  onClick={(e) => e.stopPropagation()}
                  className="p-1 rounded hover:bg-[var(--bg-soft)]"
                  title="下载"
                >
                  <Download className="w-3 h-3 text-muted-foreground" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(file.path);
                  }}
                  className="p-1 rounded hover:bg-[var(--bg-soft)]"
                  title="删除"
                >
                  <Trash2 className="w-3 h-3 text-red-500" />
                </button>
              </>
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

// ── Upload Drop Zone ────────────────────────────────────────────

function UploadDropZone({
  onFilesSelected,
  targetPath,
}: {
  onFilesSelected: (files: FileList) => void;
  targetPath: string;
}) {
  const [isDragging, setIsDragging] = useState(false);

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
        onFilesSelected(e.dataTransfer.files);
      }
    },
    [onFilesSelected]
  );

  const handleClick = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        onFilesSelected(input.files);
      }
    };
    input.click();
  }, [onFilesSelected]);

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 p-6 rounded-lg border-2 border-dashed transition-colors cursor-pointer",
        isDragging
          ? "border-primary bg-primary/5"
          : "border-[var(--border)] hover:border-[var(--muted)]"
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={handleClick}
    >
      <Upload className="w-8 h-8 text-muted-foreground" />
      <p className="text-sm text-muted-foreground text-center">
        {isDragging ? "松开以上传文件" : "拖拽文件到此处，或点击上传"}
      </p>
      <p className="text-xs text-muted-foreground">
        上传到: {targetPath || "/"}
      </p>
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────

interface ProjectWorkspacePanelProps {
  className?: string;
}

export function ProjectWorkspacePanel({ className }: ProjectWorkspacePanelProps) {
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadTarget, setUploadTarget] = useState("");

  // Load workspace files
  const loadWorkspace = useCallback(async () => {
    if (!selectedProjectId) return;
    setIsLoading(true);
    try {
      const data = await fetch(`/api/projects/${selectedProjectId}/workspace`);
      const json = await data.json();
      setFiles(json.files || []);
    } catch {
      // Silently fail
    } finally {
      setIsLoading(false);
    }
  }, [selectedProjectId]);

  // Handle file upload
  const handleUpload = useCallback(
    async (targetPath: string, fileList: FileList) => {
      if (!selectedProjectId) return;

      for (const file of Array.from(fileList)) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("path", targetPath ? `${targetPath}/${file.name}` : file.name);

        try {
          await fetch(`/api/projects/${selectedProjectId}/workspace/upload`, {
            method: "POST",
            body: formData,
          });
        } catch {
          // Silently fail
        }
      }

      // Reload workspace
      loadWorkspace();
    },
    [selectedProjectId, loadWorkspace]
  );

  // Handle file delete
  const handleDelete = useCallback(
    async (filePath: string) => {
      if (!selectedProjectId) return;
      if (!confirm(`确定要删除 ${filePath} 吗？`)) return;

      try {
        await fetch(
          `/api/projects/${selectedProjectId}/workspace?path=${encodeURIComponent(filePath)}`,
          { method: "DELETE" }
        );
        loadWorkspace();
      } catch {
        // Silently fail
      }
    },
    [selectedProjectId, loadWorkspace]
  );

  if (!selectedProjectId) {
    return (
      <div className={cn("p-4 text-center text-sm text-muted-foreground", className)}>
        请先选择一个项目
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-2">
        <span className="text-xs font-medium text-muted-foreground">
          项目工作空间
        </span>
        <button
          onClick={() => setUploadTarget("")}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-[var(--sidebar-hover)] hover:bg-[var(--bg-soft)]"
        >
          <Plus className="w-3 h-3" />
          上传文件
        </button>
      </div>

      {/* Upload zone */}
      <UploadDropZone
        onFilesSelected={(files) => handleUpload(uploadTarget, files)}
        targetPath={uploadTarget}
      />

      {/* File tree */}
      <div className="flex flex-col gap-0.5 max-h-64 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-sm text-muted-foreground">
            加载中...
          </div>
        ) : files.length === 0 ? (
          <div className="p-4 text-center text-sm text-muted-foreground">
            工作空间为空，上传文件开始
          </div>
        ) : (
          files.map((file) => (
            <FileTreeItem
              key={file.path}
              file={file}
              onUpload={(path) => {
                setUploadTarget(path);
                // Trigger file input
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
          ))
        )}
      </div>
    </div>
  );
}
