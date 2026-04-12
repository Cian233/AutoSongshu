// ── ReasoningPart ────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderAssistantReasoningPart()
//
// Renders a collapsible "thinking" panel for reasoning/thinking parts.
// Shows a truncated preview in the summary, and the full markdown
// content in the collapsible body.

import { memo, useState } from "react";
import type { ReasoningPart as ReasoningPartType } from "../../types/session";
import { MarkdownContent } from "../markdown/MarkdownContent";

/** Safely coerce a value to string, never producing "[object Object]". */
function safeText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); } catch { /* fall through */ }
  }
  return String(value);
}

/** Truncate text to a maximum length, appending ellipsis. */
function truncate(text: string, maxLen: number): string {
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

interface ReasoningPartProps {
  /** The reasoning part data. */
  part: ReasoningPartType;
  /** Unique key for this reasoning part (used for expanded state tracking). */
  partKey: string;
  /** Whether this part should be open by default. */
  defaultOpen?: boolean;
}

function ReasoningPartInner({
  part,
  partKey,
  defaultOpen = false,
}: ReasoningPartProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const rawText = safeText(part.text);
  const preview = truncate(rawText, 68) || "思考内容";

  return (
    <details
      className="assistant-part assistant-part-reasoning"
      data-assistant-part-key={partKey}
      open={isOpen}
      onToggle={(e) => {
        setIsOpen(e.currentTarget.open);
      }}
    >
      <summary>
        <span className="assistant-part-heading-copy">
          <span className="assistant-part-kicker">思考过程</span>
          <span className="assistant-part-title">{preview}</span>
        </span>
      </summary>
      <div
        className="assistant-part-body markdown-body"
        data-assistant-part-body
      >
        {isOpen && <MarkdownContent content={rawText} />}
      </div>
    </details>
  );
}

export const ReasoningPart = memo(ReasoningPartInner);
