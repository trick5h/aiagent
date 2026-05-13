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
import time
import traceback
import warnings

# 隱藏所有過時警告
warnings.filterwarnings("ignore", category=DeprecationWarning)


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
SESSION_LOG_HEADER = "## Session Summary Log"
SESSION_MEMORY_LIMIT = 5
# 用於快速判斷是否為元問題的輕量分類器（可替換為更小的本地模型）
SMALL_MODEL = MODEL  # 當前環境預設使用同模型，視情況替換為更小模型


# =========================
# Tools Determination
# =========================

async def is_user_query_needs_tools(user_input: str, tool_result: str | None) -> bool:
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
    1. If the question is general and does not explicitly require specific data: output NO.
    2. If the data contains the answer: Output NO.
    3. If the data is not related to the question or missing key fields needed for the answer: Output YES.
    4. If you are not sure if the data contains the answer, lean towards YES to allow tool usage.

    Does it need MORE tool calls? Answer only YES or NO."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"User Question: {user_input}\n\nCurrent Tool Result: {tool_result}"},
    ]

    print(f"> [Debug] 判斷是否需要工具，問題: {user_input}, 工具結果: {tool_result}")
    try:
        resp = ollama.chat(
            model=SMALL_MODEL,
            messages=messages,
            options={"temperature": 0.1},
        )
        if inspect.isawaitable(resp):
            resp = await resp
        resp = _normalize_chat_response(resp)
        content = str(resp.get('message', {}).get('content', '')).strip().upper()
        if content.startswith('Y'):
            return True
        if content.startswith('N'):
            return False
    except Exception:
        return False
    return False


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
            + "\n\nBefore calling any tool, ask: does this tool directly help solve the user's current question? If not, do not call it. Do NOT call failed tools. Do NOT repeat the same tool with identical parameters."
        )
    return ""


def _build_final_answer_prompt(tool_result_text: str) -> str:
    return (
        "# FINAL ANSWER MODE - RESPOND IN NATURAL LANGUAGE ONLY\n"
        "==== IMPORTANT ====\n"
        "You MUST respond with ONLY natural language text. There are NO tools available in this mode.\n"
        "Do NOT output JSON, do NOT attempt to call tools, do NOT use any special formatting.\n"
        "==== END INSTRUCTIONS ====\n\n"
        f"Tool result obtained:\n{tool_result_text}\n\n"
        "TASK: Analyze the above result and provide a DIRECT, NATURAL-LANGUAGE answer to the user's original question.\n"
        "REQUIREMENTS:\n"
        "- Response MUST be ONLY natural language\n"
        "- MUST directly answer the user's question using the result above\n"
        "- MUST NOT output JSON, code, or any structured format\n"
        "- MUST NOT attempt to call any tools or functions\n"
        "- Keep answer concise and relevant to the question"
    )


def _build_turn_summary(user_input: str, assistant_text: str, tool_text: str = "") -> str:
    summary_source = assistant_text.strip() or tool_text.strip() or user_input.strip()
    summary_source = " ".join(summary_source.split())
    if len(summary_source) > 120:
        summary_source = summary_source[:200] + "..."
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




def is_shell_noise_input(text: str) -> bool:
    normalized = " ".join(text.split()).lower()
    if not normalized:
        return True
    return (
        "set-executionpolicy" in normalized
        and "activate.ps1" in normalized
    ) or normalized.startswith("(& ") and "activate" in normalized



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
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "type": "init",
                        "mcp_tools": ollama_tools,
                    })

                    if len(mcp_tools.tools) > 0:
                        print(">>>>>>> MCP Server:", len(mcp_tools.tools), "Tools successfully initialized. \n")
                        #print([t.name for t in mcp_tools.tools])

                    # 提取可用工具名稱和描述
                    available_tool_names = {t.name for t in mcp_tools.tools}
                    tool_descriptions = {t.name: t.description for t in mcp_tools.tools}

                    # 2. 獲取memory與System Prompt
                    system_prompt = build_system_prompt()
                    
                    messages = [{"role": "system", "content": system_prompt}]
                    
                    # 3. 開始迴圈 
                    print("Agent started. Type 'exit' to quit.\n")
                    input_eof_retries = 0
                    max_input_eof_retries = 3
                    input_eof_retry_delay_seconds = 0.5
                    
                    while True:
                        try:
                            user_input = input("You > ")
                        except EOFError:
                            input_eof_retries += 1
                            if input_eof_retries < max_input_eof_retries:
                                print(f"Loading...")
                                time.sleep(input_eof_retry_delay_seconds)
                                continue
                            print("> Error: Terminal input repeatedly, exiting.")
                            break
                        except KeyboardInterrupt:
                            print("\n> Interrupted by user, exiting.")
                            break
                        except Exception as e:
                            print(f"> Error reading input: {e}")
                            _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"input error: {e}"})
                            break

                        input_eof_retries = 0

                        if is_shell_noise_input(user_input):
                            continue

                        if user_input.strip().lower() == "exit":
                            return
                        
                        user_message = {"role": "user", "content": user_input}
                        messages.append(user_message)
                        # Quick heuristic: decide whether this user input needs tools
                        needs_tools = await is_user_query_needs_tools(user_input, tool_result='')
                        print(f"> [Debug] 需要工具: {needs_tools}")

                        if not needs_tools:
                            # Directly ask the model (no tools) for natural language answer
                            final_messages = [
                                {"role": "system", "content": build_system_prompt()},
                                {"role": "user", "content": user_input},
                            ]
                            final_request = {"model": MODEL, "messages": final_messages}
                            try:
                                final_report = ollama.chat(
                                    model=MODEL,
                                    messages=final_messages,
                                    options={"temperature": 0.7},
                                )
                                log_llm_call(final_request, response=final_report)
                                if inspect.isawaitable(final_report):
                                    final_report = await final_report
                                final_report = _normalize_chat_response(final_report)
                                final_text = str(final_report.get('message', {}).get('content', '')).strip()
                                print_streaming(final_text)
                                append_memory_summary(
                                    MEMORY_PATH,
                                    _build_turn_summary(
                                        user_input=user_input,
                                        assistant_text=final_text,
                                    ),
                                )
                            except Exception as e:
                                print(f"> 快速回答失敗，將進入工具流程: {e}")
                                _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": str(e)})
                            continue
                        
                        # 開始 ReAct 迴圈 
                        # 初始化本輪的執行歷史
                        executed_tool_calls: set[str] = set()  # 記錄「工具名+參數」組合，防止完全重複的調用
                        failed_tools: set[str] = set()
                        llm_failed = False
                        successful_tool_result_text = ""
                        observation_available = False  # 當有工具結果可用時，下一輪引導模型直接回答
                        skip_final_answer = False
                
                        for _ in range(MAX_TOOL_LOOPS):
                    
                            # 如果已有觀察結果，立即進入最終答案生成階段
                            if observation_available:
                                break
                    
                            # A. 執行階段：強制調用工具
                            # 構建傳給 LLM 的訊息，包含動態警告
                            messages_for_llm = _dedupe_consecutive_messages(messages)
                            warning = _build_dynamic_warning(executed_tool_calls, failed_tools, available_tool_names)
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
                                # 如果已有可觀察到的工具結果，禁用工具強制模型直接回答
                                if observation_available:
                                    messages_for_llm.append({"role": "system", "content": _build_final_answer_prompt(successful_tool_result_text)})
                                    # 禁用工具，強制基於現有觀察直接回答
                                    raw_response = ollama.chat(
                                        model=MODEL,
                                        messages=messages_for_llm,
                                        options={"temperature": 0.1},
                                    )
                                else:
                                    # 沒有觀察結果，保持工具啟用以允許鏈式調用
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
                                # observation_available 會在後續解析回應內容後（若無 tool_calls）被清除。
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
                                last_tool_name = ""  # Track last executed tool
                                has_successful_execution = False
                                for call in tool_calls: 
                                    tool_name = call['function']['name'] 
                                    tool_args = call['function']['arguments'] 
                                    
                                    # 檢查工具是否存在
                                    if tool_name not in available_tool_names:
                                        tool_text = f"ERROR: Tool '{tool_name}' does not exist. Available tools: {', '.join(sorted(available_tool_names))}"
                                        print(f"> 工具不存在: {tool_name}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Tool does not exist")
                                        _append_tool_message(messages, call, tool_text)
                                        # 不記錄無效工具
                                        last_tool_text = tool_text
                                        continue

                                    # 檢查工具是否已失敗
                                    if tool_name in failed_tools:
                                        tool_text = f"SKIP: Tool '{tool_name}' previously failed. Do not retry."
                                        print(f"> 跳過已失敗的工具: {tool_name}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Tool already failed")
                                        _append_tool_message(messages, call, tool_text)
                                        # 不記錄已失敗的工具
                                        last_tool_text = tool_text
                                        continue


                                    # 檢查是否已用相同參數執行過此工具 (防止完全相同的調用)
                                    tool_call_key = f"{tool_name}({json.dumps(tool_args, sort_keys=True)})"
                                    if tool_call_key in executed_tool_calls:
                                        tool_text = f"SKIP: Tool '{tool_name}' with identical arguments already executed. Do not repeat the exact same call."
                                        print(f"> 跳過完全相同的工具調用: {tool_name}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Identical tool call already executed")
                                        _append_tool_message(messages, call, tool_text)
                                        last_tool_text = tool_text
                                        continue

                                    # 記錄執行此工具呼叫組合
                                    executed_tool_calls.add(tool_call_key)
                                    
                                    print(f"> 正在執行工具: {tool_name}...") 
                                    
                                    # 透過 MCP Session 執行 (with timeout protection)
                                    try:
                                        # 若遇到 asyncio.CancelledError，代表底層會話或子程序可能在啟動階段被取消
                                        # 我們嘗試重試幾次，以降低因 race condition 導致的單次失敗
                                        max_cancel_retries = 3
                                        cancel_attempt = 0
                                        result = None
                                        while True:
                                            try:
                                                result = await asyncio.wait_for(
                                                    session.call_tool(
                                                        tool_name,
                                                        arguments=tool_args,
                                                    ),
                                                    timeout=60  # 60 second timeout per tool
                                                )
                                                break
                                            except Exception as e:
                                                cancel_attempt += 1
                                                tb = traceback.format_exc()
                                                tool_text = f"Tool call cancelled (attempt {cancel_attempt}/{max_cancel_retries}): {type(e).__name__}: {e}"
                                                print(f"> {tool_text}")
                                                log_tool_call(tool_name, tool_args, result=tool_text, error=tb)
                                                if cancel_attempt >= max_cancel_retries:
                                                    # 轉為 BrokenResourceError，觸發外層重連機制
                                                    raise anyio.BrokenResourceError(f"call_tool cancelled repeatedly: {e}")
                                                await asyncio.sleep(0.5)

                                        tool_text = tool_result_to_text(result)
                                        log_tool_call(tool_name, tool_args, result=result)
                                        if tool_text:
                                            print(f"> 工具結果: {tool_text}")
                                        has_successful_execution = True
                                        last_tool_name = tool_name  # Record which tool succeeded
                                    except asyncio.TimeoutError:
                                        tool_text = f"Tool execution timeout (60s): {tool_name}"
                                        print(f"> {tool_text}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Timeout")
                                        failed_tools.add(tool_name)
                                    except anyio.BrokenResourceError as e:
                                        tool_text = f"Tool execution failed due to broken MCP connection: {e}"
                                        log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                        failed_tools.add(tool_name)
                                        print(f"> MCP 連接已斷開，將重新連接...")
                                        raise  # Re-raise to trigger outer reconnection logic
                                    except Exception as e:
                                        tool_text = f"Tool execution failed: {type(e).__name__}: {e}"
                                        print(f"> 工具執行失敗: {tool_text}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                        failed_tools.add(tool_name)
                                    _append_tool_message(messages, call, tool_text)
                                    last_tool_text = tool_text

                                # 只有在執行擁有足夠資訊的工具時，才標記 observation 可用
                                if has_successful_execution:
                                    successful_tool_result_text = last_tool_text
                                    print(f"> [Debug] 成功的工具結果: {successful_tool_result_text}")
                                    # 智能判斷此工具數據是否需要下一輪工具調用
                                    tool_needed = await is_user_query_needs_tools(user_input, successful_tool_result_text)
                                    print(f"> [Debug] 需要工具: {tool_needed}")
                                    if not tool_needed:
                                        observation_available = True
                                    else:
                                        observation_available = False
                            
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
                                # 已收到最終自然語言回答，清除 observation 標記
                                observation_available = False
                                break
                        else:
                            print("> Agent 已達工具呼叫上限，為避免無限迴圈而停止。")
                            # 達到迴圈限制，強制進行最終答案生成（如果有成功的工具結果）
                            if successful_tool_result_text:
                                observation_available = True

                        if llm_failed:
                            # 回到使用者輸入循環，讓使用者修正模型設定或重試
                            continue

                        if skip_final_answer:
                            append_memory_summary(
                                MEMORY_PATH,
                                _build_turn_summary(
                                    user_input=user_input,
                                    assistant_text=successful_tool_result_text,
                                    tool_text=successful_tool_result_text,
                                ),
                            )
                            continue

                        if successful_tool_result_text:
                            # 為最終答案生成構建乾淨的訊息歷史（移除工具相關內容，只保留用戶和最終觀察）
                            final_messages = [
                                {"role": "system", "content": build_system_prompt()},
                                {"role": "user", "content": user_input},
                                {
                                    "role": "system",
                                    "content": _build_final_answer_prompt(successful_tool_result_text),
                                },
                            ]
                            final_request = {
                                "model": MODEL,
                                "messages": final_messages,
                            }
                            start_final = time.perf_counter()
                            try:
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
                                final_text = str(final_report.get('message', {}).get('content', '')).strip()
                                
                                # 如果模型仍然輸出JSON，使用工具結果代替
                                if final_text.startswith('{') and final_text.endswith('}'):
                                    final_text = successful_tool_result_text
                                
                                print_streaming(final_text)
                                append_memory_summary(
                                    MEMORY_PATH,
                                    _build_turn_summary(
                                        user_input=user_input,
                                        assistant_text=final_text,
                                        tool_text=successful_tool_result_text,
                                    ),
                                )
                            except Exception as e:
                                end_final = time.perf_counter()
                                log_llm_call(final_request, response=None, error=e, start=start_final, end=end_final)
                                print(f"> 最終回答生成失敗: {type(e).__name__}: {e}")
                                print_streaming(successful_tool_result_text)
                                append_memory_summary(
                                    MEMORY_PATH,
                                    _build_turn_summary(
                                        user_input=user_input,
                                        assistant_text=successful_tool_result_text,
                                        tool_text=successful_tool_result_text,
                                    ),
                                )
                            continue
        except anyio.BrokenResourceError as e:
            print("MCP connection broken, reconnecting in 2s...", e)
            try:
                _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": str(e)})
            except Exception:
                pass
            await asyncio.sleep(2)
            continue
        except KeyboardInterrupt:
            print("> Agent stopped by user.")
            return
        except (asyncio.CancelledError, EOFError) as e:
            print(f"> Agent stopped: {type(e).__name__}")
            try:
                _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent stop: {type(e).__name__}: {str(e)}"})
            except Exception:
                pass
            return
        except ExceptionGroup as eg:
            # 捕捉 TaskGroup 中未處理的多重例外，逐一記錄細節但讓 agent 繼續重啟循環
            try:
                print(f"> Agent encountered ExceptionGroup with {len(eg.exceptions)} sub-exception(s). Logging and continuing...")
            except Exception:
                print("> Agent encountered ExceptionGroup; logging and continuing...")
            try:
                details = []
                for idx, sub in enumerate(eg.exceptions, start=1):
                    tb = "".join(traceback.format_exception(type(sub), sub, getattr(sub, '__traceback__', None)))
                    details.append({
                        "index": idx,
                        "type": type(sub).__name__,
                        "error": str(sub),
                        "traceback": tb,
                    })
                _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "exception_group", "count": len(eg.exceptions), "sub_exceptions": details})
            except Exception as e2:
                try:
                    _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"failed logging ExceptionGroup: {e2}"})
                except Exception:
                    pass
            # 等待並繼續外層重連循環
            await asyncio.sleep(2)
            continue
        except Exception as e:
            print(f"> Agent crashed: {type(e).__name__}: {e}")
            try:
                _append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent crash: {type(e).__name__}: {e}"})
            except Exception:
                pass
            return
                
                
if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore # For Windows compatibility
    except Exception as e:
        print(f"> Failed to set event loop policy: {e}")
    asyncio.run(run_mcp_agent())