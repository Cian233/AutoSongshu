from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CommandContext:
    session_id: str
    session: Any
    manager: Any
    args: str = ""
    content: str = ""


@dataclass
class CommandResult:
    response_text: str
    requires_async: bool = False
    async_handler: Callable[[str, str], None] | None = None
    assistant_status: str = "completed"
    updated_session: dict[str, Any] | None = None


class SlashCommand(ABC):
    name: str = ""
    description: str = ""
    aliases: list[str] = []
    usage: str = ""

    @abstractmethod
    def execute(self, ctx: CommandContext) -> CommandResult:
        pass

    def help_text(self) -> str:
        lines = [f"**{self.name}** - {self.description}"]
        if self.usage:
            lines.append(f"用法: {self.usage}")
        if self.aliases:
            lines.append(f"别名: {', '.join(self.aliases)}")
        return "\n".join(lines)


class HelpCommand(SlashCommand):
    name = "/help"
    description = "显示可用命令列表"
    aliases = ["?", "/h"]
    usage = "/help [命令名]"

    def __init__(self, registry: "CommandRegistry") -> None:
        self.registry = registry

    def execute(self, ctx: CommandContext) -> CommandResult:
        if ctx.args:
            cmd_name = ctx.args.strip().lower()
            if not cmd_name.startswith("/"):
                cmd_name = "/" + cmd_name
            cmd = self.registry.get_command(cmd_name)
            if cmd:
                return CommandResult(response_text=cmd.help_text())
            return CommandResult(response_text=f"未找到命令: {cmd_name}")

        lines = ["## 可用命令", ""]
        for cmd in self.registry.list_commands():
            lines.append(f"- **{cmd.name}** - {cmd.description}")
        lines.append("")
        lines.append("输入 `/help <命令名>` 查看详细用法。")
        return CommandResult(response_text="\n".join(lines))


class StatsCommand(SlashCommand):
    name = "/stats"
    description = "显示 Token 消耗统计"
    aliases = ["/usage", "/tokens"]
    usage = "/stats"

    def execute(self, ctx: CommandContext) -> CommandResult:
        usage_text = "未找到 Token 消耗统计。"
        conversation = getattr(ctx.session, "conversation", None)
        if conversation is not None:
            tracker = getattr(conversation, "cost_tracker", None)
            if tracker is not None and hasattr(tracker, "summary_dict"):
                model_name = ctx.session._get_model_name() if hasattr(ctx.session, "_get_model_name") else ""
                summary = tracker.summary_dict(model_name=model_name)
                lines = [
                    "**Token 消耗统计**",
                    f"- Input Tokens: {summary.get('input_tokens', 0)}",
                    f"- Output Tokens: {summary.get('output_tokens', 0)}",
                    f"- Total Tokens: {summary.get('total_tokens', 0)}",
                    f"- Events: {summary.get('event_count', 0)}",
                ]
                if summary.get("estimated_cost_usd") is not None:
                    lines.append(f"- Estimated Cost: ${summary['estimated_cost_usd']:.4f}")
                if summary.get("cache_hit_ratio") is not None:
                    lines.append(f"- Cache Hit Rate: {summary['cache_hit_ratio'] * 100:.1f}%")
                usage_text = "\n".join(lines)
        return CommandResult(response_text=usage_text)


class ClearCommand(SlashCommand):
    name = "/clear"
    description = "清空会话历史"
    aliases = ["/reset"]
    usage = "/clear"

    def execute(self, ctx: CommandContext) -> CommandResult:
        ctx.session.messages.clear()
        from autosongshu_agent.memory import LayeredConversationMemory

        ctx.session.memory = LayeredConversationMemory()
        conversation = getattr(ctx.session, "conversation", None)
        if conversation is not None:
            try:
                conversation.close()
            except Exception:
                pass
            ctx.session.conversation = None
        return CommandResult(
            response_text="会话历史已清空。",
            updated_session={"memory": ctx.session.memory.model_dump()},
        )


class StatusCommand(SlashCommand):
    name = "/status"
    description = "显示当前会话状态"
    aliases = ["/info"]
    usage = "/status"

    def execute(self, ctx: CommandContext) -> CommandResult:
        session = ctx.session
        lines = [
            "## 会话状态",
            f"- **会话ID**: {session.session_id}",
            f"- **状态**: {session.status}",
            f"- **消息数**: {len(session.messages)}",
            f"- **模式**: {getattr(session, 'mode', 'auto')}",
        ]
        if session.start_url:
            lines.append(f"- **起始URL**: {session.start_url}")
        if session.allowed_hosts:
            lines.append(f"- **允许主机**: {', '.join(session.allowed_hosts)}")
        if session.artifact_dir:
            lines.append(f"- **Artifact目录**: {session.artifact_dir}")
        if session.knowledge_base_ids:
            lines.append(f"- **知识库**: {len(session.knowledge_base_ids)} 个")
        memory = getattr(session, "memory", None)
        if memory is not None and hasattr(memory, "summary"):
            if memory.summary:
                lines.append(f"- **记忆摘要**: {memory.summary[:100]}...")
        return CommandResult(response_text="\n".join(lines))


class InterruptCommand(SlashCommand):
    name = "/interrupt"
    description = "中断当前任务执行"
    aliases = ["/stop", "/abort"]
    usage = "/interrupt"

    def execute(self, ctx: CommandContext) -> CommandResult:
        if ctx.session.status not in ("running", "interrupting"):
            return CommandResult(response_text="当前没有正在执行的任务。")
        if ctx.session.status == "interrupting":
            return CommandResult(response_text="任务已在中断中...")
        return CommandResult(
            response_text="请使用中断按钮来停止当前任务。",
            assistant_status="completed",
        )


class ModeCommand(SlashCommand):
    name = "/mode"
    description = "切换执行模式"
    usage = "/mode [auto|semi-auto]"

    def execute(self, ctx: CommandContext) -> CommandResult:
        args = ctx.args.strip().lower()
        if not args:
            current_mode = getattr(ctx.session, "mode", "auto")
            return CommandResult(
                response_text=f"当前模式: **{current_mode}**\n\n可用模式: auto, semi-auto"
            )

        valid_modes = ("auto", "semi-auto")
        if args not in valid_modes:
            return CommandResult(
                response_text=f"无效模式: {args}\n\n可用模式: {', '.join(valid_modes)}"
            )

        ctx.session.mode = args
        return CommandResult(
            response_text=f"已切换到 **{args}** 模式。",
            updated_session={"mode": args},
        )


class CompactCommand(SlashCommand):
    name = "/compact"
    description = "压缩会话记忆"
    aliases = ["/summarize"]
    usage = "/compact"

    def execute(self, ctx: CommandContext) -> CommandResult:
        def async_handler(session_id: str, message_id: str) -> None:
            ctx.manager._process_slash_compact(session_id, message_id)

        return CommandResult(
            response_text="正在压缩会话记忆...",
            requires_async=True,
            async_handler=async_handler,
            assistant_status="in_progress",
        )


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name.lower()] = command
        for alias in command.aliases:
            self._aliases[alias.lower()] = command.name.lower()

    def get_command(self, name: str) -> SlashCommand | None:
        lowered = name.lower()
        if lowered in self._commands:
            return self._commands[lowered]
        if lowered in self._aliases:
            return self._commands.get(self._aliases[lowered])
        return None

    def list_commands(self) -> list[SlashCommand]:
        return list(self._commands.values())

    def is_command(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return False
        parts = stripped.split()
        if not parts:
            return False
        cmd_name = parts[0].lower()
        return cmd_name in self._commands or cmd_name in self._aliases

    def parse_command(self, text: str) -> tuple[str, str] | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped.split(None, 1)
        if not parts:
            return None
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return cmd_name, args


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(HelpCommand(registry))
    registry.register(StatsCommand())
    registry.register(ClearCommand())
    registry.register(StatusCommand())
    registry.register(InterruptCommand())
    registry.register(ModeCommand())
    registry.register(CompactCommand())
    return registry


default_command_registry = create_default_registry()


__all__ = [
    "CommandContext",
    "CommandResult",
    "SlashCommand",
    "CommandRegistry",
    "create_default_registry",
    "default_command_registry",
    "HelpCommand",
    "StatsCommand",
    "ClearCommand",
    "StatusCommand",
    "InterruptCommand",
    "ModeCommand",
    "CompactCommand",
]
