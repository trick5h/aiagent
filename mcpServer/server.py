import sys

from fastmcp import FastMCP

# 整個專案共用這一個實例
# Create the MCP instance before importing tools to avoid circular imports
mcp = FastMCP("Team-Server")

# 讓 tools 模組無論用 `import server` 還是以 `__main__` 執行，都引用同一個 mcp 實例。
sys.modules.setdefault("server", sys.modules[__name__])

import tools.user_tools  # 匯入後，工具會自動註冊到 mcp 實例
import tools.system_tools
import tools.sql_tools

if __name__ == "__main__":
    mcp.run()  # 啟動單一伺服器，包含所有工具
