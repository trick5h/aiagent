from typing import Any

from config import MEMORY_PATH, SOUL_PATH
from src.memory import load_recent_memory_notes

# =========================
# Soul / Prompt
# =========================

def load_soul() -> str:
    if not SOUL_PATH.exists():
        return (
            "# Personality\n"
            "You are a helpful local AI agent.\n\n"
            "# Rules\n"
            "- Be concise.\n"
            "- Use tools when needed.\n"
            "- Do not hallucinate tool results.\n"
        )
    return SOUL_PATH.read_text(encoding="utf-8")


def build_system_prompt() -> str:
    soul = load_soul()
    recent_memory = load_recent_memory_notes(MEMORY_PATH)

    prompt = f"""\
{soul}

# Tool-Use Policy
- Before every tool call, ask yourself: "Does this tool directly help solve the user's current question?"
- If the answer is no, do not call a tool.
- If the answer is yes, only call the most directly relevant tool.
- Chain multiple tools only when each next tool is directly justified by the previous observation.
- Always keep the user's original question as the target of the final answer; do not drift to unrelated data.
"""

    if recent_memory:
        prompt += f"\n# Recent Memory\n{recent_memory}\n"

    return prompt


def build_final_answer_prompt(tool_result_text: str) -> str:
    return (
        "# FINAL ANSWER MODE - RESPOND IN NATURAL LANGUAGE ONLY\n"
        "==== IMPORTANT ====\n"
        "You MUST respond with ONLY natural language text. There are NO tools available in this mode.\n"
        "Do NOT output JSON, do NOT attempt to call tools, do NOT use any special formatting.\n"
        "==== END INSTRUCTIONS ====\n\n"
        f"Tool result obtained:\n{tool_result_text}\n\n"
        "TASK: Analyze the above result and provide a DIRECT, NATURAL-LANGUAGE answer to the user's original question. Provide a summary if a tool was executed.\n"
        "REQUIREMENTS:\n"
        "- Response MUST be ONLY natural language\n"
        "- MUST directly answer the user's question using the result above, do not make up things that are not in the result\n"
        "- MUST NOT output JSON, code, or any structured format\n"
        "- MUST NOT attempt to call any tools or functions\n"
        "- Keep answer concise and relevant to the question\n"
        "- This result is not a single direct output, but the outcome of multiple repeated processing steps. Please do not assume it represents all available data."
    )

def normalize_chat_response(resp: Any) -> dict:
    """Normalize various ollama chat return types into a dict with a 'message' key.
    Works with plain dicts, objects with .message or .content, or other types.
    """
    if resp is None:
        return {}
    if isinstance(resp, dict):
        return resp
    # If the response object has a 'message' attribute, try to extract it
    if hasattr(resp, "message"):
        m = getattr(resp, "message")
        if isinstance(m, dict):
            return {"message": m}
        # message might be an object with .content
        if hasattr(m, "content"):
            return {"message": {"content": getattr(m, "content")}}
        try:
            return {"message": dict(m)}
        except Exception:
            return {"message": {"content": str(m)}}
    # Fallback: object may have top-level 'content'
    if hasattr(resp, "content"):
        return {"message": {"content": getattr(resp, "content")}}
    # Last resort: stringify
    return {"message": {"content": str(resp)}}