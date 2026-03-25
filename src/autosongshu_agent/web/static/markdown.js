import { escapeHtml, sanitizeUrl } from "./state.js";

const _markdownCache = new Map();
const _MAX_CACHE_SIZE = 150;
const _CACHE_KEY_LENGTH = 64;

function _makeCacheKey(text) {
  const len = text.length;
  const tail = text.slice(-_CACHE_KEY_LENGTH);
  return `${len}:${tail}`;
}

export function getCachedMarkdown(text) {
  const key = _makeCacheKey(text);
  if (_markdownCache.has(key)) {
    return _markdownCache.get(key);
  }
  const html = renderMarkdown(text);
  if (_markdownCache.size >= _MAX_CACHE_SIZE) {
    const firstKey = _markdownCache.keys().next().value;
    _markdownCache.delete(firstKey);
  }
  _markdownCache.set(key, html);
  return html;
}

export function clearMarkdownCache() {
  _markdownCache.clear();
}

const PYTHON_HIGHLIGHT_PATTERN =
  /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|\b(from|import|as|if|elif|else|for|while|try|except|finally|with|return|yield|in|is|not|and|or|def|class|pass|break|continue|raise|assert|global|nonlocal|del|async|await|lambda)\b|\b(True|False|None)\b|\b(\d+(?:\.\d+)?)\b|(@[A-Za-z_]\w*)|\b([A-Za-z_]\w*)(?=\()/gm;
const JSON_HIGHLIGHT_PATTERN =
  /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

function normalizeCodeLanguage(language) {
  return String(language || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "");
}

function highlightByPattern(source, pattern, renderMatch) {
  const text = String(source ?? "");
  let html = "";
  let lastIndex = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    html += escapeHtml(text.slice(lastIndex, index));
    html += renderMatch(match);
    lastIndex = index + String(match[0] || "").length;
  }

  html += escapeHtml(text.slice(lastIndex));
  return html;
}

function renderCodeToken(kind, value) {
  return `<span class="code-token code-token-${kind}">${escapeHtml(String(value ?? ""))}</span>`;
}

function highlightPythonCode(source) {
  return highlightByPattern(source, PYTHON_HIGHLIGHT_PATTERN, (match) => {
    if (match[1]) {
      return renderCodeToken("comment", match[1]);
    }
    if (match[2]) {
      return renderCodeToken("string", match[2]);
    }
    if (match[3]) {
      return renderCodeToken("keyword", match[3]);
    }
    if (match[4]) {
      return renderCodeToken("constant", match[4]);
    }
    if (match[5]) {
      return renderCodeToken("number", match[5]);
    }
    if (match[6]) {
      return renderCodeToken("decorator", match[6]);
    }
    if (match[7]) {
      return renderCodeToken("function", match[7]);
    }
    return escapeHtml(String(match[0] || ""));
  });
}

function highlightJsonCode(source) {
  return highlightByPattern(source, JSON_HIGHLIGHT_PATTERN, (match) => {
    if (match[1]) {
      const tokenKind = match[2] ? "property" : "string";
      return `${renderCodeToken(tokenKind, match[1])}${escapeHtml(match[2] || "")}`;
    }
    if (match[3]) {
      return renderCodeToken("constant", match[3]);
    }
    if (match[4]) {
      return renderCodeToken("number", match[4]);
    }
    return escapeHtml(String(match[0] || ""));
  });
}

function renderDiffLine(kind, line) {
  const safeLine = escapeHtml(String(line ?? ""));
  return `<span class="code-diff-line code-diff-line-${kind}">${safeLine || "&nbsp;"}</span>`;
}

function highlightDiffCode(source) {
  return String(source ?? "")
    .split("\n")
    .map((line) => {
      if (line.startsWith("@@")) {
        return renderDiffLine("hunk", line);
      }
      if (line.startsWith("+") && !line.startsWith("+++")) {
        return renderDiffLine("add", line);
      }
      if (line.startsWith("-") && !line.startsWith("---")) {
        return renderDiffLine("remove", line);
      }
      if (
        line.startsWith("diff ") ||
        line.startsWith("index ") ||
        line.startsWith("---") ||
        line.startsWith("+++")
      ) {
        return renderDiffLine("meta", line);
      }
      return renderDiffLine("plain", line);
    })
    .join("");
}

function highlightCode(source, language) {
  const normalizedLanguage = normalizeCodeLanguage(language);
  if (normalizedLanguage === "python" || normalizedLanguage === "py") {
    return highlightPythonCode(source);
  }
  if (normalizedLanguage === "json") {
    return highlightJsonCode(source);
  }
  if (normalizedLanguage === "diff") {
    return highlightDiffCode(source);
  }
  return escapeHtml(String(source ?? ""));
}

export function applyInlineMarkdown(rawText) {
  const placeholders = [];
  const store = (html) => `@@HTML_${placeholders.push(html) - 1}@@`;

  let text = String(rawText ?? "");
  text = text.replace(/`([^`]+)`/g, (_, code) => store(`<code>${escapeHtml(code)}</code>`));
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, label, url) => {
    const safeUrl = sanitizeUrl(url);
    if (!safeUrl) {
      return escapeHtml(label);
    }
    return store(
      `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`,
    );
  });

  text = escapeHtml(text);
  text = text.replace(/(\*\*|__)(.+?)\1/g, "<strong>$2</strong>");
  text = text.replace(/(^|[\s(])(\*|_)([^*_][\s\S]*?)(\2)(?=[\s).,!?:;]|$)/g, "$1<em>$3</em>");
  text = text.replace(/@@HTML_(\d+)@@/g, (_, index) => placeholders[Number(index)] || "");
  return text;
}

export function renderCodeBlock(content, language = "", title = "") {
  const normalizedLanguage = normalizeCodeLanguage(language);
  const titleHtml = title ? `<span class="code-title">${escapeHtml(title)}</span>` : "";
  const langHtml = normalizedLanguage ? `<span class="code-lang">${escapeHtml(normalizedLanguage)}</span>` : "";
  const chromeHtml = `
    <span class="code-window-chrome" aria-hidden="true">
      <span class="code-window-dot is-close"></span>
      <span class="code-window-dot is-minimize"></span>
      <span class="code-window-dot is-expand"></span>
    </span>
  `;
  const highlightedCode = highlightCode(content, normalizedLanguage);
  return `
    <div class="code-shell code-shell-vscode${normalizedLanguage ? ` code-shell-${escapeHtml(normalizedLanguage)}` : ""}">
      <div class="code-head">
        ${chromeHtml}
        <div class="code-head-meta">${titleHtml}${langHtml}</div>
      </div>
      <pre class="code-block"><code class="code-language-${escapeHtml(normalizedLanguage || "plain")}">${highlightedCode}</code></pre>
    </div>
  `;
}

export function renderJsonBlock(label, value) {
  const pretty = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return renderCodeBlock(pretty, "json", label);
}

function splitMarkdownTableRow(line) {
  const trimmed = String(line ?? "").trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!trimmed) {
    return [];
  }

  const cells = [];
  let current = "";
  let escaping = false;

  for (const char of trimmed) {
    if (escaping) {
      current += char;
      escaping = false;
      continue;
    }
    if (char === "\\") {
      escaping = true;
      continue;
    }
    if (char === "|") {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }

  cells.push(current.trim());
  return cells;
}

function isMarkdownTable(lines) {
  if (!Array.isArray(lines) || lines.length < 2 || !lines[0].includes("|")) {
    return false;
  }

  const dividerCells = splitMarkdownTableRow(lines[1]);
  if (!dividerCells.length) {
    return false;
  }

  return dividerCells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function tableAlignment(cell) {
  const normalized = String(cell ?? "").replace(/\s+/g, "");
  if (normalized.startsWith(":") && normalized.endsWith(":")) {
    return "center";
  }
  if (normalized.endsWith(":")) {
    return "right";
  }
  return "left";
}

function renderMarkdownTable(lines) {
  const headerCells = splitMarkdownTableRow(lines[0]);
  const dividerCells = splitMarkdownTableRow(lines[1]);
  const alignments = dividerCells.map((cell) => tableAlignment(cell));
  const bodyRows = lines.slice(2).filter((line) => line.trim());

  const thead = `<thead><tr>${headerCells
    .map((cell, index) => `<th class="table-align-${alignments[index] || "left"}">${applyInlineMarkdown(cell)}</th>`)
    .join("")}</tr></thead>`;
  const tbody = bodyRows.length
    ? `<tbody>${bodyRows
        .map((row) => {
          const cells = splitMarkdownTableRow(row);
          return `<tr>${headerCells
            .map(
              (_, index) =>
                `<td class="table-align-${alignments[index] || "left"}">${applyInlineMarkdown(cells[index] || "")}</td>`,
            )
            .join("")}</tr>`;
        })
        .join("")}</tbody>`
    : "";

  return `<div class="table-wrap"><table>${thead}${tbody}</table></div>`;
}

function isFenceTokenLine(line) {
  return /^@@FENCE_(\d+)@@$/.test(String(line ?? "").trim());
}

function isBulletListLine(line) {
  return /^\s*[-*+]\s+/.test(String(line ?? ""));
}

function isOrderedListLine(line) {
  return /^\s*\d+\.\s+/.test(String(line ?? ""));
}

function isHeadingLine(line) {
  return /^\s*#{1,6}\s+/.test(String(line ?? ""));
}

function isBlockquoteLine(line) {
  return /^>\s?/.test(String(line ?? ""));
}

function isMarkdownTableStart(lines, index) {
  return isMarkdownTable(lines.slice(index, index + 2));
}

function renderMarkdownSegment(segment, fenceBlocks) {
  const trimmed = segment.trim();
  if (!trimmed) {
    return "";
  }

  const lines = trimmed.split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const currentLine = lines[index];
    const currentTrimmed = currentLine.trim();

    if (!currentTrimmed) {
      index += 1;
      continue;
    }

    if (isFenceTokenLine(currentLine)) {
      const fenceMatch = currentTrimmed.match(/^@@FENCE_(\d+)@@$/);
      const fence = fenceBlocks[Number(fenceMatch?.[1] || 0)] || { language: "", code: "" };
      blocks.push(renderCodeBlock(fence.code, fence.language));
      index += 1;
      continue;
    }

    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [lines[index], lines[index + 1]];
      index += 2;
      while (index < lines.length) {
        const row = lines[index];
        if (!row.trim() || !row.includes("|")) {
          break;
        }
        if (isFenceTokenLine(row) || isHeadingLine(row) || isBulletListLine(row) || isOrderedListLine(row)) {
          break;
        }
        tableLines.push(row);
        index += 1;
      }
      blocks.push(renderMarkdownTable(tableLines));
      continue;
    }

    if (isBulletListLine(currentLine)) {
      const listLines = [];
      while (index < lines.length && isBulletListLine(lines[index])) {
        listLines.push(lines[index]);
        index += 1;
      }
      blocks.push(
        `<ul>${listLines
          .map((line) => `<li>${applyInlineMarkdown(line.replace(/^\s*[-*+]\s+/, ""))}</li>`)
          .join("")}</ul>`,
      );
      continue;
    }

    if (isOrderedListLine(currentLine)) {
      const listLines = [];
      while (index < lines.length && isOrderedListLine(lines[index])) {
        listLines.push(lines[index]);
        index += 1;
      }
      blocks.push(
        `<ol>${listLines
          .map((line) => `<li>${applyInlineMarkdown(line.replace(/^\s*\d+\.\s+/, ""))}</li>`)
          .join("")}</ol>`,
      );
      continue;
    }

    if (isHeadingLine(currentLine)) {
      const match = currentLine.match(/^\s*(#{1,6})\s+(.+)$/);
      const level = match ? match[1].length : 2;
      const text = match ? match[2] : currentLine;
      blocks.push(`<h${level}>${applyInlineMarkdown(text)}</h${level}>`);
      index += 1;
      continue;
    }

    if (isBlockquoteLine(currentLine)) {
      const quoteLines = [];
      while (index < lines.length && isBlockquoteLine(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(`<blockquote>${renderMarkdown(quoteLines.join("\n"))}</blockquote>`);
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        break;
      }
      if (
        isFenceTokenLine(line) ||
        isMarkdownTableStart(lines, index) ||
        isBulletListLine(line) ||
        isOrderedListLine(line) ||
        isHeadingLine(line) ||
        isBlockquoteLine(line)
      ) {
        break;
      }
      paragraphLines.push(line);
      index += 1;
    }

    if (paragraphLines.length) {
      blocks.push(`<p>${paragraphLines.map((line) => applyInlineMarkdown(line)).join("<br>")}</p>`);
      continue;
    }

    index += 1;
  }

  return blocks.join("");
}

export function renderMarkdown(source) {
  const raw = String(source ?? "").replace(/\r\n/g, "\n").trim();
  if (!raw) {
    return "";
  }

  const fenceBlocks = [];
  const withFenceTokens = raw.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, (_, language, code) => {
    const index = fenceBlocks.push({
      language: String(language || "").trim(),
      code: String(code || "").replace(/\n$/, ""),
    }) - 1;
    return `\n@@FENCE_${index}@@\n`;
  });

  return withFenceTokens
    .split(/\n{2,}/)
    .map((segment) => renderMarkdownSegment(segment, fenceBlocks))
    .join("");
}
