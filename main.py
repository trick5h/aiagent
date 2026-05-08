import asyncio
from pathlib import Path 
from mcp import ClientSession, StdioServerParameters 
from mcp.client.stdio import stdio_client 
import ollama 
import json
import inspect
from typing import Any 
import time
import uuid
from datetime import datetime

# =========================
# Config
# =========================

MODEL = "qwen2.5-coder:3b"
SERVER_COMMAND = "python"          # or "python3"
SERVER_PATH = Path("mcpServer/server.py")        # your FastMCP server
SOUL_PATH = Path("SOUL.md")
MEMORY_PATH = Path("MEMORY.json")
MAX_TOOL_LOOPS = 8
LOG_PATH = Path(__file__).resolve().parent / "logs.jsonl"

# =========================
# Memory
# =========================

def load_memory(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_memory(path: Path, messages: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
    return f"""\
{soul}

# Tool Usage Rules
- When a tool is needed, call it with .json format.
- Do not invent tool results.
"""


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


def log_llm_call(call_id: str, request: dict, response: Any = None, error: Any = None, start: float | None = None, end: float | None = None) -> None:
    entry: dict = {
        "id": call_id,
        "timestamp": datetime.now(),
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

# =========================
# Main Agent
# =========================

async def run_mcp_agent(): 
    # A. 設定如何啟動你的 Server (stdio 模式) 
    server_params = StdioServerParameters(
        command="python", # 或是 "python3" 
        args=[str(SERVER_PATH)], # 你的 FastMCP 程式碼檔案 
    ) 
    # B. 建立連線 
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
            
            
            # 2. 獲取memory與System Prompt
            system_prompt = build_system_prompt()
            
            messages = load_memory(MEMORY_PATH)
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": system_prompt})
            else:
                messages[0] = {"role": "system", "content": system_prompt}

            save_memory(MEMORY_PATH, messages)
            
            # 3. 開始迴圈 
            print("Agent started. Type 'exit' to quit.\n")
            
            while True:
                user_input = await asyncio.to_thread(input, "You > ")
                if user_input.strip().lower() == "exit":
                    break
                
                user_message = {"role": "user","content": user_input,}
                messages.append(user_message)
                save_memory(MEMORY_PATH, messages)
                
                # 開始迴圈 
                for _ in range(MAX_TOOL_LOOPS):
            
                    # A. 執行階段：強制調用工具
                    # Call ollama.chat (support sync or async implementations) and log request/response
                    call_id = str(uuid.uuid4())
                    request_payload = {
                        "model": MODEL,
                        "messages": messages,
                        "tools": "ollama_tools_summary"
                    }
                    start = time.perf_counter()
                    try:
                        raw_response = ollama.chat(
                            model=MODEL,
                            messages=messages,
                            tools=ollama_tools,
                            format='json',
                        )
                        if inspect.isawaitable(raw_response):
                            raw_response = await raw_response
                        end = time.perf_counter()
                        # log the call (raw_response may be a ChatResponse object)
                        log_llm_call(call_id, request_payload, response=raw_response, start=start, end=end)
                        # Normalize response to a dict-like shape for downstream code
                        response = _normalize_chat_response(raw_response)
                    except Exception as e:
                        end = time.perf_counter()
                        log_llm_call(call_id, request_payload, response=None, error=e, start=start, end=end)
                        raise
            
                    # B. 解析模型輸出並透過 MCP 執行
                    tool_calls = response.get('message', {}).get('tool_calls', []) 
                    
                    if tool_calls: 
                        for call in tool_calls: 
                            tool_name = call['function']['name'] 
                            tool_args = call['function']['arguments'] 
                            
                            print(f"正在執行工具: {tool_name}...") 
                            
                            # 透過 MCP Session 執行 
                            try:
                                result = await session.call_tool(
                                    tool_name,
                                    arguments=tool_args,
                                )
                                tool_text = tool_result_to_text(result)
                            except Exception as e:
                                tool_text = f"Tool execution failed: {e}"
                            
                        # C. 回報階段：將結果轉成人話 (不傳 tools 參數，省 Token)
                        final_call_id = str(uuid.uuid4())
                        final_messages = [
                            user_message,
                            {'role': 'system', 'content': 'Briefly explain the MCP tool execution result to user.'},
                            {'role': 'assistant', 'content': f"Tool result: {tool_text}"},
                        ]
                        final_request = {"model": MODEL, "messages": final_messages}
                        start_final = time.perf_counter()
                        final_report = ollama.chat(
                            model=MODEL,
                            messages=final_messages,
                        )
                        if inspect.isawaitable(final_report):
                            final_report = await final_report
                        end_final = time.perf_counter()
                        log_llm_call(final_call_id, final_request, response=final_report, start=start_final, end=end_final)
                        final_report = _normalize_chat_response(final_report)
                        print(f"Agent 執行並回覆: {final_report['message'].get('content')}")
                        break
                    
                    else: 
                        print(f"Agent 直接回覆: {response['message'].get('content')}")
                        break
                
                
if __name__ == "__main__": 
    asyncio.run(run_mcp_agent())