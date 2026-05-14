import time
import json
from typing import Any

# =========================
# Dynamic Message
# =========================
# Build dynamic warning messages about tool execution history and availability, and to append assistant/tool messages to the conversation.

def append_assistant_message(messages: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    assistant_message = response.get("message", {}) or {}
    normalized_message: dict[str, Any] = {"role": "assistant"}

    content = assistant_message.get("content")
    if content is not None:
        normalized_message["content"] = content

    tool_calls = assistant_message.get("tool_calls")
    if tool_calls:
        normalized_message["tool_calls"] = tool_calls

    messages.append(normalized_message)
    return normalized_message


def append_tool_message(messages: list[dict[str, Any]], tool_call: dict[str, Any], tool_text: str) -> None:
    tool_message: dict[str, Any] = {
        "role": "tool",
        "content": tool_text,
    }

    tool_call_id = tool_call.get("id")
    if tool_call_id:
        tool_message["tool_call_id"] = tool_call_id

    messages.append(tool_message)


def extract_tool_call_from_content(content: Any) -> dict[str, Any] | None:
    """Parse a JSON tool request from assistant content when tool_calls is absent.

    Supported shapes:
    - {"name": "tool_name", "arguments": {...}}
    - {"tool_name": "..."} is intentionally not supported to avoid ambiguity.
    """
    if isinstance(content, dict):
        candidate = content
    elif isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            candidate = json.loads(text)
        except Exception:
            return None
    else:
        return None

    if not isinstance(candidate, dict):
        return None

    tool_name = candidate.get("name")
    arguments = candidate.get("arguments", {})

    if not isinstance(tool_name, str) or not tool_name:
        return None
    if not isinstance(arguments, dict):
        return None

    return {
        "id": f"json-{tool_name}-{int(time.time() * 1000)}",
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": arguments,
        },
    }


def build_dynamic_warning(
    executed_tools: set[str],
    failed_tools: set[str],
    available_tool_names: set[str],
) -> str:
    """Build a dynamic warning message about tool execution history and availability."""
    warnings = []

    if available_tool_names:
        warnings.append(f"Available tools: {', '.join(sorted(available_tool_names))}")

    if failed_tools:
        warnings.append(
            f"FAILED (do not retry): {', '.join(sorted(failed_tools))}"
        )

    if executed_tools:
        warnings.append(
            f"ALREADY EXECUTED this round: {', '.join(sorted(executed_tools))}"
        )

    if warnings:
        return (
            "# Dynamic Execution Warnings\n"
            + "\n".join(warnings)
            + "\n\nBefore calling any tool, ask: does this tool directly help solve the user's current question? If not, do not call it. Do NOT call failed tools. Do NOT repeat the same tool with identical parameters."
        )
    return ""



def build_turn_summary(user_input: str, assistant_text: str, tool_text: str = "") -> str:
    summary_source = assistant_text.strip() or tool_text.strip() or user_input.strip()
    summary_source = " ".join(summary_source.split())
    if len(summary_source) > 120:
        summary_source = summary_source[:200] + "..."
    return summary_source


def dedupe_consecutive_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove consecutive duplicate role/content pairs before sending to the model.

    This keeps runtime history stable, but prevents repeated messages from being
    replayed multiple times into a single request.
    """
    deduped: list[dict[str, Any]] = []
    for message in messages:
        if deduped:
            previous = deduped[-1]
            if previous.get("role") == message.get("role") and previous.get("content") == message.get("content"):
                continue
        deduped.append(message)
    return deduped