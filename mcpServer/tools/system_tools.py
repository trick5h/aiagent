from server import mcp
from pydantic import Field

import xml.etree.ElementTree as ET
import psutil
import shutil
import os
import urllib.request
from datetime import datetime

@mcp.tool()
def get_system_health() -> str:
    """查詢當前電腦的 CPU 使用率與磁碟剩餘空間。"""
    cpu_usage = psutil.cpu_percent(interval=1)
    total, used, free = shutil.disk_usage("/")
    
    return (
        f"CPU 使用率: {cpu_usage}%\n"
        f"磁碟空間: 已用 {used // (2**30)}GB / 剩餘 {free // (2**30)}GB"
    )

#======================================================
# 定義 RDL 存放目錄
WORKSPACE_DIR = "D:/AiAgent/workspace"
#======================================================

@mcp.tool()
def analyze_report_params(report_name: str = Field(description=".rdl檔案名稱")) -> str:
    """
    讀取指定的 RDL 檔案並回傳它需要的參數清單。
    例如輸入 'Sales_Monthly'，會回傳該報表需要的日期、地區等參數。
    """
    file_path = os.path.join(WORKSPACE_DIR, f"{report_name}.rdl")
    if not os.path.exists(file_path):
        return f"錯誤：找不到報表檔案 {report_name}"

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        # RDL 的 XML namespace 通常較複雜，這裡簡化處理
        ns = {'rdl': 'http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition'}
        
        params = []
        # 尋找 ReportParameters 節點
        for param in root.findall(".//rdl:ReportParameter", ns):
            p_name = param.get("Name")
            data_type_node = param.find("rdl:DataType", ns)
            p_type = data_type_node.text if data_type_node is not None and data_type_node.text is not None else "Unknown"
            params.append(f"- {p_name} ({p_type})")
        
        if not params:
            return f"報表 {report_name} 不需要任何參數。"
        return f"報表 '{report_name}' 需要以下參數：\n" + "\n".join(params)
    
    except Exception as e:
        return f"解析報表時出錯: {str(e)}"

@mcp.tool()
def analyze_report_data(report_name: str = Field(description=".rdl檔案名稱")) -> str:
    """
    解析指定 RDL 檔案中的 Dataset，回傳該報表包含的所有資料欄位名稱。
    這有助於了解報表輸出的數據結構。
    """
    # 確保副檔名正確
    if not report_name.endswith(".rdl"):
        report_name += ".rdl"
        
    file_path = os.path.join(WORKSPACE_DIR, report_name)
    
    if not os.path.exists(file_path):
        return f"錯誤：在路徑 {WORKSPACE_DIR} 找不到報表檔案 '{report_name}'。"

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # RDL 使用 XML 命名空間，通常需要定義 ns 才能精準抓取
        # 這裡涵蓋了常見的 RDL 命名空間版本
        ns = {'rdl': 'http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition',
              'rdl_old': 'http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition'}
        
        report_structure = []
        
        # 尋找所有的 DataSets
        # 注意：RDL 結構中 Field 節點通常在 DataSet > Fields > Field
        datasets = root.findall(".//rdl:DataSet", ns) or root.findall(".//rdl_old:DataSet", ns)
        
        if not datasets:
            return f"報表 '{report_name}' 中沒有偵測到任何 DataSets。"

        for ds in datasets:
            ds_name = ds.get("Name")
            fields = []
            # 抓取該 DataSet 下的所有 Field Name
            field_nodes = ds.findall(".//rdl:Field", ns) or ds.findall(".//rdl_old:Field", ns)
            for field in field_nodes:
                fields.append(field.get("Name"))
            
            if fields:
                report_structure.append(f"資料集 [{ds_name}] 包含欄位: {', '.join(fields)}")
            else:
                report_structure.append(f"資料集 [{ds_name}] 未定義具體欄位。")

        return f"--- 報表結構分析：{report_name} ---\n" + "\n".join(report_structure)

    except Exception as e:
        return f"解析 RDL 時發生錯誤: {str(e)}"
        
@mcp.tool()
def get_url_image(id: int = Field(description="圖片ID")):
    try:
        url = "https://rirmsdev.csitech.com/RMS/AspSoft/Document/ViewImage/ImageHandler.ashx?type=L&image_id=" + str(id)

        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        target_file_name = f"{timestamp}_{id}.png"
        target_path = os.path.abspath(os.path.join(WORKSPACE_DIR, target_file_name))

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)

        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=20) as response, open(target_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)

        return f"下載成功，檔案在：{target_path}"
    except Exception as e:
        return f"下載失敗：{type(e).__name__}: {e}"

@mcp.tool()
def no_more_tools():
    """如果你認為任務已經完成，執行這個來表示你不需要額外工具了。"""
    return "全部執行完成，不需要額外工具。"

@mcp.tool()
def no_tools_available():
    """如果你發現沒有任何工具可用，執行這個來表示找不到工具。"""
    return "全部執行完成，沒有任何可用工具，不須再呼叫工具。"