from server import mcp
import tools.user_tools  # 匯入後，工具會自動註冊到 mcp 實例
import tools.system_tools

if __name__ == "__main__":
    mcp.run() # 啟動單一伺服器，包含所有工具