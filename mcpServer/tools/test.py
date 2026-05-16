import json
import xml.etree.ElementTree as ET
import os
import urllib.request

from pydantic import Field
from ddgs import DDGS


def search_online(
    query: str = Field(description="搜尋關鍵字，注意:只能傳入一個英文單詞"),
    limit: int = 5
):
    """使用網路搜尋引擎搜尋相關資訊。會給出搜尋到的網站標題與網址。"""
    search_result = f" {query}的搜尋結果為:\n"

    print (type(limit))

    try:
        with DDGS() as ddgs:
            data = [r for r in ddgs.text(query, max_results=limit)]
            
            if not data:
                return "找不到結果。"

            websites = []
            for r in data:
                #websites[str(r['title'])] = str(r['href'])
                website={}
                website['title'] = str(r['title'])
                website['url'] = str(r['href'])
                website['summary'] = str(r['body'])
                websites.append(website)

            if len(websites) == 0:
                search_result += "沒有找到相關衍生結果。"

    except Exception as e:
        return f"請求發生錯誤：{e}"

    return search_result + str(websites)



def search_ddg(query):
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=5)]
        
        if not results:
            return "找不到結果。"
            
        output = ""
        for r in results:
            output += f"[] {r['title']}\n Website {r['href']}\n Note {r['body']}\n\n"
        return output

print (search_online("Python programming language"))