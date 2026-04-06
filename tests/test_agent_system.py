"""
Tests for Agent system - Phase 4.
"""

import pytest
from autosongshu_agent.agent.definition import (
    BuiltInAgentDefinition,
    CustomAgentDefinition,
    get_agent_model,
)
from autosongshu_agent.agent.built_in import (
    EXPLORE_AGENT,
    PLAN_AGENT,
    VERIFICATION_AGENT,
    GENERAL_PURPOSE_AGENT,
    get_builtin_agents,
    ALL_AGENT_DISALLOWED_TOOLS,
)
from autosongshu_agent.agent.fork import (
    build_forked_messages,
    is_in_fork_child,
    FORK_BOILERPLATE_TAG,
)


class TestAgentDefinition:
    """Tests for AgentDefinition types."""

    def test_builtin_agent_definition(self):
        """Test BuiltInAgentDefinition creation."""
        agent = BuiltInAgentDefinition(
            agent_type="test_agent",
            when_to_use="Test purposes",
        )

        assert agent.agent_type == "test_agent"
        assert agent.source == "built-in"
        assert agent.model == "inherit"

    def test_custom_agent_definition(self):
        """Test CustomAgentDefinition creation."""
        agent = CustomAgentDefinition(
            agent_type="custom_agent",
            when_to_use="Custom agent",
            source="user",
            filename="custom.md",
        )

        assert agent.agent_type == "custom_agent"
        assert agent.source == "user"
        assert agent.filename == "custom.md"

    def test_get_agent_model(self):
        """Test model resolution."""
        # Override takes precedence
        assert get_agent_model("gpt-4", "gpt-3.5", "claude-3") == "claude-3"

        # Agent's own model (not inherit)
        assert get_agent_model("gpt-4", "gpt-3.5", None) == "gpt-4"

        # Inherit from parent
        assert get_agent_model("inherit", "gpt-3.5", None) == "gpt-3.5"
        assert get_agent_model(None, "gpt-3.5", None) == "gpt-3.5"


class TestBuiltInAgents:
    """Tests for built-in agents."""

    def test_get_builtin_agents(self):
        """Test that all built-in agents are returned."""
        agents = get_builtin_agents()

        assert len(agents) == 4
        agent_types = [a.agent_type for a in agents]
        assert "Explore" in agent_types
        assert "Plan" in agent_types
        assert "Verification" in agent_types
        assert "general-purpose" in agent_types

    def test_explore_agent_read_only(self):
        """Test that Explore agent is read-only."""
        assert EXPLORE_AGENT.agent_type == "Explore"
        assert EXPLORE_AGENT.omit_claude_md is True
        assert "file_edit" in EXPLORE_AGENT.disallowed_tools
        assert "file_write" in EXPLORE_AGENT.disallowed_tools

    def test_plan_agent_read_only(self):
        """Test that Plan agent is read-only."""
        assert PLAN_AGENT.agent_type == "Plan"
        assert PLAN_AGENT.omit_claude_md is True
        assert "file_edit" in PLAN_AGENT.disallowed_tools

    def test_verification_agent_has_critical_reminder(self):
        """Test that Verification agent has critical reminder."""
        assert VERIFICATION_AGENT.agent_type == "Verification"
        assert VERIFICATION_AGENT.critical_reminder is not None
        assert "VERIFICATION-ONLY" in VERIFICATION_AGENT.critical_reminder

    def test_general_purpose_agent_has_all_tools(self):
        """Test that general-purpose agent has access to all tools."""
        assert GENERAL_PURPOSE_AGENT.agent_type == "general-purpose"
        assert GENERAL_PURPOSE_AGENT.tools == ["*"]

    def test_all_agents_disallow_nested_agents(self):
        """Test that all built-in agents disallow nested agents by default."""
        for agent in get_builtin_agents():
            # Check that agent tool is disallowed (except general-purpose which has all tools)
            if agent.agent_type != "general-purpose":
                assert "agent" in agent.disallowed_tools


class TestForkSubagent:
    """Tests for Fork Subagent mechanism."""

    def test_build_forked_messages(self):
        """Test building fork messages."""
        assistant_message = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll help you with that."},
                {"type": "tool_use", "id": "tool_1", "name": "read", "input": {}},
                {"type": "tool_use", "id": "tool_2", "name": "glob", "input": {}},
            ],
        }

        messages = build_forked_messages("Analyze the codebase", assistant_message)

        # Should return 2 messages
        assert len(messages) == 2

        # First message is assistant (with new UUID)
        assert messages[0]["role"] == "assistant"

        # Second message is user with tool results and directive
        assert messages[1]["role"] == "user"
        content = messages[1]["content"]
        assert len(content) == 3  # 2 tool results + 1 directive

        # Last block should contain fork tag
        directive_block = content[-1]
        assert directive_block["type"] == "text"
        assert FORK_BOILERPLATE_TAG in directive_block["text"]

    def test_is_in_fork_child(self):
        """Test detecting fork child context."""
        # Not a fork child
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        assert is_in_fork_child(messages) is False

        # Is a fork child
        messages_with_fork = [
            {
                "role": "user",
                "content": f"<{FORK_BOILERPLATE_TAG}>Task here</{FORK_BOILERPLATE_TAG}>",
            },
        ]
        assert is_in_fork_child(messages_with_fork) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
