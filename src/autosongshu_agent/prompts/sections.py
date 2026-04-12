"""
Prompt sections - Static/dynamic boundary and section registration.

Three-layer caching:
1. Global cache (static sections before boundary)
2. Session-memoized (dynamic sections computed once per session)
3. Volatile (recomputed every turn)

Inspired by claw-code's constants/systemPromptSections.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class SystemPromptSection:
    """
    A section of the system prompt.

    cache_break:
    - False: Compute once, cache until /clear or /compact
    - True: Recompute every turn (volatile, breaks prompt cache)
    """

    name: str
    compute: Callable[[], Any]
    cache_break: bool


def system_prompt_section(
    name: str,
    compute: Callable[[], Any],
) -> SystemPromptSection:
    """
    Create a memoized section - computed once per session.

    Use for dynamic content that's stable within a session:
    - User/project info
    - MCP instructions
    - Environment status
    """
    return SystemPromptSection(name=name, compute=compute, cache_break=False)


def DANGEROUS_uncached_section(
    name: str,
    compute: Callable[[], Any],
    reason: str,  # REQUIRED: explain why this needs to be volatile
) -> SystemPromptSection:
    """
    Create a volatile section - recomputed every turn.

    WARNING: This BREAKS prompt cache! Use sparingly.

    Only use for content that MUST change every turn:
    - Real-time counters
    - Turn-specific context
    - Volatile state

    The 'reason' parameter is mandatory - force documentation of why.
    """
    return SystemPromptSection(name=name, compute=compute, cache_break=True)
