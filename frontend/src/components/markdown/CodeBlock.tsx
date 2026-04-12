// ── CodeBlock ────────────────────────────────────────────────────
// Renders a fenced code block with syntax highlighting (via highlight.js),
// a language label, and a copy-to-clipboard button.

import { useCallback, useMemo, useRef, useState, memo, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import hljs from "highlight.js";

interface CodeBlockProps {
  /** The raw code content (without surrounding fences). Used for copy-to-clipboard. */
  content: string;
  /** Language identifier (e.g. "python", "json", "diff"). */
  language?: string;
  /** Optional title shown in the code header. */
  title?: string;
  /** Additional CSS class names for the outer shell. */
  className?: string;
  /**
   * Optional pre-rendered children (e.g. from rehype-highlight).
   * When provided, this is rendered inside <code> instead of the
   * plain text `content` string.
   */
  children?: ReactNode;
  /**
   * Optional CSS class name from react-markdown (e.g. "hljs language-python").
   * Merged into the <code> element's className to preserve highlight.js markers.
   */
  codeClassName?: string;
}

function CodeBlockInner({
  content,
  language = "",
  title,
  className,
  children,
  codeClassName,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }, [content]);

  const normalizedLanguage = language.trim().toLowerCase();

  // When children are provided (e.g. from rehype-highlight), use them directly.
  // Otherwise, highlight the content string ourselves.
  const highlighted = useMemo(() => {
    if (children !== undefined) return undefined;
    if (!normalizedLanguage || normalizedLanguage === "plain" || normalizedLanguage === "text") {
      return undefined;
    }
    try {
      const result = hljs.highlight(content, { language: normalizedLanguage, ignoreIllegals: true });
      return result.value;
    } catch {
      return undefined;
    }
  }, [children, content, normalizedLanguage]);

  return (
    <div
      className={cn(
        "code-shell",
        normalizedLanguage && `code-shell-${normalizedLanguage}`,
        className,
      )}
    >
      <div className="code-head">
        <span className="code-window-chrome" aria-hidden="true">
          <span className="code-window-dot is-close" />
          <span className="code-window-dot is-minimize" />
          <span className="code-window-dot is-expand" />
        </span>
        <div className="code-head-meta">
          {title && <span className="code-title">{title}</span>}
          {normalizedLanguage && (
            <span className="code-lang">{normalizedLanguage}</span>
          )}
        </div>
        <button
          type="button"
          className="code-copy-btn"
          onClick={handleCopy}
          title={copied ? "已复制" : "复制代码"}
          aria-label={copied ? "已复制" : "复制代码"}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre className="code-block">
        <code
          className={cn(
            highlighted && "hljs",
            codeClassName,
          )}
          dangerouslySetInnerHTML={
            highlighted ? { __html: highlighted } : undefined
          }
        >
          {highlighted ? undefined : (children ?? content)}
        </code>
      </pre>
    </div>
  );
}

export const CodeBlock = memo(CodeBlockInner);
