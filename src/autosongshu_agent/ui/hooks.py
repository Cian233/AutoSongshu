"""
Frontend hooks for state management.

Provides React-like hooks for Python CLI/Web apps to interact with the new Store.
Inspired by claw-code's useAppState hook.
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar
from weakref import WeakSet

from ..core.state import Store, create_store, AppState, get_default_app_state

T = TypeVar("T")


class StateSubscription:
    """
    Manages subscriptions to store changes.

    Usage:
        subscription = StateSubscription(store)
        subscription.subscribe(lambda state: print(state))

        # Later...
        subscription.unsubscribe_all()
    """

    def __init__(self, store: Store):
        self._store = store
        self._unsubscribe: Callable | None = None
        self._listeners: WeakSet[Callable] = WeakSet()

    def subscribe(self, listener: Callable[[Any], None]) -> Callable[[], None]:
        """
        Subscribe to store changes.

        Returns unsubscribe function.
        """

        def wrapper():
            state = self._store.get_state()
            listener(state)

        self._listeners.add(listener)
        unsubscribe = self._store.subscribe(wrapper)

        return lambda: self._listeners.discard(listener)

    def unsubscribe_all(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()


def use_app_state(
    store: Store[AppState] | None = None,
    selector: Callable[[AppState], T] | None = None,
) -> tuple[T, Callable[[Callable[[AppState], AppState]], None]]:
    """
    Hook to access and update AppState.

    Similar to React's useState but for our Store.

    Args:
        store: Store instance (uses global if None)
        selector: Optional selector function to extract subset of state

    Returns:
        Tuple of (current_state, set_state_function)

    Example:
        # Get full state
        state, set_state = use_app_state(store)

        # Get subset
        model, set_state = use_app_state(store, lambda s: s.get('main_loop_model'))

        # Update state
        set_state(lambda s: {**s, 'main_loop_model': 'gpt-4'})
    """
    if store is None:
        store = create_store(get_default_app_state())

    current_state = store.get_state()

    if selector:
        selected = selector(current_state)
    else:
        selected = current_state

    def set_state(updater: Callable[[AppState], AppState]) -> None:
        store.set_state(updater)

    return selected, set_state


def use_selector(
    store: Store[AppState],
    selector: Callable[[AppState], T],
) -> T:
    """
    Hook to select a subset of state.

    More efficient than use_app_state when you only need a specific value.

    Args:
        store: Store instance
        selector: Function to extract subset of state

    Returns:
        Selected value

    Example:
        model = use_selector(store, lambda s: s.get('main_loop_model'))
    """
    state = store.get_state()
    return selector(state)


class StateBridge:
    """
    Bridge between Store and UI frameworks.

    Provides a clean API for UI components to interact with Store.
    """

    def __init__(self, store: Store[AppState] | None = None):
        self._store = store or create_store(get_default_app_state())
        self._subscriptions: dict[str, StateSubscription] = {}

    def get_store(self) -> Store[AppState]:
        """Get the underlying store."""
        return self._store

    def get_state(self) -> AppState:
        """Get current state."""
        return self._store.get_state()

    def update_state(self, updater: Callable[[AppState], AppState]) -> None:
        """Update state."""
        self._store.set_state(updater)

    def subscribe(
        self, key: str, listener: Callable[[AppState], None]
    ) -> Callable[[], None]:
        """
        Subscribe to state changes with a key.

        Args:
            key: Unique key for this subscription
            listener: Callback function

        Returns:
            Unsubscribe function
        """
        if key not in self._subscriptions:
            self._subscriptions[key] = StateSubscription(self._store)

        return self._subscriptions[key].subscribe(listener)

    def unsubscribe(self, key: str) -> None:
        """Unsubscribe by key."""
        if key in self._subscriptions:
            self._subscriptions[key].unsubscribe_all()
            del self._subscriptions[key]


# Global bridge instance
_global_bridge: StateBridge | None = None


def get_global_bridge() -> StateBridge:
    """Get global StateBridge instance."""
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = StateBridge()
    return _global_bridge


def init_global_bridge(store: Store[AppState]) -> StateBridge:
    """Initialize global bridge with a store."""
    global _global_bridge
    _global_bridge = StateBridge(store)
    return _global_bridge


__all__ = [
    "StateSubscription",
    "use_app_state",
    "use_selector",
    "StateBridge",
    "get_global_bridge",
    "init_global_bridge",
]
