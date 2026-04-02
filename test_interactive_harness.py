import sys
import json
from unittest.mock import MagicMock
import builtins

# mock dependencies
sys.modules["agentscope.message"] = MagicMock()
sys.modules["agentscope.tool"] = MagicMock()

from src.autosongshu_agent.tools import register_default_tools, _wrap_registered_tool, _ToolExecutionPolicy

toolkit = MagicMock()
runtime = MagicMock()

def dummy_sandbox_write_file(path, content):
    return {"status": "written"}

wrapped = _wrap_registered_tool(
    dummy_sandbox_write_file, 
    runtime, 
    policy=_ToolExecutionPolicy(requires_approval=True)
)

print("Running with requires_approval=True. We will simulate input 'n'.")

# override input to simulate "n"
builtins.input = lambda prompt: "n"

result = wrapped(path="/tmp/test", content="hello")
print("Result with n:", getattr(result, "content", result))

# override input to simulate "y"
builtins.input = lambda prompt: "y"

result2 = wrapped(path="/tmp/test", content="hello")
print("Result with y:", getattr(result2, "content", result2))

