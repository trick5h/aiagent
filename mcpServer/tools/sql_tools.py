from server import mcp
from pydantic import Field

import pyodbc
import json
from decimal import Decimal
from datetime import datetime, date

# 設定連線字串
# Driver : 'SQL Server' or 'ODBC Driver 17 for SQL Server'
# Server 如果是本機，可以用 '.' 或 'localhost'
conn_str = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=10.1.3.61;'
    'DATABASE=RI_RMS30_DEV;'
    'UID=sa;'
    'PWD=infoshare;'
)


# 處理特殊型別的函式
def sql_json_serializer(obj):
    """協助處理 JSON 無法序列化的 SQL 型別"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)      
    raise TypeError(f"Type {type(obj)} not serializable")


@mcp.tool()
def list_tables(name : str = Field(description="搜尋字串")) -> str:
    """如果不確定資料庫中的表名稱，用此搜尋資料庫中是否有相關名稱的資料表(sys.tables)。請傳入參數，以使用like '%{name}%' 比對。"""
    
    sql="""select name 
    from sys.tables 
    where name like ?
    """

    # 每次調用工具時才連線
    with pyodbc.connect(conn_str) as conn:
        with conn.cursor() as cursor:
            
            # 嘗試連線
            try:
                cursor.execute(sql, (f'%{name}%',))
            except Exception as e:
                return f"資料庫執行錯誤: {str(e)}"

            # 回傳資料
            rows = cursor.fetchall()
            if not rows:
                return f"找不到與名稱 {name} 相似的資料表。"
            else:
                output = str(", ".join([row[0] for row in rows]))
                if len(output) > 1000:
                    return "相關名稱的資料表如下: "  + output[:1000] + " ... [資料過長已截斷，請指定查詢特定名稱]"
                return "相關名稱的資料表如下: "  + ", ".join([row[0] for row in rows])
    # 離開 with 區塊時，Python 會自動 close connection

@mcp.tool()
def get_table_schema(table_name : str = Field(description="資料表名稱")) -> str:
    """查詢指定資料表的欄位名稱與資料型態(INFORMATION_SCHEMA.COLUMNS)。"""

    sql="""select COLUMN_NAME, DATA_TYPE 
    from INFORMATION_SCHEMA.COLUMNS 
    where TABLE_NAME=?
    """

    with pyodbc.connect(conn_str) as conn:
        with conn.cursor() as cursor:
            
            # 嘗試連線
            try:
                cursor.execute(sql, (table_name,))
            except Exception as e:
                return f"資料庫執行錯誤: {str(e)}"
            
            # 回傳資料
            rows = cursor.fetchall()
            if not rows:
                return f"找不到資料表 {table_name} 的定義。"
            else:
                schema_info = [f"{row[0]} ({row[1]})" for row in rows]
                return f"{table_name} 資料表欄位如下: " + ", ".join(schema_info)

@mcp.tool()
def execute_sql(sql_query : str = Field(description="SQL 查詢語句")) -> str:
    """執行完整的 SQL 查詢，並回傳結果。請只執行所需的查詢以確保安全性與避免過多資料量。"""

    with pyodbc.connect(conn_str) as conn:
        with conn.cursor() as cursor:
            if not sql_query.strip().lower().startswith("select"):
                return "目前僅允許執行 SELECT 查詢以確保安全性。"
            
            # 嘗試連線
            try:
                cursor.execute(sql_query)
            except Exception as e:
                return f"資料庫執行錯誤: {str(e)}"
            
            # 回傳資料
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            if not rows:
                return "沒有找到符合條件的資料。"
            else:
                # 組合為自帶標籤的字典清單 (List of Dicts)
                results = [dict(zip(columns, row)) for row in rows]
            
            # 轉換為 JSON 字串，並處理非 ASCII 字元 (如中文)
            output = "執行完成。結果為: "
            output += json.dumps(results, ensure_ascii=False, indent=None, default=sql_json_serializer)
               
            # 硬性截斷防止溢位
            MAX_CHARS = 5000 
            if len(output) > MAX_CHARS:
                return output[:MAX_CHARS] + " ... [資料過長已截斷，請縮小查詢範圍或指定欄位]"
            
            return output