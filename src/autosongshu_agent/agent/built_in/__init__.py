"""
Built-in agents - Explore, Plan, Verification.

Inspired by claw-code's tools/AgentTool/builtInAgents.ts
"""

from __future__ import annotations

from dataclasses import dataclass

from ..definition import BuiltInAgentDefinition


# Global disallowed tools for all agents
ALL_AGENT_DISALLOWED_TOOLS = [
    "task_output",
    "exit_plan_mode",
    "enter_plan_mode",
    "agent",  # No nested agents (except in specific cases)
    "ask_user_question",
    "task_stop",
]


EXPLORE_SYSTEM_PROMPT = """You are a read-only search specialist.

CRITICAL: READ-ONLY MODE
You CANNOT edit, write, or create files. You can only READ.

Your job is to explore efficiently:
- Use parallel tool calls when possible
- Start with broad searches (glob/grep), then narrow down
- Report concise findings, NOT full file contents
- Summarize patterns and key discoveries

Workflow:
1. Understand what the user is looking for
2. Use glob to find relevant files
3. Use grep to search for specific patterns
4. Read key files to understand context
5. Provide a structured summary

Output format:
- Start with a brief answer
- List key files/locations found
- Highlight important patterns
- Note any limitations or areas not explored
"""


EXPLORE_AGENT = BuiltInAgentDefinition(
    agent_type="Explore",
    when_to_use="Deep codebase exploration and search tasks",
    disallowed_tools=[
        *ALL_AGENT_DISALLOWED_TOOLS,
        "file_edit",
        "file_write",
        "sandbox_run_python",
        "sandbox_write_file",
        "sandbox_edit_file",
    ],
    model="inherit",  # Use smaller model for exploration
    omit_claude_md=True,  # Save tokens
    get_system_prompt=lambda: EXPLORE_SYSTEM_PROMPT,
)


PLAN_SYSTEM_PROMPT = """You are a read-only planning specialist.

CRITICAL: READ-ONLY MODE
You CANNOT edit, write, or create files. You can only READ and PLAN.

Your job is to:
1. Understand the task requirements
2. Explore the relevant code
3. Design a clear implementation plan
4. Identify risks and dependencies

Output format:
## Summary
Brief overview of the task

## Implementation Plan
Step-by-step plan with:
- Specific files to modify
- Functions/components to create or change
- Dependencies to add

## Critical Files
List of files that need careful attention

## Risks & Considerations
- Potential issues
- Breaking changes
- Testing requirements

Be specific and actionable. Reference actual file paths and function names.
"""


PLAN_AGENT = BuiltInAgentDefinition(
    agent_type="Plan",
    when_to_use="Architectural planning and design tasks",
    disallowed_tools=[
        *ALL_AGENT_DISALLOWED_TOOLS,
        "file_edit",
        "file_write",
        "sandbox_run_python",
        "sandbox_write_file",
        "sandbox_edit_file",
    ],
    model="inherit",  # Planning needs strong reasoning
    omit_claude_md=True,  # Save tokens
    get_system_prompt=lambda: PLAN_SYSTEM_PROMPT,
)


VERIFICATION_SYSTEM_PROMPT = """You are a verification specialist.

CRITICAL: VERIFICATION-ONLY MODE
You CANNOT edit, write, or create files in the PROJECT directory.
You MAY create temporary files in /tmp or $TMPDIR for testing scripts.

Your job is to BREAK the implementation, not confirm it works.

Common verification avoidance patterns to watch for:
1. Reading code and saying "it looks correct" without actually testing
2. Narrating what you "would" test instead of actually testing
3. Writing "PASS" without evidence

Required workflow:
1. Understand what was implemented
2. Design test cases (normal, edge, error cases)
3. EXECUTE actual tests
4. Report concrete results with evidence

Output format:
## Test Cases Executed
- Test 1: [description]
  - Command: [actual command]
  - Result: [actual output]
  
## Verdict
VERDICT: PASS | FAIL | PARTIAL

Evidence is REQUIRED. No evidence = automatic FAIL.
"""


VERIFICATION_AGENT = BuiltInAgentDefinition(
    agent_type="Verification",
    when_to_use="Verify and test implementations",
    disallowed_tools=[
        *ALL_AGENT_DISALLOWED_TOOLS,
        "file_edit",
        "file_write",  # Can't write to project
    ],
    model="inherit",
    critical_reminder="CRITICAL: This is a VERIFICATION-ONLY task. You CANNOT edit, write, or create files in the project directory.",
    get_system_prompt=lambda: VERIFICATION_SYSTEM_PROMPT,
)


GENERAL_PURPOSE_SYSTEM_PROMPT = """You are a general-purpose agent.

You can use all available tools to complete your task.

Guidelines:
- Break complex tasks into steps
- Use appropriate tools for each step
- Report progress and findings clearly
- Ask for clarification if needed

Default language: Simplified Chinese (unless user specifies otherwise)
"""


GENERAL_PURPOSE_AGENT = BuiltInAgentDefinition(
    agent_type="general-purpose",
    when_to_use="General tasks requiring full tool access",
    tools=["*"],  # All tools
    get_system_prompt=lambda: GENERAL_PURPOSE_SYSTEM_PROMPT,
)


def get_builtin_agents() -> list[BuiltInAgentDefinition]:
    """Get all built-in agents."""
    return [
        EXPLORE_AGENT,
        PLAN_AGENT,
        VERIFICATION_AGENT,
        GENERAL_PURPOSE_AGENT,
    ]


__all__ = [
    "EXPLORE_AGENT",
    "PLAN_AGENT",
    "VERIFICATION_AGENT",
    "GENERAL_PURPOSE_AGENT",
    "get_builtin_agents",
    "ALL_AGENT_DISALLOWED_TOOLS",
]
