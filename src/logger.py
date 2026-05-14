from datetime import datetime
import json
from typing import Any

from config import LOG_PATH
from src.prompt import normalize_chat_response

# =========================
# Logs
# =========================
# Insert logging helpers after normalization

def append_log(entry: dict) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        # Avoid raising from logger
        print(f"[logger] failed to write log: {e}")


def log_llm_call(request: dict, response: Any = None, error: Any = None, start: float | None = None, end: float | None = None) -> None:
    entry: dict = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "llm",
        "request": request,
        "error": None,
        "response": None,
        "duration_seconds": None,
    }
    if start is not None and end is not None:
        try:
            entry["duration_seconds"] = float(f"{end - start:.4f}")
        except Exception:
            entry["duration_seconds"] = None

    if error is not None:
        entry["error"] = str(error)

    try:
        if response is not None:
            # Try to keep response small: extract normalized message and tool_calls
            resp_norm = normalize_chat_response(response)
            msg = resp_norm.get("message")
            entry["response"] = {
                "message": msg,
            }
    except Exception as e:
        entry["response"] = {"error_while_serializing": str(e)}

    append_log(entry)

def log_tool_call(tool_name: str, arguments: dict, result: Any = None, error: Any = None) -> None:
    entry: dict = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "tool",
        "tool_name": tool_name,
        "arguments": arguments,
        "result": None,
        "error": None,
    }
    if error is not None:
        entry["error"] = str(error)
    else:
        try:
            entry["result"] = str(result)
        except Exception as e:
            entry["result"] = f"Error while serializing result: {e}"

    append_log(entry)

def tool_result_to_text(result: Any) -> str:
    if result is None:
        return ""

    if hasattr(result, "content"):
        content = result.content

        if isinstance(content, list):
            parts = []
            for block in content:
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)

        if isinstance(content, str):
            return content

        return str(content)

    return str(result)