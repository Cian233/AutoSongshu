"""
35-line minimalist Store - bridges React and non-React worlds.

Inspired by claw-code's state/store.ts:
- Zero dependencies
- Object.is equality check (matches React behavior)
- onChange callback for centralized side effects
- subscribe returns unsubscribe function (matches useSyncExternalStore contract)
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

T = TypeVar("T")
Listener = Callable[[], None]
OnChange = Callable[[T, T], None]


class Store(Generic[T]):
    """
    Minimalist reactive store with 3 methods:
    - get_state(): read current state
    - set_state(updater): functionally update state
    - subscribe(listener): listen for changes, returns unsubscribe
    """

    __slots__ = ("_state", "_listeners", "_on_change")

    def __init__(self, initial_state: T, on_change: OnChange[T] | None = None):
        self._state: T = initial_state
        self._listeners: set[Listener] = set()
        self._on_change: OnChange[T] | None = on_change

    def get_state(self) -> T:
        """Get current state."""
        return self._state

    def set_state(self, updater: Callable[[T], T]) -> None:
        """
        Update state with an updater function.
        Uses Object.is equality check to avoid unnecessary updates.
        """
        prev = self._state
        next_state = updater(prev)
        # Object.is equality check - matches React behavior
        if next_state is prev:
            return
        self._state = next_state
        # Call onChange callback first (for centralized side effects)
        if self._on_change:
            self._on_change(next_state, prev)
        # Notify all listeners
        for listener in self._listeners:
            listener()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """
        Subscribe to state changes.
        Returns unsubscribe function - matches useSyncExternalStore contract.
        """
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)


def create_store(initial_state: T, on_change: OnChange[T] | None = None) -> Store[T]:
    """Factory function to create a Store."""
    return Store(initial_state, on_change)
