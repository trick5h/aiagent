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

@mcp.tool()
def search_online(
    query: str = Field(description="搜尋關鍵字"),
    limit: int = Field(default=5, description="回傳結果的數量上限")
):
    """使用網路搜尋引擎搜尋相關資訊。會給出搜尋到的摘要與網站的網址。"""

    search_result = ''

    # 1. 設定 DuckDuckGo 免金鑰 API 參數
    # format=json: 要求回傳 JSON 格式
    # no_redirect=1: 避免直接重導向到官網
    params = {"q": query, "format": "json", "no_redirect": 1}

    # 2. 組裝網址
    encoded_params = urllib.parse.urlencode(params)
    url = f"https://api.duckduckgo.com/?{encoded_params}"

    try:
        # 3. 發送 HTTP GET 請求
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )  # 加上 User-Agent 模擬瀏覽器

        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))

            # 4. 提取核心摘要
            search_result += f"# {query}的定義: \n"
            abstract = data.get("AbstractText")
            if abstract:
                search_result += f"{abstract}\n"
            else:
                search_result += "目前查詢不到摘要定義。\n"
            search_result += f'## Websites: \n'

            # 5. 提取相關結果列表
            related_topics = data.get("RelatedTopics", [])

            count = 0
            websites={}
            for item in related_topics:
                if count >= limit:  # 嚴格限制最多 10 筆
                    break

                # 確保該項目是包含說明的字典（排除分類群組）
                if "Text" in item and "FirstURL" in item:
                    count += 1
                    text = item.get("Text")
                    link = item.get("FirstURL")
                    websites[text] = link

                if count == 0:
                    search_result += "沒有找到相關衍生結果。"

    except Exception as e:
        return f"請求發生錯誤：{e}"

    return search_result + str(websites)



@mcp.tool()
def open_url(url: str = Field(description="網址")):
    """用系統預設瀏覽器來打開指定網址。"""
    webbrowser.open(url.strip())
    
    return f"已成功使用瀏覽器完成打開網址: {url}"