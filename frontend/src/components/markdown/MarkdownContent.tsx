// ── MarkdownContent ──────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/markdown.js
//
// Renders Markdown text using react-markdown with rehype-highlight
// for syntax highlighting.  Provides a custom code component that
// wraps fenced code blocks in the CodeBlock component (with copy
// button and language label).

import React, { memo, useMemo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CodeBlock } from "./CodeBlock";
import { cn } from "../../lib/cn";

// ── Helper: extractText ───────────────────────────────────────────

/**
 * Recursively extract plain text from React children (which may be
 * strings, numbers, or React elements with nested children).
 * Used to get copyable plain text from rehype-highlight output.
 * Also acts as a safe fallback: if any node is an unexpected object
 * type, it returns "[unknown]" rather than "[object Object]".
 */
function extractText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (React.isValidElement(node)) {
    // Prefer explicit text content
    const { children: kids, dangerouslySetInnerHTML } = node.props;
    if (dangerouslySetInnerHTML?.__html) {
      return dangerouslySetInnerHTML.__html.replace(/<[^>]*>/g, "");
    }
    if (kids != null) return extractText(kids);
    return "";
  }
  // Primitive fallback — never return "[object Object]"
  return "";
}

interface MarkdownContentProps {
  /** Raw markdown text to render. */
  content: string;
  /** Additional CSS class names for the wrapper. */
  className?: string;
  /** Whether this output is still streaming (pending). */
  isPending?: boolean;
}

function MarkdownContentInner({
  content,
  className,
  isPending = false,
}: MarkdownContentProps) {
  const components = useMemo(
    () => ({
      code({
        className: codeClassName,
        children,
        node,
        ...rest
      }: React.HTMLAttributes<HTMLElement> & {
        inline?: boolean;
        node?: unknown;
      }) {
        // Detect fenced code blocks: they have a language class
        // e.g. "language-python" or "hljs language-python" from rehype-highlight
        const match = /language-(\w+)/.exec(codeClassName || "");
        const hasHljs = codeClassName?.includes("hljs");
        const isInline = !match && !hasHljs;

        if (isInline) {
          return (
            <code className={codeClassName} {...rest}>
              {children}
            </code>
          );
        }

        const language = match ? match[1] : "";

        // Extract plain text from children for copy-to-clipboard.
        // Also serves as a safe fallback when children contains
        // unexpected objects (e.g. from rehype-highlight edge cases).
        const plainText = extractText(children);

        // Safety net: if extracted text contains "[object " artifacts,
        // the children tree likely has bad nodes — fall back to plain text.
        const hasObjectArtifact = plainText.indexOf("[object ") !== -1;

        return (
          <CodeBlock content={plainText} language={language} codeClassName={codeClassName}>
            {hasObjectArtifact ? plainText : children}
          </CodeBlock>
        );
      },
      // Table support
      table({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) {
        return (
          <div className="table-wrap">
            <table {...props}>{children}</table>
          </div>
        );
      },
    }),
    [],
  );

  if (!content || !content.trim()) {
    return null;
  }

  return (
    <div className={cn("markdown-body", isPending && "is-pending", className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </Markdown>
    </div>
  );
}

export const MarkdownContent = memo(MarkdownContentInner);
