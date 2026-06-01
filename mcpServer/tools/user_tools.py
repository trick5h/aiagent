from ddgs import DDGS

from server import mcp
from pydantic import Field

import json
import urllib.parse
import urllib.request
import webbrowser
import os
import sys

project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
import config

@mcp.tool()
def read_file(path: str = Field(description="檔案路徑")):
    """根據路徑讀取檔案內容。"""
    if ':' not in path or path.startswith('/'):
        path = os.path.join(config.WORKSPACE_DIR, path)
    with open(path, 'r', encoding='utf-8') as file:
        content = file.read()
    return f'"{path}" 的檔案內容:\n{content}'

@mcp.tool()
def set_volume(
    level: int = Field(ge=0, le=100, description="音量大小") # ge: 大於等於, le: 小於等於 (沒有設定 default 值，欄位會被列入「必要參數」)
):
    """這是測試調整音量大小。"""
    return level
'''
@mcp.tool()
def search_online(
    query: str = Field(description="搜尋關鍵字"),
):
    """使用網路搜尋引擎搜尋相關資訊。會給出搜尋到的網站標題、網址與摘要。"""
    
    search_result = f" {query}的搜尋結果為:\n"

    try:
        with DDGS() as ddgs:
            data = [r for r in ddgs.text(query, max_results=5)]
            
            if not data:
                return "沒有找到相關結果。"

            websites = []
            for r in data:
                website={}
                website['title'] = str(r['title'])
                website['url'] = str(r['href'])
                website['summary'] = str(r['body'])
                websites.append(website)

    except Exception as e:
        return f"請求發生錯誤：{e}"

    return search_result + str(websites)



@mcp.tool()
def open_url(url: str = Field(description="網址")):
    """用系統預設瀏覽器來打開指定網址。"""
    webbrowser.open(url.strip())
    
    return f"已成功使用瀏覽器完成打開網址: {url}"
'''