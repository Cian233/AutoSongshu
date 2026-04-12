// ── AssistantTimeline ────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//   buildAssistantTimelineItems(), renderAssistantTimeline()
//
// Builds and renders the timeline of parts for an assistant message:
// reasoning parts, tool call/result pairs, and text output parts.
// Each part type is rendered by its corresponding component.

import { useMemo } from "react";
import type {
  Message,
  ReasoningPart as ReasoningPartType,
  ToolCallPart,
  ToolResultPart,
  TextPart,
} from "../../types/session";
import { getMessageParts } from "../../lib/message-normalizer";
import { ReasoningPart } from "./ReasoningPart";
import { ToolPart } from "./ToolPart";
import { OutputPart } from "./OutputPart";
import type { ToolTimelineItem } from "./ToolResult";

// ── Timeline item types ──────────────────────────────────────────

type TimelineItem =
  | {
      type: "reasoning";
      key: string;
      part: ReasoningPartType;
      index: number;
    }
  | ToolTimelineItem
  | {
      type: "output";
      key: string;
      part: TextPart;
      index: number;
    };

// ── Build timeline items ─────────────────────────────────────────

function assistantPartKey(
  messageId: string,
  kind: string,
  identifier: string | number,
): string {
  return `${String(messageId || "message")}:${kind}:${String(identifier || "part")}`;
}

/**
 * Build timeline items from a message's normalized parts.
 * Matches tool_call and tool_result parts by ID, merging them
 * into a single tool timeline item.
 */
function buildAssistantTimelineItems(message: Message): TimelineItem[] {
  const parts = getMessageParts(message);
  const items: TimelineItem[] = [];
  const toolIndexes = new Map<string, number>();
  let reasoningCount = 0;
  let outputCount = 0;

  for (const part of parts) {
    if (part.type === "reasoning") {
      items.push({
        type: "reasoning",
        key: assistantPartKey(message?.id, "reasoning", reasoningCount),
        part: part as ReasoningPartType,
        index: reasoningCount,
      });
      reasoningCount += 1;
      continue;
    }

    if (part.type === "tool_call") {
      const tcp = part as ToolCallPart;
      const toolCallId = String(
        tcp.id || assistantPartKey(message?.id, "tool", items.length),
      );
      const existingIndex = toolIndexes.get(toolCallId);

      if (typeof existingIndex === "number") {
        const existing = items[existingIndex] as ToolTimelineItem;
        items[existingIndex] = {
          ...existing,
          toolCall: tcp,
          name: tcp.name || existing.name,
        };
        continue;
      }

      toolIndexes.set(toolCallId, items.length);
      items.push({
        type: "tool",
        key: assistantPartKey(message?.id, "tool", toolCallId),
        toolCallId,
        name: tcp.name || "tool",
        toolCall: tcp,
        toolResult: null,
      });
      continue;
    }

    if (part.type === "tool_result") {
      const trp = part as ToolResultPart;
      const toolCallId = String(trp.tool_call_id || "");
      let existingIndex = toolIndexes.get(toolCallId);

      // Fallback: match by name if no tool_call_id match
      if (typeof existingIndex !== "number" && trp.name) {
        for (let i = items.length - 1; i >= 0; i--) {
          const item = items[i];
          if (
            item.type === "tool" &&
            !(item as ToolTimelineItem).toolResult &&
            (item as ToolTimelineItem).name === trp.name
          ) {
            existingIndex = i;
            if (toolCallId) {
              toolIndexes.set(toolCallId, i);
            }
            break;
          }
        }
      }

      if (typeof existingIndex === "number") {
        const existing = items[existingIndex] as ToolTimelineItem;
        items[existingIndex] = {
          ...existing,
          name: trp.name || existing.name,
          toolResult: trp,
        };
        continue;
      }

      const fallbackId =
        toolCallId ||
        assistantPartKey(message?.id, "tool-result", items.length);
      toolIndexes.set(fallbackId, items.length);
      items.push({
        type: "tool",
        key: assistantPartKey(message?.id, "tool", fallbackId),
        toolCallId: fallbackId,
        name: trp.name || "tool",
        toolCall: null,
        toolResult: trp,
      });
      continue;
    }

    // Default: output text
    items.push({
      type: "output",
      key: assistantPartKey(message?.id, "output", outputCount),
      part: part as TextPart,
      index: outputCount,
    });
    outputCount += 1;
  }

  return items;
}

// ── Component ────────────────────────────────────────────────────

interface AssistantTimelineProps {
  /** The assistant message. */
  message: Message;
}

function AssistantTimelineInner({ message }: AssistantTimelineProps) {
  const items = useMemo(
    () => buildAssistantTimelineItems(message),
    [message],
  );

  if (!items.length) {
    return null;
  }

  // Find the index of the last reasoning item (for auto-open logic)
  const lastReasoningIndex = items.reduce(
    (lastIndex, item, index) =>
      item.type === "reasoning" ? index : lastIndex,
    -1,
  );

  const isInProgress = message.status === "in_progress";

  return (
    <div className="assistant-timeline">
      {items.map((item, index) => {
        if (item.type === "reasoning") {
          const defaultOpen =
            isInProgress && index === lastReasoningIndex;
          return (
            <ReasoningPart
              key={item.key}
              part={item.part}
              partKey={item.key}
              defaultOpen={defaultOpen}
            />
          );
        }

        if (item.type === "tool") {
          const defaultOpen =
            isInProgress && !item.toolResult;
          return (
            <ToolPart
              key={item.key}
              toolItem={item}
              message={message}
              defaultOpen={defaultOpen}
            />
          );
        }

        // Output
        const isPending =
          isInProgress && index === items.length - 1;
        return (
          <OutputPart
            key={item.key}
            partKey={item.key}
            text={item.part.text || ""}
            isPending={isPending}
          />
        );
      })}
    </div>
  );
}

export { AssistantTimelineInner as AssistantTimeline, buildAssistantTimelineItems };
export type { TimelineItem };
