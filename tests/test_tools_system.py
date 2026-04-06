"""
Tests for tools system - Phase 2.
"""

import pytest
from autosongshu_agent.tools import (
    Tool,
    build_tool,
    ToolDef,
    PermissionResult,
    ToolRegistry,
    get_all_base_tools,
    partition_tool_calls,
    ToolExecutionResult,
    ToolBatchResult,
)


class TestBuildTool:
    """Tests for build_tool() pattern."""

    def test_build_tool_basic(self):
        """Test basic tool building."""

        async def my_call(input_data, context):
            return {"result": "ok"}

        tool_def = ToolDef(
            name="my_tool",
            description="A test tool",
            call=my_call,
        )

        tool = build_tool(tool_def)

        assert tool.name == "my_tool"
        assert tool.description == "A test tool"
        assert tool.user_facing_name({}) == "my_tool"

    def test_build_tool_default_fail_closed(self):
        """Test that build_tool provides fail-closed defaults."""

        async def my_call(input_data, context):
            return {}

        tool = build_tool(ToolDef(name="test", description="test", call=my_call))

        # Default: NOT concurrency safe
        assert tool.is_concurrency_safe({}) is False

        # Default: NOT read-only (assumes writes)
        assert tool.is_read_only({}) is False

        # Default: IS enabled
        assert tool.is_enabled() is True

        # Default: permission check returns allow
        result = tool.check_permissions({})
        assert result.behavior == "allow"

    def test_build_tool_override_defaults(self):
        """Test that tool can override defaults."""

        async def my_call(input_data, context):
            return {}

        tool = build_tool(
            ToolDef(
                name="safe_tool",
                description="A safe tool",
                call=my_call,
                is_concurrency_safe=lambda _: True,
                is_read_only=lambda _: True,
            )
        )

        assert tool.is_concurrency_safe({}) is True
        assert tool.is_read_only({}) is True


class TestPermissionResult:
    """Tests for PermissionResult."""

    def test_allow(self):
        """Test allow result."""
        result = PermissionResult.allow({"arg": "value"})

        assert result.behavior == "allow"
        assert result.updated_input == {"arg": "value"}

    def test_ask(self):
        """Test ask result."""
        result = PermissionResult.ask("Need approval")

        assert result.behavior == "ask"
        assert result.error == "Need approval"

    def test_deny(self):
        """Test deny result."""
        result = PermissionResult.deny("Blocked")

        assert result.behavior == "deny"
        assert result.error == "Blocked"


class TestToolExecutionResult:
    """Tests for ToolExecutionResult."""

    def test_success_result(self):
        """Test successful execution result."""
        result = ToolExecutionResult.success_result(
            tool_name="browser_navigate",
            output={"status": "ok"},
            arguments={"url": "https://example.com"},
        )

        assert result.success is True
        assert result.handled is True
        assert result.output == {"status": "ok"}

    def test_error_result(self):
        """Test error execution result."""
        result = ToolExecutionResult.error_result(
            tool_name="browser_navigate",
            error="Timeout",
            arguments={"url": "https://example.com"},
        )

        assert result.success is False
        assert result.handled is True
        assert result.error == "Timeout"

    def test_permission_denied(self):
        """Test permission denied result."""
        result = ToolExecutionResult.permission_denied(
            tool_name="sandbox_run_python",
            arguments={"code": "print('hello')"},
            reason="High risk tool requires approval",
        )

        assert result.success is False
        assert result.handled is False  # NOT executed
        assert "approval" in result.error

    def test_not_found(self):
        """Test tool not found result."""
        result = ToolExecutionResult.not_found(
            tool_name="nonexistent_tool",
            arguments={},
        )

        assert result.success is False
        assert result.handled is False
        assert "not found" in result.error


class TestToolBatchResult:
    """Tests for ToolBatchResult."""

    def test_batch_result_aggregation(self):
        """Test batch result aggregation."""
        results = [
            ToolExecutionResult.success_result("tool1", {}, {}),
            ToolExecutionResult.success_result("tool2", {}, {}),
            ToolExecutionResult.error_result("tool3", "failed", {}),
            ToolExecutionResult.permission_denied("tool4", {}, "denied"),
        ]

        batch = ToolBatchResult(results=results)

        assert batch.all_success is False
        assert batch.any_handled is True
        assert batch.success_count == 2
        assert batch.failure_count == 1
        assert batch.skipped_count == 1


class TestPartitionToolCalls:
    """Tests for partition_tool_calls()."""

    def test_partition_mixed_tools(self):
        """Test partitioning a mix of safe and unsafe tools."""

        async def safe_call(input_data, context):
            return {}

        async def unsafe_call(input_data, context):
            return {}

        safe_tool = build_tool(
            ToolDef(
                name="safe_tool",
                description="Safe",
                call=safe_call,
                is_concurrency_safe=lambda _: True,
            )
        )

        unsafe_tool = build_tool(
            ToolDef(
                name="unsafe_tool",
                description="Unsafe",
                call=unsafe_call,
                is_concurrency_safe=lambda _: False,
            )
        )

        tool_calls = [
            {"name": "safe_tool", "input": {}},
            {"name": "safe_tool", "input": {"arg": "value"}},
            {"name": "unsafe_tool", "input": {}},
            {"name": "safe_tool", "input": {}},
        ]

        batches = partition_tool_calls(tool_calls, [safe_tool, unsafe_tool])

        # First two safe tools should be in one batch
        assert len(batches) == 3
        assert batches[0].is_concurrency_safe is True
        assert len(batches[0].blocks) == 2

        # Unsafe tool in its own batch
        assert batches[1].is_concurrency_safe is False
        assert len(batches[1].blocks) == 1

        # Last safe tool in new batch (after unsafe)
        assert batches[2].is_concurrency_safe is True
        assert len(batches[2].blocks) == 1


class TestToolRegistry:
    """Tests for tool registry."""

    def test_registry_operations(self):
        """Test basic registry operations."""

        async def my_call(input_data, context):
            return {}

        tool = build_tool(
            ToolDef(
                name="test_tool",
                description="Test",
                call=my_call,
            )
        )

        registry = ToolRegistry(_tools=[tool])

        assert registry.get_tool("test_tool") is not None
        assert registry.get_tool("TEST_TOOL") is not None  # Case-insensitive
        assert registry.get_tool("nonexistent") is None
        assert "test_tool" in registry.get_tool_names()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
