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

from agentscope.message import Msg
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

# Role-to-tool-group mapping
_ROLE_TOOL_GROUPS = {
    "recon": ["http", "browser", "knowledge"],
    "scanner": ["sandbox", "skill-scripts", "findings"],
    "exploit": ["sandbox", "skill-scripts", "findings", "http"],
    "report": ["findings", "knowledge"],
    "general": ["http", "browser", "sandbox", "findings", "knowledge"],
}

_ROLE_MODEL_PROFILES = {
    "recon": None,  # use default
    "scanner": None,
    "exploit": None,
    "report": None,
    "general": None,
}


@registry.register(
    "agent",
    description="启动一个专业化子 Agent 来执行独立任务。适用于需要并行处理或隔离上下文的复杂操作。\n\n"
                "何时使用：\n"
                "- 任务可以分解为多个独立子任务时，并行启动多个子 Agent\n"
                "- 需要专业角色（侦察/扫描/利用/报告）时，指定对应角色\n"
                "- 任务需要隔离上下文，避免污染主 Agent 的对话历史\n"
                "- 你只需要最终结果，不需要关注中间过程\n\n"
                "可用角色:\n"
                "- recon: 信息收集专家（HTTP 请求、浏览器操作、DNS 查询）\n"
                "- scanner: 漏洞扫描专家（Nmap、Dirsearch、SQLMap 等技能脚本）\n"
                "- exploit: 漏洞利用专家（Payload 生成、漏洞验证）\n"
                "- report: 报告生成专家（发现汇总、报告导出）\n"
                "- general: 通用专家（全工具集）\n\n"
                "注意：子 Agent 会立即执行，完成后返回结果。你只会收到最终摘要。",
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
    role: str = "general",
) -> ToolResponse:
    """Spawn and execute a specialized sub-agent for a task.

    Args:
        description: Short description of what the agent should do.
        prompt: Detailed prompt/instructions for the agent.
        name: Optional name for the agent instance.
        subagent_type: Type of sub-agent: "general", "research", "testing".
        role: Role of the sub-agent: "recon", "scanner", "exploit", "report", "general".
    """
    try:
        agent_id = uuid.uuid4().hex[:12]
        agent_name = name.strip() or f"agent_{agent_id}"

        # Validate role
        valid_roles = ("recon", "scanner", "exploit", "report", "general")
        if role not in valid_roles:
            role = "general"

        # Role descriptions for response
        role_descriptions = {
            "recon": "信息收集专家",
            "scanner": "漏洞扫描专家",
            "exploit": "漏洞利用专家",
            "report": "报告生成专家",
            "general": "通用专家",
        }

        # Create agent output directory
        agent_dir = runtime.artifacts.path("agents") / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write agent manifest
        manifest = {
            "agent_id": agent_id,
            "name": agent_name,
            "type": subagent_type,
            "role": role,
            "description": description,
            "prompt": prompt,
            "status": "running",
            "created_at": time.time(),
            "output_dir": str(agent_dir),
        }
        runtime.artifacts.write_json(f"agents/{agent_id}/manifest.json", manifest)

        # Store in runtime's agent registry if available
        if not hasattr(runtime, "_agents"):
            runtime._agents = {}
        runtime._agents[agent_id] = manifest

        # Execute the sub-agent
        result = _execute_sub_agent(runtime, agent_id, role, prompt, description)

        # Update manifest with result
        manifest["status"] = "completed"
        manifest["result"] = result
        manifest["completed_at"] = time.time()
        runtime.artifacts.write_json(f"agents/{agent_id}/manifest.json", manifest)
        runtime._agents[agent_id] = manifest

        return _tool_response({
            "ok": True,
            "agent_id": agent_id,
            "name": agent_name,
            "type": subagent_type,
            "role": role,
            "role_description": role_descriptions[role],
            "status": "completed",
            "message": f"子 Agent '{agent_name}' 已完成 (角色: {role_descriptions[role]})",
            "result": result,
        })
    except Exception as exc:
        # Update manifest with error
        try:
            if hasattr(runtime, "_agents") and agent_id in runtime._agents:
                runtime._agents[agent_id]["status"] = "failed"
                runtime._agents[agent_id]["error"] = str(exc)
        except Exception:
            pass
        return _error_response(exc)


def _execute_sub_agent(
    runtime: PentestRuntime,
    agent_id: str,
    role: str,
    prompt: str,
    description: str,
) -> str:
    """Execute a sub-agent and return its result.

    This function builds a role-specific sub-agent, executes it with the
    given prompt, and returns a summary of the result.

    Args:
        runtime: The PentestRuntime instance.
        agent_id: The unique ID of the sub-agent.
        role: The role of the sub-agent.
        prompt: The task prompt for the sub-agent.
        description: Short description of the task.

    Returns:
        A summary string of the sub-agent's result.
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    # Get the builder from the runtime context
    builder = getattr(runtime, "_agent_builder", None)
    if builder is None:
        # Fallback: try to get from the caller's context
        import inspect
        frame = inspect.currentframe()
        while frame:
            if "self" in frame.f_locals:
                obj = frame.f_locals["self"]
                if hasattr(obj, "_build_sub_agent"):
                    builder = obj
                    break
            frame = frame.f_back

    if builder is None or not hasattr(builder, "_build_sub_agent"):
        # If no builder available, return a placeholder result
        logger.warning(
            "Sub-agent %s: no builder available; returning placeholder result.",
            agent_id,
        )
        return f"子 Agent ({role}) 已创建但无法执行：缺少构建器。任务描述: {description}"

    # Build the sub-agent
    tool_groups = _ROLE_TOOL_GROUPS.get(role, _ROLE_TOOL_GROUPS["general"])
    model_profile = _ROLE_MODEL_PROFILES.get(role)

    try:
        sub_agent = builder._build_sub_agent(
            role=role_descriptions.get(role, role),
            tool_groups=tool_groups,
            model_profile=model_profile,
        )
    except Exception as exc:
        logger.error("Sub-agent %s: failed to build: %s", agent_id, exc)
        return f"子 Agent ({role}) 构建失败: {exc}"

    # Execute the sub-agent
    role_descriptions = {
        "recon": "信息收集专家",
        "scanner": "漏洞扫描专家",
        "exploit": "漏洞利用专家",
        "report": "报告生成专家",
        "general": "通用专家",
    }

    try:
        user_msg = Msg(
            name="User",
            content=f"任务: {description}\n\n详细指令:\n{prompt}",
            role="user",
        )

        # Run the sub-agent synchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, use asyncio.run_coroutine_threadsafe
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(sub_agent(user_msg), loop)
            response = future.result(timeout=300)  # 5 minute timeout
        else:
            response = loop.run_until_complete(sub_agent(user_msg))

        # Extract result from response
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content[:2000]  # Truncate long results
            elif isinstance(content, list):
                # Extract text blocks
                texts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        texts.append(block["text"])
                    elif isinstance(block, str):
                        texts.append(block)
                return "\n".join(texts)[:2000]
            return str(content)[:2000]

        return f"子 Agent ({role_descriptions.get(role, role)}) 执行完成，但无法解析结果。"

    except Exception as exc:
        logger.error("Sub-agent %s: execution failed: %s", agent_id, exc)
        return f"子 Agent ({role_descriptions.get(role, role)}) 执行失败: {exc}"
