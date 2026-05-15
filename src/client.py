import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from dataclasses import dataclass
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import SERVERS
from src.logger import append_log


@dataclass
class MCPConnectionBundle:
    all_ollama_tools: list[dict]
    available_tool_names: set[str]
    tool_to_server: dict[str, str]
    server_sessions: dict[str, ClientSession]

    def session_for_tool(self, tool_name: str) -> ClientSession | None:
        server_name = self.tool_to_server.get(tool_name)
        if server_name is None:
            return None
        return self.server_sessions.get(server_name)


@asynccontextmanager
async def connect_all_mcp_servers():
    async with AsyncExitStack() as exit_stack:
        bundle = MCPConnectionBundle(
            all_ollama_tools=[],
            available_tool_names=set(),
            tool_to_server={},
            server_sessions={},
        )

        async def connect_server(server_name: str, server_params: StdioServerParameters) -> None:
            try:
                read, write = await exit_stack.enter_async_context(stdio_client(server_params))
                session = await exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                mcp_tools = await session.list_tools()
                ollama_tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.inputSchema,
                        },
                    }
                    for t in mcp_tools.tools
                ]

                bundle.all_ollama_tools.extend(ollama_tools)
                bundle.server_sessions[server_name] = session

                for tool in mcp_tools.tools:
                    bundle.available_tool_names.add(tool.name)
                    previous_server = bundle.tool_to_server.get(tool.name)
                    if previous_server is None:
                        bundle.tool_to_server[tool.name] = server_name
                    elif previous_server != server_name:
                        print(
                            f"> [Warning] 工具名稱重複: {tool.name} 同時出現在 {previous_server} 與 {server_name}，將保留前者。"
                        )

                append_log(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "type": f"init_{server_name}",
                        "mcp_tools": ollama_tools,
                    }
                )
            except Exception as e:
                print(f"連線到伺服器 {server_name} 失敗: {e}")

        async with asyncio.TaskGroup() as tg:
            for name, params in SERVERS.items():
                tg.create_task(connect_server(name, params))

        yield bundle