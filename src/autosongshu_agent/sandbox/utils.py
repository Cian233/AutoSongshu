from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

_PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")
_USER_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_MARKDOWN_FENCE_PATTERN = re.compile(r"^\s*```")
_CJK_CHARACTER_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CODE_TOKEN_PATTERN = re.compile(
    r"[=(){}\[\];<>]|"
    r"\b(?:def|class|import|from|return|raise|async|await|if|elif|else|for|while|try|except|with|lambda|"
    r"print|const|let|var|function|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b",
    re.IGNORECASE,
)
_STRUCTURED_DATA_LINE_PATTERN = re.compile(r"""^['"]?[A-Za-z0-9_.-]+['"]?\s*:\s*\S""")
_PROSE_BULLET_PATTERN = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)")
_PROSE_PUNCTUATION_PATTERN = re.compile(r"[。！？；：]|[.!?](?:\s|$)")
_RAW_CONTENT_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".php",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".rb",
        ".pl",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".swift",
        ".kt",
        ".kts",
        ".lua",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sql",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
    }
)
_RAW_CONTENT_CODE_FILENAMES = frozenset({"dockerfile", "makefile", "procfile"})


class SandboxError(RuntimeError):
    pass


def normalize_user_id(user_id: str) -> str:
    normalized = _USER_ID_SAFE_PATTERN.sub("-", str(user_id or "").strip()).strip("-.")
    return normalized or "local-default-user"


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def build_unified_diff(
    before: str, after: str, relative_path: str, max_chars: int
) -> tuple[str, bool]:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )
    return truncate_text(diff, max_chars)


def render_numbered_lines(lines: list[str], start_line: int) -> str:
    numbered: list[str] = []
    for offset, raw_line in enumerate(lines):
        line_number = start_line + offset
        stripped = raw_line.rstrip("\r\n")
        suffix = "\n" if raw_line.endswith(("\n", "\r")) else ""
        numbered.append(f"{line_number:>4}: {stripped}{suffix}")
    return "".join(numbered)


def detect_runtime_hints(stdout: str, stderr: str) -> list[str]:
    text = f"{stdout}\n{stderr}".lower()
    hints: list[str] = []

    if (
        "certificate_verify_failed" in text
        or "unable to get local issuer certificate" in text
    ):
        hints.append(
            "检测到 TLS 证书校验失败；对已授权目标可在 requests/httpx 中显式使用 verify=False 重试，并记录原因。"
        )
    elif "httpsconnectionpool" in text or "sslerror" in text:
        hints.append(
            "检测到 HTTPS/TLS 连接异常；如果目标证书链不完整或为自签名证书，请优先排查 verify/证书问题。"
        )

    if (
        "nameresolutionerror" in text
        or "failed to resolve" in text
        or "getaddrinfo failed" in text
    ):
        hints.append(
            "检测到 DNS 解析异常；请检查目标域名是否可解析、是否仍在有效期内，或是否需要代理/特定网络环境。"
        )

    if "connecttimeout" in text or "readtimeout" in text or "timed out" in text:
        hints.append("检测到超时；可在脚本中增加 timeout、重试机制，或降低并发。")

    return hints


def is_code_like_path(path: Path | None, *, language_hint: str | None = None) -> bool:
    if language_hint:
        return True
    if path is None:
        return False
    return (
        path.suffix.lower() in _RAW_CONTENT_CODE_EXTENSIONS
        or path.name.lower() in _RAW_CONTENT_CODE_FILENAMES
    )


def _looks_like_natural_language_line(text: str) -> bool:
    stripped = text.strip().strip("`")
    if not stripped:
        return False

    code_token_hits = len(_CODE_TOKEN_PATTERN.findall(stripped))
    if code_token_hits >= 3:
        return False

    cjk_count = len(_CJK_CHARACTER_PATTERN.findall(stripped))
    word_count = len(_WORD_PATTERN.findall(stripped))
    has_sentence_punctuation = bool(_PROSE_PUNCTUATION_PATTERN.search(stripped))
    has_bullet_prefix = bool(_PROSE_BULLET_PATTERN.match(stripped))
    has_heading_punctuation = ":" in stripped or "：" in stripped

    if not (has_sentence_punctuation or has_bullet_prefix or has_heading_punctuation):
        return False

    if has_heading_punctuation and code_token_hits == 0:
        return cjk_count >= 2 or word_count >= 2
    return cjk_count >= 4 or word_count >= 4


def _looks_like_code_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("#!"):
        return True
    if stripped.startswith(("```", "#", "//", "--", "/*", "*", "<!--", '"""', "'''")):
        return False
    return bool(
        _CODE_TOKEN_PATTERN.search(stripped)
        or _STRUCTURED_DATA_LINE_PATTERN.match(stripped)
    )


def _finalize_comment_block(
    block_stats: dict[str, int], totals: dict[str, int]
) -> None:
    if block_stats["lines"] <= 0:
        return
    totals["max_block_lines"] = max(totals["max_block_lines"], block_stats["lines"])
    totals["max_block_chars"] = max(totals["max_block_chars"], block_stats["chars"])
    block_stats["lines"] = 0
    block_stats["chars"] = 0


def validate_raw_file_content(
    content: str,
    *,
    path: Path | None = None,
    language_hint: str | None = None,
) -> None:
    if not is_code_like_path(path, language_hint=language_hint):
        return

    normalized = content.lstrip("\ufeff")
    lines = normalized.splitlines()
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if not non_empty_lines:
        return

    # Skip validation for very short files — false-positive prone.
    if len(non_empty_lines) <= 6:
        return

    if _MARKDOWN_FENCE_PATTERN.match(
        non_empty_lines[0]
    ) or _MARKDOWN_FENCE_PATTERN.match(non_empty_lines[-1]):
        raise SandboxError(
            "Sandbox file content must be raw code or raw file text only. Remove the Markdown code fences and resend the file content itself."
        )

    suffix = (path.suffix.lower() if path is not None else ".py") or ".py"
    line_comment_prefixes = (
        ("#",)
        if suffix in {".py", ".pyw", ".sh", ".bash", ".zsh", ".ps1"}
        else ("#", "//", "--")
    )
    in_triple_quote: str | None = None
    in_block_comment = False
    in_html_comment = False
    totals = {
        "code_lines": 0,
        "comment_prose_lines": 0,
        "comment_prose_chars": 0,
        "max_block_lines": 0,
        "max_block_chars": 0,
    }
    block_stats = {"lines": 0, "chars": 0}

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue

        comment_text: str | None = None

        if in_triple_quote:
            end_index = stripped.find(in_triple_quote)
            if end_index >= 0:
                comment_text = stripped[:end_index].strip()
                in_triple_quote = None
            else:
                comment_text = stripped
        elif in_block_comment:
            end_index = stripped.find("*/")
            if end_index >= 0:
                comment_text = stripped[:end_index].lstrip("*").strip()
                in_block_comment = False
            else:
                comment_text = stripped.lstrip("*").strip()
        elif in_html_comment:
            end_index = stripped.find("-->")
            if end_index >= 0:
                comment_text = stripped[:end_index].strip()
                in_html_comment = False
            else:
                comment_text = stripped
        elif stripped.startswith(('"""', "'''")):
            delimiter = stripped[:3]
            remainder = stripped[3:]
            end_index = remainder.find(delimiter)
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_triple_quote = delimiter
        elif stripped.startswith("/*"):
            remainder = stripped[2:]
            end_index = remainder.find("*/")
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_block_comment = True
        elif stripped.startswith("<!--"):
            remainder = stripped[4:]
            end_index = remainder.find("-->")
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_html_comment = True
        else:
            for prefix in line_comment_prefixes:
                if stripped.startswith(prefix):
                    comment_text = stripped[len(prefix) :].strip()
                    break

        if comment_text is not None:
            if _looks_like_natural_language_line(comment_text):
                block_stats["lines"] += 1
                block_stats["chars"] += len(comment_text)
                totals["comment_prose_lines"] += 1
                totals["comment_prose_chars"] += len(comment_text)
            continue

        _finalize_comment_block(block_stats, totals)

        if _looks_like_code_line(stripped):
            totals["code_lines"] += 1
            continue

        if _looks_like_natural_language_line(stripped):
            # Tolerate a few prose-like lines; only reject if excessive.
            totals["comment_prose_lines"] += 1
            totals["comment_prose_chars"] += len(stripped)
            continue

        totals["code_lines"] += 1

    _finalize_comment_block(block_stats, totals)

    # Only reject if the file is overwhelmingly explanation-heavy.
    if totals["max_block_lines"] >= 20 and totals["max_block_chars"] >= 800:
        raise SandboxError(
            "Sandbox file content contains a large explanation-heavy comment block. Keep comments concise and resend raw code only."
        )

    if (
        totals["comment_prose_lines"] >= totals["code_lines"] + 8
        and totals["comment_prose_chars"] >= 800
    ):
        raise SandboxError(
            "Sandbox file content looks explanation-heavy relative to the code. Remove the reasoning text and resend raw code only."
        )

    if (
        totals["code_lines"] == 0
        and totals["comment_prose_lines"] >= 8
        and totals["comment_prose_chars"] >= 400
    ):
        raise SandboxError(
            "Sandbox file content contains explanation text but no executable code. Resend the actual file content only."
        )
