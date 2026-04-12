"""
Section cache - Memoization for prompt sections.

Inspired by claw-code's systemPromptSection cache.
"""

from __future__ import annotations

from typing import Any

# Global cache for sections
_section_cache: dict[str, str] = {}


def get_section_cache() -> dict[str, str]:
    """Get the global section cache."""
    return _section_cache


def clear_section_cache() -> None:
    """Clear all cached sections (call on /clear or /compact)."""
    global _section_cache
    _section_cache = {}


async def resolve_sections(sections: list[Any]) -> list[str]:
    """
    Resolve all sections, using cache for memoized ones.

    For each section:
    - If cache_break=False and in cache: return cached value
    - Otherwise: compute, cache (if not cache_break), return
    """
    from .sections import SystemPromptSection

    cache = get_section_cache()
    results: list[str] = []

    for section in sections:
        if isinstance(section, str):
            # Plain string, pass through
            results.append(section)
            continue

        if not isinstance(section, SystemPromptSection):
            # Unknown type, convert to string
            results.append(str(section))
            continue

        # Check cache
        if not section.cache_break and section.name in cache:
            results.append(cache[section.name])
            continue

        # Compute
        try:
            content = section.compute()
            if hasattr(content, "__await__"):
                content = await content
            content_str = str(content)
        except Exception as e:
            content_str = f"[Error computing section {section.name}: {e}]"

        # Cache if not volatile
        if not section.cache_break:
            cache[section.name] = content_str

        results.append(content_str)

    return results


def set_section_cache_entry(name: str, value: str) -> None:
    """Set a cache entry directly."""
    _section_cache[name] = value


def get_cached_section(name: str) -> str | None:
    """Get a cached section by name."""
    return _section_cache.get(name)
