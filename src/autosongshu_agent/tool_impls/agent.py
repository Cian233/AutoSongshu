"""Sub-agent tool implementation."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from agentscope.message import Msg
from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _tool_response

registry.create_group(
    "agent",
    description="Sub-agent tools: run delegated tasks and return summaries.",
    risk_level=ToolRiskLevel.HIGH,
    requires_approval=True,
)

_ROLE_DESCRIPTIONS = {
    "recon": "recon",
    "scanner": "scanner",
    "exploit": "exploit",
    "report": "report",
    "general": "general",
}

_ROLE_TOOL_GROUPS = {
    "recon": ["http", "browser", "knowledge"],
    "scanner": ["sandbox", "skill-scripts", "findings"],
    "exploit": ["sandbox", "skill-scripts", "findings", "http"],
    "report": ["findings", "knowledge"],
    "general": ["http", "browser", "sandbox", "findings", "knowledge"],
}

_ROLE_MODEL_PROFILES = {
    "recon": None,
    "scanner": None,
    "exploit": None,
    "report": None,
    "general": None,
}


@registry.register(
    "agent",
    description="Spawn a sub-agent to execute a focused task.",
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
    """Spawn and execute a specialized sub-agent for a task."""
    agent_id = uuid.uuid4().hex[:12]
    agent_name = name.strip() or f"agent_{agent_id}"

    if role not in _ROLE_DESCRIPTIONS:
        role = "general"

    try:
        agent_dir = runtime.artifacts.path("agents") / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

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

        if not hasattr(runtime, "_agents"):
            runtime._agents = {}
        runtime._agents[agent_id] = manifest

        result = _execute_sub_agent(runtime, agent_id, role, prompt, description)

        manifest["status"] = "completed"
        manifest["result"] = result
        manifest["completed_at"] = time.time()
        runtime.artifacts.write_json(f"agents/{agent_id}/manifest.json", manifest)
        runtime._agents[agent_id] = manifest

        return _tool_response(
            {
                "ok": True,
                "agent_id": agent_id,
                "name": agent_name,
                "type": subagent_type,
                "role": role,
                "role_description": _ROLE_DESCRIPTIONS[role],
                "status": "completed",
                "message": f"Sub-agent '{agent_name}' completed ({_ROLE_DESCRIPTIONS[role]}).",
                "result": result,
            },
        )
    except Exception as exc:
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
    """Execute a sub-agent and return a short textual summary."""
    logger = logging.getLogger(__name__)
    builder = getattr(runtime, "_agent_builder", None)

    if builder is None:
        import inspect

        frame = inspect.currentframe()
        while frame:
            maybe_self = frame.f_locals.get("self")
            if maybe_self is not None and hasattr(maybe_self, "_build_sub_agent"):
                builder = maybe_self
                break
            frame = frame.f_back

    if builder is None or not hasattr(builder, "_build_sub_agent"):
        logger.warning(
            "Sub-agent %s: no builder available; returning placeholder result.",
            agent_id,
        )
        return f"Sub-agent ({role}) created but could not execute: missing builder."

    tool_groups = _ROLE_TOOL_GROUPS.get(role, _ROLE_TOOL_GROUPS["general"])
    model_profile = _ROLE_MODEL_PROFILES.get(role)

    try:
        sub_agent = builder._build_sub_agent(
            role=_ROLE_DESCRIPTIONS.get(role, role),
            tool_groups=tool_groups,
            model_profile=model_profile,
        )
    except Exception as exc:
        logger.error("Sub-agent %s: failed to build: %s", agent_id, exc)
        return f"Sub-agent ({role}) build failed: {exc}"

    user_msg = Msg(
        name="User",
        content=f"Task: {description}\n\nInstructions:\n{prompt}",
        role="user",
    )

    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(sub_agent(user_msg), loop)
            response = future.result(timeout=300)
        else:
            response = loop.run_until_complete(sub_agent(user_msg))

        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content[:2000]
            if isinstance(content, list):
                texts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        texts.append(str(block["text"]))
                    elif isinstance(block, str):
                        texts.append(block)
                return "\n".join(texts)[:2000]
            return str(content)[:2000]
        return f"Sub-agent ({role}) completed with non-text response."
    except Exception as exc:
        logger.error("Sub-agent %s: execution failed: %s", agent_id, exc)
        return f"Sub-agent ({role}) execution failed: {exc}"
