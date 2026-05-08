from server import mcp
from pydantic import Field

@mcp.tool()
def get_user_name(user_id: int = Field(description="員工編號")):
    """根據編號查詢姓名。"""
    return "張小明"

@mcp.tool()
def set_volume(
    level: int = Field(ge=0, le=100, description="音量大小") # ge: 大於等於, le: 小於等於
):
    """測試。"""
    """沒有設定 default 值，它會自動被列入「必要項目」"""
    return level

@mcp.tool()
def search(
    query: str,
    limit: int = Field(default=10, description="回傳結果數量")
):
    """注意：此工具會回傳該搜尋條件。"""
    return "Test:" + query
