from server import mcp
from pydantic import Field
import xml.etree.ElementTree as ET
import psutil
import shutil
import os


# 定義 RDL 存放目錄
RDL_DIR = "D:/AiAgent/workspace"
@mcp.tool()
def analyze_report_params(report_name: str) -> str:
    """
    讀取指定的 RDL 檔案並回傳它需要的參數清單。
    例如輸入 'Sales_Monthly'，會回傳該報表需要的日期、地區等參數。
    """
    file_path = os.path.join(RDL_DIR, f"{report_name}.rdl")
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
            p_type = param.find("rdl:DataType", ns).text if param.find("rdl:DataType", ns) is not None else "Unknown"
            params.append(f"- {p_name} ({p_type})")
        
        if not params:
            return f"報表 {report_name} 不需要任何參數。"
        return f"報表 '{report_name}' 需要以下參數：\n" + "\n".join(params)
    
    except Exception as e:
        return f"解析報表時出錯: {str(e)}"


def analyze_report_data(report_name: str) -> str:
    """
    解析指定 RDL 檔案中的 Dataset，回傳該報表包含的所有資料欄位名稱。
    這有助於了解報表輸出的數據結構。
    """
    # 確保副檔名正確
    if not report_name.endswith(".rdl"):
        report_name += ".rdl"
        
    file_path = os.path.join(RDL_FOLDER, report_name)
    
    if not os.path.exists(file_path):
        return f"錯誤：在路徑 {RDL_FOLDER} 找不到報表檔案 '{report_name}'。"

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

def get_url_image(id: int):
    
    url = "https://rirmsdev.csitech.com/RMS/AspSoft/Document/ViewImage/ImageHandler.ashx?type=L&image_id=" + id

    # 1. 定義路徑：當前資料夾 (os.getcwd()) 的 上一層 (..)
    # 假設我們要存成 'result.jpg'
    # 1. 取得 downloader.py 本身的絕對路徑
    module_path = os.path.abspath(__file__) 

    # 2. 取得該檔案所在的資料夾 (libs)
    module_dir = os.path.dirname(module_path)

    # 3. 取得該資料夾的上一層 (Project)
    target_dir = os.path.abspath(os.path.join(module_dir, "..", "result.jpg"))

    # 2. 直接下載

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

    urllib.request.urlretrieve(url, target_dir)


    print(f"下載成功，檔案在：{target_dir}")

print(analyze_report_params("TestList"))
print(analyze_report_params("TestList"))
print(analyze_report_data("TestFleet"))
print(analyze_report_data("TestList"))

get_url_image(544)