"""
Tests for core infrastructure - Phase 1.

Tests the three-layer state architecture:
1. Session-level global state (bootstrap)
2. AppState Store
3. ToolUseContext
"""

import pytest
from autosongshu_agent.core import (
    Store,
    create_store,
    SessionState,
    get_session_id,
    set_session_id,
    init_session,
    get_cwd,
    set_cwd,
    get_total_cost,
    add_to_total_cost,
    reset_state,
    ToolUseContext,
    create_subagent_context,
    AbortController,
    FileStateCache,
    AppState,
    get_default_app_state,
    ToolPermissionContext,
    ToolRiskLevel,
)


class TestStore:
    """Tests for the 35-line minimalist Store."""

    def test_create_store(self):
        """Test store creation."""
        store = create_store({"count": 0})
        assert store.get_state() == {"count": 0}

    def test_set_state(self):
        """Test state updates."""
        store = create_store({"count": 0})
        store.set_state(lambda s: {"count": s["count"] + 1})
        assert store.get_state() == {"count": 1}

    def test_object_is_equality_check(self):
        """Test that identical objects don't trigger updates."""
        store = create_store({"count": 0})
        call_count = [0]

        def on_change(new, old):
            call_count[0] += 1

        store_with_callback = create_store({"count": 0}, on_change)
        store_with_callback.set_state(lambda s: s)  # Same object
        assert call_count[0] == 0  # Should not call on_change

    def test_subscribe(self):
        """Test subscription to state changes."""
        store = create_store({"count": 0})
        notifications = []

        def listener():
            notifications.append(store.get_state())

        unsubscribe = store.subscribe(listener)
        store.set_state(lambda s: {"count": 1})

        assert len(notifications) == 1
        assert notifications[0] == {"count": 1}

        unsubscribe()
        store.set_state(lambda s: {"count": 2})
        assert len(notifications) == 1  # No new notification

    def test_on_change_callback(self):
        """Test onChange callback."""
        changes = []

        def on_change(new_state, old_state):
            changes.append((new_state, old_state))

        store = create_store({"count": 0}, on_change)
        store.set_state(lambda s: {"count": 1})

        assert len(changes) == 1
        assert changes[0] == ({"count": 1}, {"count": 0})


class TestSessionState:
    """Tests for session-level global state."""

    def setup_method(self):
        """Reset state before each test."""
        reset_state()

    def test_init_session(self):
        """Test session initialization."""
        session_id = init_session("/tmp/test")
        assert session_id.startswith("session-")
        assert get_cwd() == "/tmp/test"

    def test_session_id(self):
        """Test session ID management."""
        set_session_id("test-session-123")
        assert get_session_id() == "test-session-123"

    def test_cost_tracking(self):
        """Test cost tracking."""
        add_to_total_cost(0.01, "gpt-4", {"input_tokens": 100, "output_tokens": 50})
        assert get_total_cost() == 0.01

        add_to_total_cost(0.02)
        assert get_total_cost() == 0.03


class TestToolUseContext:
    """Tests for ToolUseContext and agent isolation."""

    def test_create_context(self):
        """Test context creation."""
        ctx = ToolUseContext()
        assert ctx.agent_id.startswith("agent-")
        assert isinstance(ctx.abort_controller, AbortController)
        assert isinstance(ctx.read_file_state, FileStateCache)

    def test_create_subagent_context_isolation(self):
        """Test that subagent context is properly isolated."""
        parent_ctx = ToolUseContext(
            agent_id="parent-agent",
            agent_type="coordinator",
        )
        parent_ctx.read_file_state.set("file1", "content1")

        child_ctx = create_subagent_context(parent_ctx)

        # Child should have different agent_id
        assert child_ctx.agent_id != parent_ctx.agent_id

        # Child should have cloned file state
        assert child_ctx.read_file_state.get("file1") == "content1"
        child_ctx.read_file_state.set("file2", "content2")
        assert parent_ctx.read_file_state.get("file2") is None  # Parent not affected

    def test_abort_controller_propagation(self):
        """Test that abort can be shared via share_abort_controller."""
        parent_ctx = ToolUseContext()

        # Create child context with shared abort controller
        child_ctx = create_subagent_context(
            parent_ctx, {"share_abort_controller": True}
        )

        # Abort parent
        parent_ctx.abort_controller.abort()

        # Child should also be aborted (shared controller)
        assert child_ctx.abort_controller.is_aborted

    def test_abort_controller_isolation(self):
        """Test that child has independent abort controller by default."""
        parent_ctx = ToolUseContext()

        # Create child context (default: independent controller)
        child_ctx = create_subagent_context(parent_ctx)

        # Abort parent
        parent_ctx.abort_controller.abort()

        # Child should NOT be aborted (independent controller)
        assert not child_ctx.abort_controller.is_aborted


class TestAbortController:
    """Tests for AbortController."""

    def test_abort(self):
        """Test abort signaling."""
        controller = AbortController()
        assert not controller.is_aborted

        controller.abort()
        assert controller.is_aborted


class TestFileStateCache:
    """Tests for FileStateCache."""

    def test_cache_operations(self):
        """Test basic cache operations."""
        cache = FileStateCache(_max_size=2)

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        cache.set("key2", "value2")
        assert cache.get("key2") == "value2"

        # Should evict oldest when over max_size
        cache.set("key3", "value3")
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key3") == "value3"

    def test_cache_copy(self):
        """Test cache copying."""
        cache = FileStateCache()
        cache.set("key1", "value1")

        cache_copy = cache.copy()
        cache_copy.set("key2", "value2")

        assert cache.get("key2") is None
        assert cache_copy.get("key2") == "value2"


class TestAppState:
    """Tests for AppState."""

    def test_default_app_state(self):
        """Test default AppState creation."""
        state = get_default_app_state()

        assert isinstance(state, AppState)
        assert state.session_id == ""
        assert state.verbose is False
        assert isinstance(state.tool_permission_context, ToolPermissionContext)

    def test_app_state_modification(self):
        """Test AppState modification through Store."""
        store = create_store(get_default_app_state())

        # Modify model
        store.set_state(
            lambda s: AppState(**{**s.__dict__, "main_loop_model": "gpt-4"})
        )

        assert store.get_state().main_loop_model == "gpt-4"


class TestPermissions:
    """Tests for permission system."""

    def test_tool_permission_context(self):
        """Test ToolPermissionContext."""
        ctx = ToolPermissionContext.from_iterables(
            deny_names=["dangerous_tool"],
            require_approval_names=["sandbox_run_python"],
        )

        assert ctx.blocks("dangerous_tool")
        assert not ctx.blocks("safe_tool")

        assert ctx.requires_approval("sandbox_run_python")
        assert not ctx.requires_approval("browser_navigate")

    def test_risk_level_based_approval(self):
        """Test approval based on risk level."""
        ctx = ToolPermissionContext.from_iterables(
            require_approval_risk_levels=[ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL],
        )

        assert ctx.requires_approval("some_tool", ToolRiskLevel.HIGH)
        assert ctx.requires_approval("some_tool", ToolRiskLevel.CRITICAL)
        assert not ctx.requires_approval("some_tool", ToolRiskLevel.LOW)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
