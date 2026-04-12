"""
Dynamic boundary marker for prompt caching.

Everything BEFORE this boundary is static (can use global cache).
Everything AFTER is dynamic (session-memoized or volatile).

Inspired by claw-code's constants/prompts.ts:105-115
"""

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "<!-- SYSTEM_PROMPT_DYNAMIC_BOUNDARY -->"

__all__ = ["SYSTEM_PROMPT_DYNAMIC_BOUNDARY"]
