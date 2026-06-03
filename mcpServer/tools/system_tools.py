from server import mcp
from pydantic import Field

import xml.etree.ElementTree as ET
import psutil
import shutil
import os
import urllib.request
from datetime import datetime

import config

WORKSPACE_DIR = config.WORKSPACE_DIR

@mcp.tool()
def get_system_health() -> str:
    """Return the current machine's CPU usage and disk free space.

    This function queries the system for the current CPU utilization (percent)
    and the disk usage for the root drive, and returns a human-readable
    summary string.
    """
    cpu_usage = psutil.cpu_percent(interval=1)
    total, used, free = shutil.disk_usage("/")
    
    return (
        f"CPU 使用率: {cpu_usage}%\n"
        f"磁碟空間: 已用 {used // (2**30)}GB / 剩餘 {free // (2**30)}GB"
    )

#======================================================
# 定義 RDL 存放目錄
WORKSPACE_DIR = config.WORKSPACE_DIR
#======================================================

@mcp.tool()
def analyze_report_params(report_name: str = Field(description=".rdl檔案名稱")) -> str:
    """Read the specified RDL file and return a list of required parameters.

    Given a report name (without extension), this function loads the
    corresponding .rdl XML file from the workspace, extracts any
    ReportParameter entries, and returns a human-readable list with
    parameter names and their data types. If the file is missing or
    parsing fails, an error message is returned.
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
    """Parse the specified RDL file and return dataset field names.

    The function accepts a report filename (with or without the .rdl
    extension), loads the RDL XML from the workspace, locates DataSet
    nodes and their Field definitions, and returns a summary describing
    each dataset and the names of its fields. Useful for understanding
    the structure of the report's output data. On error, returns an
    explanatory message.
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
    """Download an image by ID from a remote image handler and save it.

    Builds a request URL using the provided image ID, downloads the
    image, saves it into the workspace directory with a timestamped
    filename, and returns the saved file path on success. On failure,
    returns an error message describing the exception.
    """
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
    """Indicate that all tasks are complete and no further tools are needed.

    This is intended for use by an agent to signal that it does not
    require any additional tool calls to complete its work.
    """
    return "All tasks completed; no further tools required."

@mcp.tool()
def no_tools_available():
    """Indicate that no relevant tools are available for the task.

    Use this to signal that the agent could not find any tools related
    to the requested operation and therefore cannot proceed with tool
    assistance.
    """
    return "All tasks completed; No available tools, so no further tools required."