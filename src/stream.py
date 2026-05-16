import time
import inspect
import ollama

from config import MEMORY_PATH, SMALL_MODEL
from src.memory import load_recent_memory_notes
from src.prompt import normalize_chat_response

# =========================
# Tools Determination
# =========================

#async
def is_user_query_needs_tools(user_input: str, tool_result: str | None) -> bool:
    """智能檢測工具是否返回所需數據，以輔助判斷是否需要工具。
    Use the (small) LLM to classify whether this user query needs tools.
    Returns True if tools are needed, False if not, or None on failure.
    The model is asked to reply exactly YES or NO.
    """
    if not user_input:
        return False
    system = """
    You are a strict logical auditor.
    Determine if the Current Tool Result (if have) is sufficient to fully answer the 'User Question'.

    Rules:
    1. If you are not sure if the data contains the answer: Always output YES.
    2. If the data is not related to the question or missing key data needed for the answer: Output YES.
    3. If the results only contain the fields name or running a query to know the exact data is needed: Output YES. (e.g., if the user asks for staff names but only the table schema is shown and no actual data exists, more tools should be called.)
    4. If the question is asking for a specific operation to be performed (e.g., open a URL in browser, search for online information): Output YES.
    5. If the tool result contains the direct answer: Output NO.
    6. If the tool result tells you there is no more tools needed: Output NO.

    Does it need MORE tool calls? Answer only YES or NO."""
    
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"User Question: {user_input}"},
        {"role": "user", "content": f"Current Tool Result: {tool_result}"},
    ]

    
    recent_memory = load_recent_memory_notes(MEMORY_PATH)
    if recent_memory:
        messages.append({"role": "user", "content": f"\n# Recent Memory\n{recent_memory}\n"})

    print(f"> [Debug] 判斷是否需要工具，問題: {user_input}, 工具結果:({tool_result})")
    try:
        resp = ollama.chat(
            model=SMALL_MODEL,
            messages=messages,
            options={"temperature": 0.1},
        )
        if inspect.isawaitable(resp):
            resp = ''#await resp
        resp = normalize_chat_response(resp)
        content = str(resp.get('message', {}).get('content', '')).strip().upper()
        if content.startswith('Y'):
            return True
        if content.startswith('N'):
            return False
    except Exception:
        return True
    return True


# =========================
# Streaming Output
# =========================

def print_streaming(text: str, delay: float = 0.02) -> None:
    """Print text character by character like ChatGPT streaming."""
    print()
    for char in text:
        print(char, end="", flush=True)
        time.sleep(delay)
    print()  # New line at the end


def is_shell_noise_input(text: str) -> bool:
    normalized = " ".join(text.split()).lower()
    if not normalized:
        return True
    return (
        "set-executionpolicy" in normalized
        and "activate.ps1" in normalized
    ) or normalized.startswith("(& ") and "activate" in normalized