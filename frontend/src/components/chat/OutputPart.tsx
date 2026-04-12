// ── OutputPart ───────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   renderAssistantOutputPart()
//
// Renders a text output section of an assistant message using
// react-markdown.  Supports a "pending" visual state for streaming.

import { memo } from "react";
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

interface OutputPartProps {
  /** Unique key for this output part. */
  partKey: string;
  /** The text content to render as markdown. */
  text: string;
  /** Whether this output is still streaming (pending). */
  isPending?: boolean;
}

function OutputPartInner({ partKey, text, isPending = false }: OutputPartProps) {
  const safeContent = safeText(text);
  return (
    <section
      className="assistant-part assistant-part-output"
      data-assistant-output-key={partKey}
    >
      <MarkdownContent content={safeContent} isPending={isPending} />
    </section>
  );
}

export const OutputPart = memo(OutputPartInner);
