"""Agent sub-task tool.

Ported from claw-code's Agent tool. Allows spawning specialized sub-agents
for complex, multi-step tasks that can run independently.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "agent",
    description="子 Agent 工具：启动专业化子任务，独立执行复杂的多步骤操作。",
    risk_level=ToolRiskLevel.HIGH,
    requires_approval=True,
)


@registry.register(
    "agent",
    description="启动一个专业化子 Agent 来执行独立任务。适用于需要并行处理或隔离上下文的复杂操作。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def spawn_agent(
    runtime: PentestRuntime,
    description: str,
    prompt: str,
    name: str = "",
    subagent_type: str = "general",
) -> ToolResponse:
    """Spawn a specialized sub-agent for a task.

    Args:
        description: Short description of what the agent should do.
        prompt: Detailed prompt/instructions for the agent.
        name: Optional name for the agent instance.
        subagent_type: Type of sub-agent: "general", "research", "testing".
    """
    try:
        agent_id = uuid.uuid4().hex[:12]
        agent_name = name.strip() or f"agent_{agent_id}"

        # Create agent output directory
        agent_dir = runtime.artifacts.path("agents") / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write agent manifest
        manifest = {
            "agent_id": agent_id,
            "name": agent_name,
            "type": subagent_type,
            "description": description,
            "prompt": prompt,
            "status": "created",
            "created_at": time.time(),
            "output_dir": str(agent_dir),
        }
        runtime.artifacts.write_json(f"agents/{agent_id}/manifest.json", manifest)

        # Store in runtime's agent registry if available
        if not hasattr(runtime, "_agents"):
            runtime._agents = {}
        runtime._agents[agent_id] = manifest

        return _tool_response({
            "ok": True,
            "agent_id": agent_id,
            "name": agent_name,
            "type": subagent_type,
            "status": "created",
            "message": f"子 Agent '{agent_name}' 已创建 (ID: {agent_id})",
            "output_dir": str(agent_dir),
        })
    except Exception as exc:
        return _error_response(exc)
