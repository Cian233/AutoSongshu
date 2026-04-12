// ── KnowledgeSelector ───────────────────────────────────────────
// Multi-select knowledge base checkbox list for use in settings
// dialogs and other configuration panels.
//
// Features:
//   - Checkbox list of all available knowledge bases
//   - Select all / deselect all
//   - Visual feedback for selected items
//   - Document count display per knowledge base

import React, { useCallback, useMemo } from "react";
import { CheckSquare, Square } from "lucide-react";
import { cn } from "../../lib/cn";
import { useKnowledgeStore } from "../../stores/use-knowledge-store";

// ── Props ───────────────────────────────────────────────────────

interface KnowledgeSelectorProps {
  /** Additional class names for the container */
  className?: string;
  /** Maximum height for the scrollable list (default: 160px) */
  maxHeight?: number | string;
}

// ── Component ───────────────────────────────────────────────────

export const KnowledgeSelector: React.FC<KnowledgeSelectorProps> = ({
  className,
  maxHeight = 160,
}) => {
  const {
    knowledgeBases,
    selectedKnowledgeBaseIds,
    setSelectedKnowledgeBaseIds,
  } = useKnowledgeStore();

  const allSelected = useMemo(
    () =>
      knowledgeBases.length > 0 &&
      knowledgeBases.every((kb) =>
        selectedKnowledgeBaseIds.includes(String(kb.id)),
      ),
    [knowledgeBases, selectedKnowledgeBaseIds],
  );

  const noneSelected = selectedKnowledgeBaseIds.length === 0;

  // ── Toggle a single knowledge base ────────────────────────────

  const toggleItem = useCallback(
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

  // ── Toggle all ────────────────────────────────────────────────

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelectedKnowledgeBaseIds([]);
    } else {
      setSelectedKnowledgeBaseIds(
        knowledgeBases.map((kb) => String(kb.id)),
      );
    }
  }, [allSelected, knowledgeBases, setSelectedKnowledgeBaseIds]);

  // ── Empty state ───────────────────────────────────────────────

  if (knowledgeBases.length === 0) {
    return (
      <div className={cn("space-y-1.5", className)}>
        <span className="text-sm font-medium text-[var(--text)]">
          关联知识库（可多选）
        </span>
        <p className="text-sm text-[var(--muted)]">暂无知识库</p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text)]">
          关联知识库（可多选）
        </span>
        <button
          type="button"
          onClick={toggleAll}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-2 py-0.5",
            "text-xs font-medium transition-colors duration-150",
            allSelected
              ? "text-[var(--accent)] hover:bg-[var(--accent-soft)]"
              : "text-[var(--muted)] hover:bg-[var(--bg-hover)]",
          )}
        >
          {allSelected ? (
            <>
              <CheckSquare className="h-3 w-3" />
              取消全选
            </>
          ) : (
            <>
              <Square className="h-3 w-3" />
              全选
            </>
          )}
        </button>
      </div>

      <div
        className="space-y-0.5 overflow-y-auto rounded-md border border-[var(--line)] p-1.5"
        style={{ maxHeight: typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight }}
      >
        {knowledgeBases.map((kb) => {
          const isSelected = selectedKnowledgeBaseIds.includes(String(kb.id));
          return (
            <label
              key={kb.id}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer",
                "transition-colors duration-100",
                isSelected
                  ? "bg-[var(--accent-soft)]"
                  : "hover:bg-[var(--bg-hover)]",
              )}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggleItem(String(kb.id))}
                className="sr-only"
              />
              {isSelected ? (
                <CheckSquare className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
              ) : (
                <Square className="h-3.5 w-3.5 shrink-0 text-[var(--muted-soft)]" />
              )}
              <span className="flex-1 truncate text-[var(--text)]">{kb.name}</span>
              <span className="text-[10px] text-[var(--muted)] shrink-0">
                {kb.document_count} 文档
              </span>
            </label>
          );
        })}
      </div>

      {!noneSelected && (
        <p className="text-xs text-[var(--muted)]">
          已选择 {selectedKnowledgeBaseIds.length} / {knowledgeBases.length} 个知识库
        </p>
      )}
    </div>
  );
};

export default KnowledgeSelector;
