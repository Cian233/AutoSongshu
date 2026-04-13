"""Web search and fetch tools.

Ported from claw-code's WebSearch and WebFetch tools, adapted for the
security assessment context (searching for CVE info, vulnerability
details, fetching external pages for analysis).
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import httpx
from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

# Default search result limit
_MAX_SEARCH_RESULTS = 8
# HTTP client timeout
_FETCH_TIMEOUT = 20.0
# Maximum content length to return
_MAX_CONTENT_CHARS = 30000


registry.create_group(
    "web-tools",
    description="Web 搜索和页面获取工具：搜索网络信息、获取外部页面内容。",
    risk_level=ToolRiskLevel.LOW,
)


def _html_to_text(html: str) -> str:
    """Rough HTML to text conversion for readability."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Convert common block elements to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


@registry.register(
    "web-tools",
    description="搜索网络并返回结果列表。适用于搜索漏洞信息、CVE 编号、安全公告等。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
    max_retries=2,
)
def web_search(
    runtime: PentestRuntime,
    query: str,
    max_results: int = 8,
) -> ToolResponse:
    """Search the web and return ranked results.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (1-20).
    """
    try:
        max_results = max(1, min(int(max_results), 20))
        search_url = runtime.config.model.web_search_base_url if hasattr(runtime.config.model, "web_search_base_url") else None

        if search_url:
            # Custom search endpoint
            resp = httpx.get(
                search_url,
                params={"q": query, "max": max_results},
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"results": []}
            results = data.get("results", data.get("data", []))
        else:
            # Default: DuckDuckGo HTML search
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AutoSongshu/1.0)"},
            )
            resp.raise_for_status()
            html = resp.text
            # Parse DuckDuckGo HTML results
            results = _parse_ddg_results(html)

        results = results[:max_results]
        return _tool_response({
            "ok": True,
            "query": query,
            "total_results": len(results),
            "results": results,
        })
    except Exception as exc:
        return _error_response(exc)


def _parse_ddg_results(html: str) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML search results."""
    results: list[dict[str, str]] = []
    # Extract result snippets from DDG HTML
    result_blocks = re.findall(
        r'<a rel="nofollow" class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a class="result__snippet"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )
    for url, title, snippet in result_blocks:
        # DDG redirects — extract actual URL
        actual_url = url
        if "uddg=" in url:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            actual_url = parsed.get("uddg", [url])[0]
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        snippet_clean = re.sub(r"<[^>]+>", "", snippet).strip()
        if title_clean and actual_url:
            results.append({
                "title": title_clean,
                "url": actual_url,
                "snippet": snippet_clean[:300],
            })
    return results


@registry.register(
    "web-tools",
    description="获取指定 URL 的页面内容并转换为可读文本。适用于获取安全公告、文档页面等。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
    max_retries=2,
)
def web_fetch(
    runtime: PentestRuntime,
    url: str,
    max_chars: int = 30000,
) -> ToolResponse:
    """Fetch a URL and return readable text content.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return from the page content.
    """
    try:
        max_chars = max(100, min(int(max_chars), 100000))
        # Auto-upgrade HTTP to HTTPS (except localhost)
        if url.startswith("http://") and not url.startswith("http://localhost"):
            url = "https://" + url[len("http://"):]

        resp = httpx.get(
            url,
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AutoSongshu/1.0)"},
        )
        resp.raise_for_status()

        # Ensure correct encoding for text responses
        if "charset" not in resp.headers.get("content-type", "").lower():
            resp.encoding = "utf-8"

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            text = _html_to_text(resp.text)
        elif "application/json" in content_type:
            try:
                data = resp.json()
                text = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                text = resp.text
        else:
            text = resp.text

        truncated = len(text) > max_chars
        text = text[:max_chars]

        return _tool_response({
            "ok": True,
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content_type": content_type,
            "content_length": len(resp.text),
            "truncated": truncated,
            "content": text,
        })
    except Exception as exc:
        return _error_response(exc)
