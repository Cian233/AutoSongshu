"""
Lazy Schema - Delay expensive construction until first access.

Inspired by claw-code's utils/lazySchema.ts (8 lines total).

Problem: Zod/Pydantic schema construction can be expensive.
Solution: Delay construction until first access, then cache.
"""

from __future__ import annotations

from typing import Callable, TypeVar, Generic

T = TypeVar("T")


class LazySchema(Generic[T]):
    """
    Lazy schema constructor.

    Delays expensive schema construction until first access.

    Usage:
        input_schema = lazy_schema(lambda: create_complex_schema())
        # Schema not constructed yet...

        schema = input_schema()  # Now constructed and cached
        schema = input_schema()  # Returns cached instance
    """

    __slots__ = ("_factory", "_cached")

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._cached: T | None = None

    def __call__(self) -> T:
        """Get the schema, constructing if needed."""
        if self._cached is None:
            self._cached = self._factory()
        return self._cached

    def reset(self) -> None:
        """Clear the cache (for testing)."""
        self._cached = None


def lazy_schema(factory: Callable[[], T]) -> LazySchema[T]:
    """
    Create a lazy schema wrapper.

    Args:
        factory: Function that constructs the schema

    Returns:
        LazySchema that delays construction until first access

    Example:
        >>> schema = lazy_schema(lambda: {"type": "object", "properties": {}})
        >>> # Schema not constructed yet
        >>> actual = schema()  # Now constructed
    """
    return LazySchema(factory)


__all__ = ["LazySchema", "lazy_schema"]
