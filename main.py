import asyncio
from pathlib import Path 
from mcp import ClientSession, StdioServerParameters 
from mcp.client.stdio import stdio_client 
import ollama 
import json
import inspect
import re
from typing import Any 
import time
from datetime import datetime
import anyio
import sys

# =========================
# Config
# =========================

MODEL = "qwen2.5-coder:7b"
SERVER_COMMAND = "python"          # or "python3"
SERVER_PATH = Path("mcpServer/server.py")        # your FastMCP server
SOUL_PATH = Path("SOUL.md")
MEMORY_PATH = Path("MEMORY.md")
MAX_TOOL_LOOPS = 8
LOG_PATH = Path(__file__).resolve().parent / "logs.jsonl"
SESSION_LOG_HEADER = "## Session Log"
SESSION_MEMORY_LIMIT = 5

# =========================
# Memory
# =========================

def load_recent_memory_notes(path: Path, limit: int = SESSION_MEMORY_LIMIT) -> str:
    if not path.exists():
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    session_lines = [
        line for line in lines
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}: ", line)
    ]
    if not session_lines:
        return ""
    return "\n".join(session_lines[-limit:])


def append_memory_summary(path: Path, summary: str) -> None:
    summary = " ".join(summary.split()).strip()
    if not summary:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        existing_text = ""

    needs_header = SESSION_LOG_HEADER not in existing_text
    with open(path, "a", encoding="utf-8") as fh:
        if needs_header:
            if existing_text and not existing_text.endswith("\n"):
                fh.write("\n")
            fh.write(f"\n{SESSION_LOG_HEADER}\n")
        fh.write(f"{timestamp}, {summary}\n")

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

# Tool Usage Rules
- When a tool is needed, call it with .json format.
- Do not invent tool results.
- Use an iterative think-observe-act loop: after a tool result, inspect it and decide whether another tool call is needed before answering.
- If you already have enough information, answer directly.
- If one tool already answers the user request, stop calling tools and answer from that result.
- Prefer the smallest sufficient tool set; do not call unrelated tools.
"""

    if recent_memory:
        prompt += f"\n# Recent Memory\n{recent_memory}\n"

    return prompt


def _normalize_chat_response(resp: Any) -> dict:
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

# =========================
# Logs
# =========================
# Insert logging helpers after normalization

def _append_log(entry: dict) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        # Avoid raising from logger
        print(f"[logger] failed to write log: {e}")


def log_llm_call(request: dict, response: Any = None, error: Any = None, start: float | None = None, end: float | None = None) -> None:
    entry: dict = {
        "timestamp": datetime.now(),
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
            resp_norm = _normalize_chat_response(response)
            msg = resp_norm.get("message")
            entry["response"] = {
                "message": msg,
            }
    except Exception as e:
        entry["response"] = {"error_while_serializing": str(e)}

    _append_log(entry)

def log_tool_call(tool_name: str, arguments: dict, result: Any = None, error: Any = None) -> None:
    entry: dict = {
        "timestamp": datetime.now(),
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

    _append_log(entry)

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


# =========================
# Dynamic Message
# =========================
# Build dynamic warning messages about tool execution history and availability, and to append assistant/tool messages to the conversation.
def _append_assistant_message(messages: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
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


def _append_tool_message(messages: list[dict[str, Any]], tool_call: dict[str, Any], tool_text: str) -> None:
    tool_message: dict[str, Any] = {
        "role": "tool",
        "content": tool_text,
    }

    tool_call_id = tool_call.get("id")
    if tool_call_id:
        tool_message["tool_call_id"] = tool_call_id

    messages.append(tool_message)


def _extract_tool_call_from_content(content: Any) -> dict[str, Any] | None:
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


def _build_dynamic_warning(
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
            + "\n\nDo NOT call failed tools. Do NOT repeat the same tool with identical parameters."
        )
    return ""


def _build_final_answer_prompt(tool_result_text: str) -> str:
    return (
        "You already have the tool result. "
        "Try to answer directly and only call another tools if necessary. "
        f"Use this observation only: {tool_result_text}"
    )


def _build_turn_summary(user_input: str, assistant_text: str, tool_text: str = "") -> str:
    summary_source = assistant_text.strip() or tool_text.strip() or user_input.strip()
    summary_source = " ".join(summary_source.split())
    if len(summary_source) > 120:
        summary_source = summary_source[:117] + "..."
    return summary_source


def _dedupe_consecutive_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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



# ===========================================================================
###############################################################################
#                                                                             #
#                          START OF MAIN EXECUTION                            #
#                                                                             #
###############################################################################
# =========================
# Main Agent
# =========================


async def run_mcp_agent(): 
    # A. 設定如何啟動你的 Server (stdio 模式) 
    server_params = StdioServerParameters(
        command="python", # 或是 "python3" 
        args=[str(SERVER_PATH)], # 你的 FastMCP 程式碼檔案 
    ) 
    # B. 建立連線 (auto-reconnect on broken resource)
    while True:
        try:
            async with stdio_client(server_params) as (read, write): 
                async with ClientSession(read, write) as session: 
                    # 初始化 MCP 連線 
                    await session.initialize() 
                    # 1. 獲取工具並轉為 Ollama 格式 
                    mcp_tools = await session.list_tools() 
                    ollama_tools = [{ 
                        "type": "function", 
                        "function": { 
                            "name": t.name, 
                            "description": t.description, 
                            "parameters": t.inputSchema 
                        } 
                    } for t in mcp_tools.tools]

                    _append_log({
                        "timestamp": datetime.now(),
                        "type": "init",
                        "mcp_tools": ollama_tools,
                    })

                    print("tool count:", len(mcp_tools.tools))
                    print([t.name for t in mcp_tools.tools])

                    # 提取可用工具名稱
                    available_tool_names = {t.name for t in mcp_tools.tools}

                    # 2. 獲取memory與System Prompt
                    system_prompt = build_system_prompt()
                    
                    messages = [{"role": "system", "content": system_prompt}]
                    
                    # 3. 開始迴圈 
                    print("Agent started. Type 'exit' to quit.\n")
                    
                    while True:
                        user_input = await asyncio.to_thread(input, "You > ")
                        if user_input.strip().lower() == "exit":
                            break
                        
                        user_message = {"role": "user", "content": user_input}
                        messages.append(user_message)
                        
                        # 開始 ReAct 迴圈 
                        # 初始化本輪的執行歷史
                        executed_tools: set[str] = set()
                        failed_tools: set[str] = set()
                        llm_failed = False
                        successful_tool_result_text = ""
                
                        for _ in range(MAX_TOOL_LOOPS):
                    
                            # A. 執行階段：強制調用工具
                            # 構建傳給 LLM 的訊息，包含動態警告
                            messages_for_llm = _dedupe_consecutive_messages(messages)
                            warning = _build_dynamic_warning(executed_tools, failed_tools, available_tool_names)
                            if warning:
                                messages_for_llm.append({"role": "system", "content": warning})

                            # Call ollama.chat (support sync or async implementations) and log request/response
                            print(f"> 思考中...")
                            request_payload = {
                                "model": MODEL,
                                "messages": messages_for_llm,
                                "tools": "ollama_tools_summary"
                            }
                            start = time.perf_counter()
                            try:
                                raw_response = ollama.chat(
                                    model=MODEL,
                                    messages=messages_for_llm,
                                    tools=ollama_tools,
                                    options={"temperature": 0.1},
                                    format='json',
                                )
                                if inspect.isawaitable(raw_response):
                                    raw_response = await raw_response
                                end = time.perf_counter()
                                # log the call (raw_response may be a ChatResponse object)
                                log_llm_call(request_payload, response=raw_response, start=start, end=end)
                                # Normalize response to a dict-like shape for downstream code
                                response = _normalize_chat_response(raw_response)
                            except Exception as e:
                                end = time.perf_counter()
                                log_llm_call(request_payload, response=None, error=e, start=start, end=end)
                                # Handle common Ollama errors gracefully (e.g., model not found)
                                msg = str(e).lower()
                                if "model" in msg and "not found" in msg:
                                    print(f"LLM error: {e}. Please check MODEL setting: {MODEL}")
                                    llm_failed = True
                                    break
                                raise
                
                            # B. 解析模型輸出並透過 MCP 執行
                            assistant_message = _append_assistant_message(messages, response)
                            model_thought = assistant_message.get('content', '')
                            if model_thought:
                                print(f"> 模型思考: {model_thought}")
                            tool_calls = response.get('message', {}).get('tool_calls', []) 
                            if not tool_calls:
                                content = assistant_message.get("content")
                                parsed_tool_call = _extract_tool_call_from_content(content)
                                if parsed_tool_call is not None:
                                    tool_calls = [parsed_tool_call]
                                    assistant_message["tool_calls"] = tool_calls
                                    messages[-1] = assistant_message
                            
                            if tool_calls: 
                                last_tool_text = ""
                                for call in tool_calls: 
                                    tool_name = call['function']['name'] 
                                    tool_args = call['function']['arguments'] 
                                    
                                    # 檢查工具是否存在
                                    if tool_name not in available_tool_names:
                                        tool_text = f"ERROR: Tool '{tool_name}' does not exist. Available tools: {', '.join(sorted(available_tool_names))}"
                                        print(f"> 工具不存在: {tool_name}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Tool does not exist")
                                        _append_tool_message(messages, call, tool_text)
                                        executed_tools.add(f"{tool_name}(invalid)")
                                        last_tool_text = tool_text
                                        continue

                                    # 檢查工具是否已失敗
                                    if tool_name in failed_tools:
                                        tool_text = f"SKIP: Tool '{tool_name}' previously failed. Do not retry."
                                        print(f"> 跳過已失敗的工具: {tool_name}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Tool already failed")
                                        _append_tool_message(messages, call, tool_text)
                                        executed_tools.add(f"{tool_name}(skip)")
                                        last_tool_text = tool_text
                                        continue

                                    # 記錄執行
                                    tool_key = f"{tool_name}"
                                    executed_tools.add(tool_key)
                                    
                                    print(f"> 正在執行工具: {tool_name}...") 
                                    
                                    # 透過 MCP Session 執行 
                                    try:
                                        result = await session.call_tool(
                                            tool_name,
                                            arguments=tool_args,
                                        )
                                        tool_text = tool_result_to_text(result)
                                        log_tool_call(tool_name, tool_args, result=result)
                                    except anyio.BrokenResourceError as e:
                                        tool_text = f"Tool execution failed due to broken MCP connection: {e}"
                                        log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                        failed_tools.add(tool_name)
                                        raise
                                    except Exception as e:
                                        tool_text = f"Tool execution failed: {e}"
                                        log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                        failed_tools.add(tool_name)
                                    _append_tool_message(messages, call, tool_text)
                                    last_tool_text = tool_text

                                successful_tool_result_text = last_tool_text
                                break
                            
                            else: 
                                direct_text = str(assistant_message.get('content', ''))
                                print_streaming(direct_text)
                                append_memory_summary(
                                    MEMORY_PATH,
                                    _build_turn_summary(
                                        user_input=user_input,
                                        assistant_text=direct_text,
                                    ),
                                )
                                break
                        else:
                            print("> Agent 已達工具呼叫上限，為避免無限迴圈而停止。")

                        if llm_failed:
                            # 回到使用者輸入循環，讓使用者修正模型設定或重試
                            continue

                        if successful_tool_result_text:
                            final_messages = _dedupe_consecutive_messages(messages)
                            final_messages.append({
                                "role": "system",
                                "content": _build_final_answer_prompt(successful_tool_result_text),
                            })
                            final_request = {
                                "model": MODEL,
                                "messages": final_messages,
                                "tools": "disabled",
                            }
                            start_final = time.perf_counter()
                            final_report = ollama.chat(
                                model=MODEL,
                                messages=final_messages,
                                options={"temperature": 0.7},
                            )
                            if inspect.isawaitable(final_report):
                                final_report = await final_report
                            end_final = time.perf_counter()
                            log_llm_call(final_request, response=final_report, start=start_final, end=end_final)
                            final_report = _normalize_chat_response(final_report)
                            final_text = str(final_report.get('message', {}).get('content', ''))
                            print_streaming(final_text)
                            append_memory_summary(
                                MEMORY_PATH,
                                _build_turn_summary(
                                    user_input=user_input,
                                    assistant_text=final_text,
                                    tool_text=successful_tool_result_text,
                                ),
                            )
                            continue
        except anyio.BrokenResourceError as e:
            print("MCP connection broken, reconnecting in 2s...", e)
            try:
                _append_log({"timestamp": datetime.now(), "type": "error", "error": str(e)})
            except Exception:
                pass
            await asyncio.sleep(2)
            continue
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("> Agent stopped.")
            return
                
                
if __name__ == "__main__":
    # Windows 事件避免首次執行時的異步 IO 問題
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
    asyncio.run(run_mcp_agent())