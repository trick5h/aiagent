import asyncio 
from mcp import ClientSession, StdioServerParameters 
from mcp.client.stdio 
import stdio_client 
import ollama 
import json 

# =========================
# Config
# =========================

MODEL = "qwen2.5-coder:3b"
SERVER_COMMAND = "python"          # or "python3"
SERVER_PATH = Path("mcpServer/main.py")        # your FastMCP server
SOUL_PATH = Path("SOUL.md")
MEMORY_PATH = Path("MEMORY.json")
MAX_TOOL_LOOPS = 8

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


def build_system_prompt(tools_prompt: str) -> str:
    soul = load_soul()
    return f"""\
{soul}

# Tool Usage Rules
- When a tool is needed, call it with .json format.
- Do not invent tool results.
"""


# =========================
# Main Agent
# =========================

async def run_mcp_agent(): 
    # A. 設定如何啟動你的 Server (stdio 模式) 
    server_params = StdioServerParameters( command="python", # 或是 "python3" 
    args=SERVER_PATH, # 你的 FastMCP 程式碼檔案 
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
            system_prompt = build_system_prompt(tools_prompt)
            
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
                    response = await ollama.chat( 
                        model=MODEL, 
                        messages=messages, 
                        tools=ollama_tools, 
                        format='json' # 物理級別強制 JSON 
                    ) 
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
                        final_report = ollama.chat( 
                            model=MODEL, 
                            messages=[
                                user_message,
                                {'role': 'system', 'content': 'Briefly explain the MCP tool execution result to user.'}, 
                                {'role': 'assistant', 'content': f"Tool result: {result.content}"} 
                            ] 
                        ) 
                        print(f"Agent 執行並回覆: {final_report['message']['content']}")
                        break
                    
                    else: 
                        print(f"Agent 直接回覆: {response['message']['content']}")
                        break
                
                
if __name__ == "__main__": 
    asyncio.run(run_mcp_agent())