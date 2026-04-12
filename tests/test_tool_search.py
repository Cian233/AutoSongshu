"""Tests for ToolSearch functionality."""

import pytest

from autosongshu_agent.tools.base import BuiltTool, ToolDef, build_tool
from autosongshu_agent.tools.tool_search import (
    ToolSearchConfig,
    ToolSearchResult,
    build_tool_search_result_message,
    calculate_deferred_token_cost,
    get_tool_search_config,
    is_deferred_tool,
    score_tool_match,
    search_tools_by_keyword,
    should_enable_tool_search,
)


def make_tool(
    name: str,
    description: str = "",
    search_hint: str = "",
    aliases: list[str] | None = None,
) -> BuiltTool:
    """Helper to create a tool for testing."""
    return build_tool(
        ToolDef(
            name=name,
            description=description,
            call=lambda x, ctx: x,
            search_hint=search_hint,
            aliases=aliases or [],
        )
    )


class TestIsDeferredTool:
    """Tests for is_deferred_tool()."""

    def test_tool_search_itself_never_deferred(self):
        tool = make_tool("tool_search", search_hint="search for tools")
        assert (
            is_deferred_tool(tool, always_load_names=frozenset(["tool_search"]))
            is False
        )

    def test_mcp_tools_are_deferred(self):
        tool = make_tool("mcp_slack_send", search_hint="")
        assert is_deferred_tool(tool, is_mcp_tool=True) is True

    def test_tool_with_search_hint_is_deferred(self):
        tool = make_tool("my_tool", search_hint="does something useful")
        assert is_deferred_tool(tool) is True

    def test_tool_without_hint_is_not_deferred(self):
        tool = make_tool("my_tool", search_hint="")
        assert is_deferred_tool(tool) is False

    def test_disabled_tool_search(self):
        tool = make_tool("mcp_tool", search_hint="")
        assert (
            is_deferred_tool(tool, enable_tool_search=False, is_mcp_tool=True) is False
        )


class TestScoreToolMatch:
    """Tests for score_tool_match()."""

    def test_exact_name_match(self):
        tool = make_tool("read_file", description="Read a file")
        score = score_tool_match(tool, {"read", "file"})
        assert score >= 10  # At least partial match

    def test_exact_name_match_higher_for_mcp(self):
        tool = make_tool("mcp_tool", description="MCP tool")
        score_mcp = score_tool_match(tool, {"mcp", "tool"}, is_mcp_tool=True)
        score_regular = score_tool_match(tool, {"mcp", "tool"}, is_mcp_tool=False)
        assert score_mcp > score_regular

    def test_search_hint_match(self):
        tool = make_tool(
            "grep", description="Search", search_hint="search files by pattern"
        )
        score = score_tool_match(tool, {"pattern"})
        assert score >= 4  # search_hint match

    def test_description_match(self):
        tool = make_tool("tool", description="This tool helps with file operations")
        score = score_tool_match(tool, {"operations"})
        assert score >= 2  # description match

    def test_no_match(self):
        tool = make_tool("tool", description="Does something", search_hint="hint")
        score = score_tool_match(tool, {"xyz123nonexistent"})
        assert score == 0


class TestSearchToolsByKeyword:
    """Tests for search_tools_by_keyword()."""

    def test_select_mode(self):
        tools = [
            make_tool("read_file"),
            make_tool("write_file"),
            make_tool("list_dir"),
        ]
        result = search_tools_by_keyword("select:read_file,write_file", tools)
        assert result == ["read_file", "write_file"]

    def test_select_mode_case_insensitive(self):
        tools = [make_tool("ReadFile")]
        result = search_tools_by_keyword("select:readfile", tools)
        assert result == ["ReadFile"]

    def test_keyword_search(self):
        tools = [
            make_tool("file_read", description="Read a file"),
            make_tool("file_write", description="Write a file"),
            make_tool("network_fetch", description="Fetch from network"),
        ]
        result = search_tools_by_keyword("file", tools, max_results=2)
        assert len(result) == 2
        assert "file_read" in result
        assert "file_write" in result

    def test_keyword_search_respects_max_results(self):
        tools = [make_tool(f"tool_{i}", search_hint="test") for i in range(10)]
        result = search_tools_by_keyword("test", tools, max_results=3)
        assert len(result) == 3

    def test_empty_query_returns_empty(self):
        tools = [make_tool("tool")]
        result = search_tools_by_keyword("", tools)
        assert result == []

    def test_no_matches_returns_empty(self):
        tools = [make_tool("tool_a"), make_tool("tool_b")]
        result = search_tools_by_keyword("xyz123nonexistent", tools)
        assert result == []


class TestToolSearchConfig:
    """Tests for ToolSearchConfig and get_tool_search_config()."""

    def test_disabled_mode(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TOOL_SEARCH", "false")
        config = get_tool_search_config()
        assert config.enabled is False
        assert config.mode == "standard"

    def test_tst_mode_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_TOOL_SEARCH", raising=False)
        config = get_tool_search_config()
        assert config.enabled is True
        assert config.mode == "tst"

    def test_tst_auto_mode(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TOOL_SEARCH", "auto:15")
        config = get_tool_search_config()
        assert config.enabled is True
        assert config.mode == "tst-auto"
        assert config.auto_threshold_percent == 15.0


class TestCalculateDeferredTokenCost:
    """Tests for calculate_deferred_token_cost()."""

    def test_empty_list(self):
        assert calculate_deferred_token_cost([]) == 0

    def test_single_tool(self):
        tool = make_tool("test_tool", description="A test tool")
        cost = calculate_deferred_token_cost([tool])
        assert cost > 0

    def test_larger_tools_cost_more(self):
        small_tool = make_tool("a", description="x")
        large_tool = make_tool(
            "a_very_long_tool_name", description="A very long description for testing"
        )
        small_cost = calculate_deferred_token_cost([small_tool])
        large_cost = calculate_deferred_token_cost([large_tool])
        assert large_cost > small_cost


class TestShouldEnableToolSearch:
    """Tests for should_enable_tool_search()."""

    def test_no_deferred_tools(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TOOL_SEARCH", "auto:10")
        result = should_enable_tool_search([], context_window=200_000)
        assert result is False  # No tools to defer

    def test_below_threshold(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TOOL_SEARCH", "auto:10")
        tools = [make_tool("a" * 100, description="x" * 100) for _ in range(5)]
        result = should_enable_tool_search(tools, context_window=1_000_000)
        # Token cost is small relative to huge context window
        assert result is False

    def test_standard_mode_always_false(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TOOL_SEARCH", "false")
        tools = [make_tool("test_tool")]
        result = should_enable_tool_search(tools)
        assert result is False


class TestBuildToolSearchResultMessage:
    """Tests for build_tool_search_result_message()."""

    def test_no_matches(self):
        result = ToolSearchResult(
            matches=[],
            query="xyz",
            total_deferred=10,
            mode="keyword",
        )
        msg = build_tool_search_result_message(result)
        assert "No tools found" in msg

    def test_with_matches(self):
        result = ToolSearchResult(
            matches=["read_file", "write_file"],
            query="file",
            total_deferred=20,
            mode="keyword",
        )
        msg = build_tool_search_result_message(result)
        assert "read_file" in msg
        assert "write_file" in msg
        assert "20" in msg

    def test_select_mode(self):
        result = ToolSearchResult(
            matches=["exact_tool"],
            query="select:exact_tool",
            total_deferred=5,
            mode="select",
        )
        msg = build_tool_search_result_message(result)
        assert "Precise selection" in msg
