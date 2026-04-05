from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from autosongshu_agent.commands import (
    CommandContext,
    CommandResult,
    CommandRegistry,
    SlashCommand,
    HelpCommand,
    StatsCommand,
    ClearCommand,
    StatusCommand,
    InterruptCommand,
    ModeCommand,
    CompactCommand,
    create_default_registry,
)


class TestCommandContext:
    def test_context_creation(self) -> None:
        session = MagicMock()
        manager = MagicMock()
        ctx = CommandContext(
            session_id="test-session",
            session=session,
            manager=manager,
            args="some args",
            content="/help some args",
        )
        assert ctx.session_id == "test-session"
        assert ctx.args == "some args"


class TestCommandResult:
    def test_simple_result(self) -> None:
        result = CommandResult(response_text="Hello")
        assert result.response_text == "Hello"
        assert not result.requires_async

    def test_async_result(self) -> None:
        handler = MagicMock()
        result = CommandResult(
            response_text="Processing...",
            requires_async=True,
            async_handler=handler,
        )
        assert result.requires_async
        assert result.async_handler is not None


class MockCommand(SlashCommand):
    name = "/mock"
    description = "Mock command for testing"
    aliases = ["/m"]

    def execute(self, ctx: CommandContext) -> CommandResult:
        return CommandResult(response_text=f"Mock executed with args: {ctx.args}")


class CommandRegistryTests(unittest.TestCase):
    def test_register_and_get_command(self) -> None:
        registry = CommandRegistry()
        cmd = MockCommand()
        registry.register(cmd)
        self.assertEqual(registry.get_command("/mock"), cmd)

    def test_get_command_by_alias(self) -> None:
        registry = CommandRegistry()
        cmd = MockCommand()
        registry.register(cmd)
        self.assertEqual(registry.get_command("/m"), cmd)

    def test_get_nonexistent_command(self) -> None:
        registry = CommandRegistry()
        self.assertIsNone(registry.get_command("/nonexistent"))

    def test_list_commands(self) -> None:
        registry = CommandRegistry()
        cmd = MockCommand()
        registry.register(cmd)
        commands = registry.list_commands()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0], cmd)

    def test_is_command(self) -> None:
        registry = CommandRegistry()
        cmd = MockCommand()
        registry.register(cmd)
        self.assertTrue(registry.is_command("/mock"))
        self.assertTrue(registry.is_command("/m"))
        self.assertTrue(registry.is_command("  /mock  "))
        self.assertFalse(registry.is_command("hello world"))

    def test_parse_command(self) -> None:
        registry = CommandRegistry()
        result = registry.parse_command("/help me")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "/help")
        self.assertEqual(result[1], "me")

    def test_parse_command_no_args(self) -> None:
        registry = CommandRegistry()
        result = registry.parse_command("/help")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "/help")
        self.assertEqual(result[1], "")

    def test_parse_non_command(self) -> None:
        registry = CommandRegistry()
        result = registry.parse_command("hello world")
        self.assertIsNone(result)


class HelpCommandTests(unittest.TestCase):
    def test_help_lists_commands(self) -> None:
        registry = CommandRegistry()
        registry.register(MockCommand())
        help_cmd = HelpCommand(registry)
        ctx = CommandContext(
            session_id="test", session=MagicMock(), manager=MagicMock()
        )
        result = help_cmd.execute(ctx)
        self.assertIn("可用命令", result.response_text)

    def test_help_for_specific_command(self) -> None:
        registry = CommandRegistry()
        registry.register(MockCommand())
        help_cmd = HelpCommand(registry)
        ctx = CommandContext(
            session_id="test", session=MagicMock(), manager=MagicMock(), args="/mock"
        )
        result = help_cmd.execute(ctx)
        self.assertIn("/mock", result.response_text)


class StatsCommandTests(unittest.TestCase):
    def test_stats_no_tracker(self) -> None:
        session = MagicMock()
        session.conversation = None
        cmd = StatsCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("未找到", result.response_text)

    def test_stats_with_tracker(self) -> None:
        session = MagicMock()
        conversation = MagicMock()
        tracker = MagicMock()
        tracker.summary_dict.return_value = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "event_count": 3,
        }
        conversation.cost_tracker = tracker
        session.conversation = conversation
        cmd = StatsCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("100", result.response_text)
        self.assertIn("50", result.response_text)


class ClearCommandTests(unittest.TestCase):
    def test_clear_clears_messages(self) -> None:
        session = MagicMock()
        session.messages = [MagicMock(), MagicMock()]
        session.memory = MagicMock()
        session.conversation = None
        cmd = ClearCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertEqual(len(session.messages), 0)
        self.assertIn("清空", result.response_text)


class StatusCommandTests(unittest.TestCase):
    def test_status_shows_session_info(self) -> None:
        session = MagicMock()
        session.session_id = "test-123"
        session.status = "idle"
        session.messages = [MagicMock(), MagicMock()]
        session.mode = "auto"
        session.start_url = "http://example.com"
        session.allowed_hosts = ["example.com"]
        session.artifact_dir = "/artifacts/test"
        session.knowledge_base_ids = ["kb-1"]
        cmd = StatusCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("test-123", result.response_text)
        self.assertIn("idle", result.response_text)


class InterruptCommandTests(unittest.TestCase):
    def test_interrupt_no_running_task(self) -> None:
        session = MagicMock()
        session.status = "idle"
        cmd = InterruptCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("没有", result.response_text)

    def test_interrupt_running_task(self) -> None:
        session = MagicMock()
        session.status = "running"
        cmd = InterruptCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("中断", result.response_text)


class ModeCommandTests(unittest.TestCase):
    def test_mode_show_current(self) -> None:
        session = MagicMock()
        session.mode = "auto"
        cmd = ModeCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertIn("auto", result.response_text)

    def test_mode_switch(self) -> None:
        session = MagicMock()
        session.mode = "auto"
        cmd = ModeCommand()
        ctx = CommandContext(
            session_id="test", session=session, manager=MagicMock(), args="semi-auto"
        )
        result = cmd.execute(ctx)
        self.assertEqual(session.mode, "semi-auto")

    def test_mode_invalid(self) -> None:
        session = MagicMock()
        session.mode = "auto"
        cmd = ModeCommand()
        ctx = CommandContext(
            session_id="test", session=session, manager=MagicMock(), args="invalid"
        )
        result = cmd.execute(ctx)
        self.assertIn("无效", result.response_text)


class CompactCommandTests(unittest.TestCase):
    def test_compact_requires_async(self) -> None:
        session = MagicMock()
        cmd = CompactCommand()
        ctx = CommandContext(session_id="test", session=session, manager=MagicMock())
        result = cmd.execute(ctx)
        self.assertTrue(result.requires_async)
        self.assertIsNotNone(result.async_handler)


class CreateDefaultRegistryTests(unittest.TestCase):
    def test_default_registry_has_all_commands(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.get_command("/help"))
        self.assertIsNotNone(registry.get_command("/stats"))
        self.assertIsNotNone(registry.get_command("/clear"))
        self.assertIsNotNone(registry.get_command("/status"))
        self.assertIsNotNone(registry.get_command("/interrupt"))
        self.assertIsNotNone(registry.get_command("/mode"))
        self.assertIsNotNone(registry.get_command("/compact"))

    def test_default_registry_aliases(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.get_command("?"))
        self.assertIsNotNone(registry.get_command("/usage"))
        self.assertIsNotNone(registry.get_command("/reset"))
        self.assertIsNotNone(registry.get_command("/stop"))


if __name__ == "__main__":
    unittest.main()
