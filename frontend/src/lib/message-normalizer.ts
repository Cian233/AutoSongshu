// ── Message Normalization ────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/state.js
//
// This module handles the normalization, deduplication, and merging
// of message parts received from the server.  The logic is critical
// for correct streaming display of assistant responses.
//
// Key concepts:
//   - Parts are normalized to a canonical set of types:
//       input_text, output_text, reasoning, tool_call, tool_result
//   - Consecutive text parts of the same type are merged (streaming
//     text is appended to the previous part).
//   - Tool calls and results are matched by ID and deduplicated.
//   - Assistant parts go through an additional "compaction" step
//     that merges parts based on fuzzy matching (prefix matching for
//     text, exact ID matching for tool calls/results).

import type {
  Message,
  MessagePart,
  TextPart,
  ReasoningPart,
  ToolCallPart,
  ToolResultPart,
  SessionDetail,
  SessionSummary,
} from "../types/session";

// ── Internal: safeStringify ─────────────────────────────────────

/**
 * Safely convert any value to a string.
 * - Primitives are converted via String().
 * - Objects (including arrays) are serialized via JSON.stringify().
 * - Prevents "[object Object]" display bugs.
 */
function safeStringify(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

// ── Internal: fingerprintText ───────────────────────────────────

/**
 * Create a compact fingerprint for text content.
 * For short text, returns "length:text".  For long text, returns
 * "length:first48:last48" to avoid storing huge strings in signatures.
 */
function fingerprintText(value: unknown, edge = 48): string {
  const text = String(value ?? "");
  if (!text) {
    return "0";
  }
  if (text.length <= edge * 2) {
    return `${text.length}:${text}`;
  }
  return `${text.length}:${text.slice(0, edge)}:${text.slice(-edge)}`;
}

// ── Internal: stableSerializeValue ──────────────────────────────

/**
 * Deterministically serialize a value to a stable string representation.
 * Used for comparing tool arguments in render signatures.
 */
function stableSerializeValue(value: unknown): string {
  if (value === null || value === undefined) {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerializeValue(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>)
      .sort()
      .map(
        (key) =>
          `${key}:${stableSerializeValue((value as Record<string, unknown>)[key])}`,
      )
      .join(",")}}`;
  }
  return String(value);
}

// ── Internal: summarizeMessagePart ──────────────────────────────

/**
 * Create a short summary string for a message part, used in render signatures.
 */
function summarizeMessagePart(part: MessagePart): string {
  const type = String(part?.type || "");
  if (!type) {
    return "unknown";
  }
  if (
    type === "input_text" ||
    type === "output_text" ||
    type === "reasoning"
  ) {
    return `${type}:${fingerprintText((part as TextPart | ReasoningPart).text || "")}`;
  }
  if (type === "tool_call") {
    const tcp = part as ToolCallPart;
    return `${type}:${String(tcp.id || tcp.name || "")}:${fingerprintText(stableSerializeValue(tcp.arguments || {}))}`;
  }
  if (type === "tool_result") {
    const trp = part as ToolResultPart;
    return `${type}:${String(trp.tool_call_id || trp.name || "")}:${fingerprintText(
      stableSerializeValue(Array.isArray(trp.content) ? trp.content : []),
    )}`;
  }
  return type;
}

// ── Internal: createMessageRenderSignature ──────────────────────

/**
 * Compute a render signature for a message.
 * The signature captures the message metadata and the last 3 parts
 * to detect meaningful changes that require re-rendering.
 */
function createMessageRenderSignature(
  message: Partial<Message>,
  content: MessagePart[],
): string {
  const tail = content
    .slice(-3)
    .map((part) => summarizeMessagePart(part))
    .join("|");
  return [
    String(message?.role || "assistant"),
    String(message?.status || ""),
    String(message?.error || ""),
    String(message?.updated_at || ""),
    String(message?.order_index || ""),
    String(content.length),
    tail,
  ].join("::");
}

// ── Internal: normalizeStoredMessage ────────────────────────────

/**
 * Normalize a raw message from the server into the canonical form.
 * Adds a render_signature for change detection.
 */
function normalizeStoredMessage(message: Record<string, unknown>): Message {
  const role = String(message?.role || "assistant") as Message["role"];
  const content = normalizeMessageContent(
    message?.content || [],
    role,
  );
  return {
    ...(message as unknown as Message),
    role,
    content,
    render_signature: createMessageRenderSignature(message, content),
  };
}

// ── Internal: appendNormalizedPart ──────────────────────────────

/**
 * Append a normalized part to the parts array, merging with the
 * previous part when possible (same type text streaming, or
 * deduplication of tool calls/results by ID).
 */
function appendNormalizedPart(
  parts: MessagePart[],
  part: MessagePart | null,
): void {
  if (!part) {
    return;
  }

  const type = String(part.type || "").toLowerCase();

  // Text-like parts: merge consecutive parts of the same type
  if (
    type === "input_text" ||
    type === "output_text" ||
    type === "reasoning"
  ) {
    const text = String(
      (part as TextPart | ReasoningPart).text || "",
    ).trim();
    if (!text) {
      return;
    }

    const last = parts[parts.length - 1];
    if (
      last &&
      String(last.type || "").toLowerCase() === type
    ) {
      const previousText = String(
        (last as TextPart | ReasoningPart).text || "",
      ).trim();
      // Skip if text is identical or previous already contains the new text
      if (text === previousText || previousText.startsWith(text)) {
        return;
      }
      // Extend previous text if new text is a continuation
      if (text.startsWith(previousText)) {
        (last as TextPart | ReasoningPart).text = text;
        return;
      }
    }

    parts.push({ type, text } as TextPart | ReasoningPart);
    return;
  }

  // Tool call deduplication by ID
  const last = parts[parts.length - 1];
  if (
    last &&
    type === "tool_call" &&
    String(last.type || "").toLowerCase() === "tool_call"
  ) {
    if (
      String((last as ToolCallPart).id || "") ===
      String((part as ToolCallPart).id || "")
    ) {
      parts[parts.length - 1] = part;
      return;
    }
  }

  // Tool result deduplication by tool_call_id + name
  if (
    last &&
    type === "tool_result" &&
    String(last.type || "").toLowerCase() === "tool_result"
  ) {
    if (
      String((last as ToolResultPart).tool_call_id || "") ===
        String((part as ToolResultPart).tool_call_id || "") &&
      String((last as ToolResultPart).name || "") ===
        String((part as ToolResultPart).name || "")
    ) {
      parts[parts.length - 1] = part;
      return;
    }
  }

  parts.push(part);
}

// ── Internal: matchScore ────────────────────────────────────────

/**
 * Score how well an existing part matches an incoming part.
 * Higher scores indicate a better match.
 *   - 500+: Exact ID match (tool_call, tool_result)
 *   - 400+: Exact text match
 *   - 300+: Prefix text match (streaming continuation)
 *   - 100:  Full JSON equality
 *   - 0:    No match
 */
function matchScore(existing: MessagePart, incoming: MessagePart): number {
  const existingType = String(existing?.type || "").toLowerCase();
  const incomingType = String(incoming?.type || "").toLowerCase();
  if (existingType !== incomingType) {
    return 0;
  }

  if (
    existingType === "input_text" ||
    existingType === "output_text" ||
    existingType === "reasoning"
  ) {
    const existingText = String(
      (existing as TextPart | ReasoningPart).text || "",
    ).trim();
    const incomingText = String(
      (incoming as TextPart | ReasoningPart).text || "",
    ).trim();
    if (!existingText || !incomingText) {
      return 0;
    }
    if (existingText === incomingText) {
      return 400 + existingText.length;
    }
    if (
      existingText.startsWith(incomingText) ||
      incomingText.startsWith(existingText)
    ) {
      return 300 + Math.min(existingText.length, incomingText.length);
    }
    return 0;
  }

  if (existingType === "tool_call") {
    return String((existing as ToolCallPart).id || "") ===
      String((incoming as ToolCallPart).id || "")
      ? 500
      : 0;
  }

  if (existingType === "tool_result") {
    return String((existing as ToolResultPart).tool_call_id || "") ===
      String((incoming as ToolResultPart).tool_call_id || "") &&
      String((existing as ToolResultPart).name || "") ===
        String((incoming as ToolResultPart).name || "")
      ? 500
      : 0;
  }

  return JSON.stringify(existing) === JSON.stringify(incoming) ? 100 : 0;
}

// ── Internal: findBestMatchIndex ────────────────────────────────

/**
 * Find the index of the best matching part in the compacted array,
 * starting from startIndex.
 */
function findBestMatchIndex(
  parts: MessagePart[],
  incoming: MessagePart,
  startIndex = 0,
): number {
  let bestIndex = -1;
  let bestScore = 0;
  for (
    let index = Math.max(0, startIndex);
    index < parts.length;
    index += 1
  ) {
    const score = matchScore(parts[index], incoming);
    if (score <= bestScore) {
      continue;
    }
    bestIndex = index;
    bestScore = score;
    if (score >= 500) {
      break;
    }
  }
  return bestIndex;
}

// ── Internal: mergeNormalizedPart ───────────────────────────────

/**
 * Merge an existing part with an incoming part of the same type.
 * For text parts, keeps the longer text.  For tool calls, keeps
 * the longer arguments JSON.
 */
function mergeNormalizedPart(
  existing: MessagePart,
  incoming: MessagePart,
): MessagePart {
  const type = String(existing?.type || "").toLowerCase();

  if (
    type === "input_text" ||
    type === "output_text" ||
    type === "reasoning"
  ) {
    const existingText = String(
      (existing as TextPart | ReasoningPart).text || "",
    ).trim();
    const incomingText = String(
      (incoming as TextPart | ReasoningPart).text || "",
    ).trim();
    if (incomingText.startsWith(existingText)) {
      return { type, text: incomingText } as TextPart | ReasoningPart;
    }
    return existingText.length >= incomingText.length
      ? existing
      : incoming;
  }

  if (type === "tool_call") {
    const existingArgs = JSON.stringify(
      (existing as ToolCallPart).arguments || {},
    );
    const incomingArgs = JSON.stringify(
      (incoming as ToolCallPart).arguments || {},
    );
    return existingArgs.length >= incomingArgs.length ? existing : incoming;
  }

  return incoming;
}

// ── compactAssistantParts ───────────────────────────────────────

/**
 * Compact an array of assistant message parts by merging duplicates
 * and streaming continuations.  Uses fuzzy matching to find the best
 * existing part to merge with.
 *
 * This is the core deduplication logic for streaming assistant responses.
 */
export function compactAssistantParts(parts: MessagePart[]): MessagePart[] {
  const compacted: MessagePart[] = [];
  for (const part of parts) {
    const matchIndex = findBestMatchIndex(compacted, part, 0);
    if (matchIndex !== -1) {
      compacted[matchIndex] = mergeNormalizedPart(
        compacted[matchIndex],
        part,
      );
      continue;
    }
    appendNormalizedPart(compacted, part);
  }
  return compacted;
}

// ── normalizeMessagePart ────────────────────────────────────────

/**
 * Normalize a single raw message part into the canonical form.
 *
 * Handles various input formats from different LLM providers:
 *   - "reasoning" / "thinking" / "thinking_text" -> "reasoning"
 *   - "output_text" / "text" / "progress_text" / "input_text" -> "output_text" (assistant) or "input_text" (user)
 *   - "tool_call" / "tool_use" -> "tool_call"
 *   - "tool_result" -> "tool_result"
 *   - Fallback: extract text and wrap as "output_text"
 *
 * @param part - Raw message part from the server.
 * @param role - Message role ("user" or "assistant").
 * @returns Normalized MessagePart, or null if the part is empty.
 */
export function normalizeMessagePart(
  part: unknown,
  role: string = "assistant",
): MessagePart | null {
  if (!part || typeof part !== "object") {
    return null;
  }

  const normalizedRole = String(role || "").toLowerCase();
  const raw = part as Record<string, unknown>;
  const type = String(raw.type || "").toLowerCase();

  // User messages: everything becomes input_text
  if (normalizedRole === "user") {
    const text = safeStringify(raw.text || raw.content).trim();
    return text ? { type: "input_text", text } : null;
  }

  // Reasoning / thinking variants
  if (type === "reasoning" || type === "thinking" || type === "thinking_text") {
    const text = safeStringify(
      raw.text || raw.thinking_text || raw.thinking,
    ).trim();
    return text ? { type: "reasoning", text } : null;
  }

  // Text variants -> output_text
  if (
    type === "output_text" ||
    type === "text" ||
    type === "progress_text" ||
    type === "input_text"
  ) {
    const text = safeStringify(raw.text || raw.content).trim();
    return text ? { type: "output_text", text } : null;
  }

  // Tool call / tool use
  if (type === "tool_call" || type === "tool_use") {
    const argumentsPayload =
      raw.arguments && typeof raw.arguments === "object"
        ? (raw.arguments as Record<string, unknown>)
        : raw.input && typeof raw.input === "object"
          ? (raw.input as Record<string, unknown>)
          : { value: raw.arguments ?? raw.input ?? "" };
    const fallbackId = `tool:${String(raw.name || "tool")}:${JSON.stringify(argumentsPayload)}`;
    return {
      type: "tool_call",
      id: String(raw.id || fallbackId),
      name: String(raw.name || "tool"),
      arguments: argumentsPayload,
    } as ToolCallPart;
  }

  // Tool result
  if (type === "tool_result") {
    const rawContent = Array.isArray(raw.content)
      ? raw.content
      : Array.isArray(raw.output)
        ? raw.output
        : [];
    const content: TextPart[] = rawContent
      ? (rawContent as unknown[])
          .map((item) => {
            if (!item || typeof item !== "object") {
              return {
                type: "output_text" as const,
                text: safeStringify(item),
              };
            }
            const obj = item as Record<string, unknown>;
            const itemType = String(obj.type || "").toLowerCase();
            if (itemType === "output_text" || itemType === "text") {
              return {
                type: "output_text" as const,
                text: safeStringify(obj.text),
              };
            }
            return {
              type: "output_text" as const,
              text: JSON.stringify(item, null, 2),
            };
          })
          .filter((item) => {
            const txt = item.text;
            return typeof txt === "string" ? txt.trim() : txt != null;
          })
      : [];
    return {
      type: "tool_result",
      tool_call_id: String(raw.tool_call_id || raw.id || ""),
      name: String(raw.name || ""),
      content,
    } as ToolResultPart;
  }

  // Image
  if (type === "image") {
    const url = String(raw.url || "");
    return url ? { type: "image" as const, url } : null;
  }

  // Fallback: extract text
  const text = safeStringify(raw.text || raw.content).trim();
  return text ? { type: "output_text", text } : null;
}

// ── normalizeMessageContent ─────────────────────────────────────

/**
 * Normalize an array of raw message parts.
 * For assistant messages, applies compaction (deduplication + merging).
 * For user messages, only appends non-empty parts.
 *
 * @param content - Raw content array (or single item or null).
 * @param role    - Message role ("user" or "assistant").
 * @returns Normalized array of MessagePart.
 */
export function normalizeMessageContent(
  content: unknown,
  role: string = "assistant",
): MessagePart[] {
  const items = Array.isArray(content)
    ? content
    : content == null
      ? []
      : [content];
  const parts: MessagePart[] = [];
  for (const item of items) {
    appendNormalizedPart(parts, normalizeMessagePart(item, role));
  }
  return String(role || "").toLowerCase() === "assistant"
    ? compactAssistantParts(parts)
    : parts;
}

// ── upsertMessage ───────────────────────────────────────────────

/**
 * Insert or update a message in a session detail's messages array.
 *
 * - If a message with the same ID exists, it is merged (shallow merge).
 * - If not, the message is appended.
 * - Messages are sorted by order_index, then created_at.
 *
 * @param detail  - Session detail containing the messages array.
 * @param message - Raw message from the server (will be normalized).
 * @returns New SessionDetail with the updated messages array.
 */
export function upsertMessage(
  detail: SessionDetail,
  message: Record<string, unknown>,
): SessionDetail {
  const messages = Array.isArray(detail.messages)
    ? [...detail.messages]
    : [];
  const normalizedMessage = normalizeStoredMessage(message);
  const messageId = String(message.id || "");
  const index = messages.findIndex(
    (item) => String(item.id) === messageId,
  );
  if (index === -1) {
    messages.push(normalizedMessage);
  } else {
    messages[index] = { ...messages[index], ...normalizedMessage };
  }
  messages.sort(
    (left, right) =>
      Number(left.order_index || 0) - Number(right.order_index || 0) ||
      String(left.created_at || "").localeCompare(
        String(right.created_at || ""),
      ),
  );
  return { ...detail, messages };
}

// ── getMessageParts ─────────────────────────────────────────────

/**
 * Get the normalized parts array for a message.
 * If the message already has a render_signature (i.e., it was
 * previously normalized), returns the content directly.
 * Otherwise, normalizes the content first.
 */
export function getMessageParts(message: Partial<Message>): MessagePart[] {
  if (
    Array.isArray(message?.content) &&
    typeof message?.render_signature === "string"
  ) {
    return message.content as MessagePart[];
  }
  return normalizeMessageContent(
    message?.content || [],
    String(message?.role || "assistant"),
  );
}

// ── messageText ─────────────────────────────────────────────────

/**
 * Extract all text content from a message (input_text + output_text parts),
 * joined by double newlines.
 */
export function messageText(message: Partial<Message>): string {
  return getMessageParts(message)
    .filter(
      (part) =>
        part.type === "input_text" || part.type === "output_text",
    )
    .map((part) => {
      const txt = (part as TextPart).text;
      if (typeof txt === "string") return txt.trim();
      if (txt != null && typeof txt === "object") {
        try { return JSON.stringify(txt, null, 2); } catch { return String(txt); }
      }
      return String(txt ?? "").trim();
    })
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

// ── computeRenderSignature ──────────────────────────────────────

/**
 * Compute the render signature for a message.
 * This is used to detect whether a message has changed enough
 * to warrant a re-render.
 */
export function computeRenderSignature(
  message: Partial<Message>,
  content: MessagePart[],
): string {
  return createMessageRenderSignature(message, content);
}

// ── normalizeSessionDetail ──────────────────────────────────────

/**
 * Normalize a raw session detail from the server.
 * Normalizes all messages and sorts them by order_index / created_at.
 */
export function normalizeSessionDetail(
  raw: Record<string, unknown>,
): SessionDetail {
  const messages = Array.isArray(raw?.messages)
    ? (raw.messages as Record<string, unknown>[])
        .map((message) => normalizeStoredMessage(message))
        .sort(
          (left, right) =>
            Number(left.order_index || 0) -
              Number(right.order_index || 0) ||
            String(left.created_at || "").localeCompare(
              String(right.created_at || ""),
            ),
        )
    : [];

  return {
    ...(raw as unknown as SessionDetail),
    messages,
  };
}

// ── normalizeSessionSummary ─────────────────────────────────────

/**
 * Normalize a raw session summary from the server.
 * Ensures the ID is a string and applies defaults for optional fields.
 */
export function normalizeSessionSummary(
  raw: Record<string, unknown>,
): SessionSummary {
  return {
    id: String(raw.id || ""),
    project_id: String(raw.project_id || ""),
    title: raw.title != null ? String(raw.title) : undefined,
    status: raw.status != null
      ? (String(raw.status) as SessionSummary["status"])
      : undefined,
    created_at: raw.created_at != null
      ? String(raw.created_at)
      : undefined,
    updated_at: raw.updated_at != null
      ? String(raw.updated_at)
      : undefined,
    is_compacting: raw.is_compacting != null
      ? Boolean(raw.is_compacting)
      : undefined,
    mode: raw.mode != null ? String(raw.mode) : undefined,
    start_url: raw.start_url != null
      ? String(raw.start_url)
      : undefined,
    knowledge_base_count:
      raw.knowledge_base_count != null
        ? Number(raw.knowledge_base_count)
        : undefined,
    token_usage: raw.token_usage as SessionSummary["token_usage"],
    allowed_hosts: Array.isArray(raw.allowed_hosts)
      ? (raw.allowed_hosts as string[])
      : undefined,
    knowledge_base_ids: Array.isArray(raw.knowledge_base_ids)
      ? (raw.knowledge_base_ids as string[])
      : undefined,
  };
}
