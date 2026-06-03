import time
import json
from typing import Any

# =========================
# Dynamic Message
# =========================
# Build dynamic warning messages about tool execution history and availability, and to append assistant/tool messages to the conversation.


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    return {}


def normalize_tool_call(candidate: Any) -> dict[str, Any] | None:
    """Normalize a single tool-call-like object into the internal OpenAI-style shape.

    Accepted input forms include:
    - {"id": "...", "type": "function", "function": {"name": "tool", "arguments": {...}}}
    - {"name": "tool", "arguments": {...}}
    - {"function": "tool", "parameters": {...}}
    - {"function": {"name": "tool", "arguments": {...}}}
    - {"tool": "tool", "parameters": {...}}
    """
    if not isinstance(candidate, dict):
        return None

    tool_name = candidate.get("name") or candidate.get("tool_name") or candidate.get("tool")
    arguments: dict[str, Any] = _normalize_arguments(candidate.get("arguments"))

    function_field = candidate.get("function")
    if isinstance(function_field, str):
        tool_name = tool_name or function_field
    elif isinstance(function_field, dict):
        tool_name = tool_name or function_field.get("name") or function_field.get("function")
        function_arguments = _normalize_arguments(function_field.get("arguments"))
        if function_arguments:
            arguments = function_arguments
        else:
            parameters = _normalize_arguments(function_field.get("parameters"))
            if parameters:
                arguments = parameters

    parameters = _normalize_arguments(candidate.get("parameters"))
    if parameters and not arguments:
        arguments = parameters

    if not isinstance(tool_name, str) or not tool_name:
        return None

    tool_call_id = candidate.get("id")
    normalized: dict[str, Any] = {
        "type": candidate.get("type") or "function",
        "function": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    if isinstance(tool_call_id, str) and tool_call_id:
        normalized["id"] = tool_call_id

    return normalized


def normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, list):
        normalized_calls: list[dict[str, Any]] = []
        for item in value:
            normalized = normalize_tool_call(item)
            if normalized is not None:
                normalized_calls.append(normalized)
        return normalized_calls

    if isinstance(value, dict):
        # Some LLMs return a wrapper object with tool_calls, some return a single call.
        if "tool_calls" in value and isinstance(value.get("tool_calls"), list):
            return normalize_tool_calls(value.get("tool_calls"))
        normalized = normalize_tool_call(value)
        return [normalized] if normalized is not None else []

    return []

def append_assistant_message(messages: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    assistant_message = response.get("message", {}) or {}
    normalized_message: dict[str, Any] = {"role": "assistant"}

    content = assistant_message.get("content")
    if content is not None:
        normalized_message["content"] = content

    tool_calls = normalize_tool_calls(assistant_message.get("tool_calls"))
    if not tool_calls:
        parsed_from_content = extract_tool_call_from_content(content)
        if parsed_from_content is not None:
            tool_calls = [parsed_from_content]
    if tool_calls:
        normalized_message["tool_calls"] = tool_calls

    messages.append(normalized_message)
    return normalized_message


def append_tool_message(messages: list[dict[str, Any]], tool_call: dict[str, Any], tool_text: str) -> None:
    # Normalise tool call information into the conversation history so the LLM
    # can see which tool was invoked, with what arguments, and what result it produced.
    func = tool_call.get("function") or {}
    tool_name = func.get("name") or tool_call.get("name") or "<unknown>"
    tool_args = func.get("arguments") or tool_call.get("arguments") or {}

    # Compose a readable content block that includes invocation metadata
    try:
        args_text = json.dumps(tool_args, ensure_ascii=False, indent=2)
    except Exception:
        args_text = str(tool_args)

    content = f"[Tool: {tool_name}]\nArguments:\n{args_text}\n\nResult:\n{tool_text}"

    tool_message: dict[str, Any] = {
        "role": "tool",
        "content": content,
        "name": tool_name,
        "arguments": tool_args,
    }

    tool_call_id = tool_call.get("id")
    if tool_call_id:
        tool_message["tool_call_id"] = tool_call_id

    messages.append(tool_message)


def extract_tool_call_from_content(content: Any) -> dict[str, Any] | None:
    """Parse a JSON tool request from assistant content when tool_calls is absent.

    Supported shapes:
    - {"name": "tool_name", "arguments": {...}}
    - {"function": "tool_name", "parameters": {...}}
    - {"function": {"name": "tool_name", "arguments": {...}}}
    - {"tool_calls": [...]} (single embedded call or wrapper)
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

    normalized = normalize_tool_call(candidate)
    if normalized is None:
        return None

    if not normalized.get("id"):
        normalized["id"] = f"json-{normalized['function']['name']}-{int(time.time() * 1000)}"

    return normalized


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