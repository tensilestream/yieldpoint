"""A PreToolUse gate for the Claude Agent SDK — enforcement, not advice.

The SDK lets a hook run before a tool call and deny it. That placement is the
whole point: the agent proposes the edit, and something outside the agent
decides whether it lands. An MCP tool cannot do this, because calling it is the
agent's choice.

Fails open throughout. If the payload cannot be parsed, the file cannot be read,
or the verifier raises, the edit is allowed — blocking someone's work because
the checker got confused is worse than not checking.
"""

from __future__ import annotations

from aegisflow.hook import blocks, build_change, evaluate, render


async def aegis_pretooluse(input_data, tool_use_id, context):
    """Register for ``PreToolUse`` on Edit|MultiEdit|Write.

    Returns the SDK's permission-decision shape: deny carries the prescription,
    which is what the agent reads and acts on.
    """
    del tool_use_id, context
    verdict, change = evaluate(input_data)

    if not change.usable or not blocks(verdict):
        return {}

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": render(verdict, change),
        }
    }


def options():
    """Wire it into the SDK's options object."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    return ClaudeAgentOptions(
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Edit|MultiEdit|Write", hooks=[aegis_pretooluse])
            ]
        }
    )


def without_the_sdk() -> None:
    """The same gate with no SDK at all: a subprocess reading stdin.

        aegisflow install-hook        # writes .claude/settings.json

    Exit 0 allows, exit 2 denies and feeds stderr back to the agent.
    """
