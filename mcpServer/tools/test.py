import xml.etree.ElementTree as ET
import os
import urllib.request


def search_online(
    query: str,
    limit: int = 10
):
    """注意：此工具只會回傳搜尋條件。"""
    import json
    import urllib.parse
    import urllib.request

    search_result = ''

    # 1. 設定 DuckDuckGo 免金鑰 API 參數
    # format=json: 要求回傳 JSON 格式
    # no_redirect=1: 避免直接重導向到官網
    params = {"q": query, "format": "json", "no_redirect": 1}

    # 2. 組裝網址
    encoded_params = urllib.parse.urlencode(params)
    url = f"https://api.duckduckgo.com/?{encoded_params}"

    try:
        # 4. 發送 HTTP GET 請求
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )  # 加上 User-Agent 模擬瀏覽器

        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))

            # 5. 提取核心摘要
            search_result += f"# {query}的定義: \n"
            abstract = data.get("AbstractText")
            if abstract:
                search_result += f"{abstract}\n"
            else:
                search_result += "查詢不到直接定義。\n"
            search_result += f'## Websites: \n'

            # 6. 提取相關結果列表（限定前 10 筆）
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
                    print("沒有找到相關衍生結果。")

    except Exception as e:
        print("請求發生錯誤：", e)

    return search_result + str(websites)

import webbrowser
url= "https://www.google.com"
webbrowser.open(url.strip())
print(f"已成功使用瀏覽器完成打開網址: {url}")