This README provides a professional overview of your AI Agent's architecture, specifically focusing on the integration between **OpenClaw**, **Python MCP**, and the **C# RDL Rendering Engine**.

---

## README.md

# RDL Report AI Agent (MCP)

This project implements an intelligent Report Management Agent using the **Model Context Protocol (MCP)**. It allows an AI (via OpenClaw) to analyze, parameterize, and execute local **SQL Server Reporting Services (SSRS) RDL files** to generate PDF reports.

## 🚀 Architecture Overview

The system operates through a three-layer architecture:

1. **LLM (Ollama):** Manages user intent and tool selection.
2. **Bridge (Python MCP):** Acts as the brain, parsing RDL structures (XML) and managing logic.
## 🛠️ Prerequisites & Packages

### 1. Python Environment

The Python layer handles the MCP protocol and XML parsing.

* **Python 3.10+**
* **Packages:**
* `ollama`: Handling LLM input and responses.
* `mcp`: Managing local connection to the MCP server.
* `fastmcp`: High-level framework for building MCP servers.
* `xml.etree.ElementTree`: (Built-in) For RDL structure analysis.



```bash
pip install mcp
pip install fastmcp

```



### 2. System Requirements (Windows)

* **SQL Server Types:** Required by the Report Viewer control for spatial data support.

## 📂 Project Structure

```text
├── main.py
├── mcpServer/
│   ├── server.py          # Python MCP entry point
│   └── tools/             # Folder containing all available tools for the agent
│       ├── system_tools.py 
│       └── user_tools.py  
├── agent/
│   ├── mcp_client.py      # Connects to the Python MCP server
│   └── prompt.py          # Generates prompts for the LLM based on templates
├── workspace/             # Place for reports and temporary files
├── MEMORY.py              # Stores long-term memory and logs
└── SOUL.py                # Strict rules for decision-making and tool selection

```

## 🔧 Tool Definitions

The agent exposes the following capabilities:

| Tool | Input         | Description                                               |
| --- |---------------|-----------------------------------------------------------|
| `analyze_report_data` | `report_name` | Parses the RDL XML to list available DataSets. |
| `get_url_image` | `id`          | Downloads the image.                                      |


## 📝 Usage Example

**User:** "Show me the structure of the SalesReport."
**Agent:** (Calls `analyze_report_data`) "This report contains fields: OrderID, Customer, and TotalAmount."

**User:** "Great, download the image for Customer 'Gemini' and save it."
**Agent:** (Calls `get_url_image`) "Success! Your image is ready at D:/workspace/result.png."

---

## 🔒 Security Note

This agent is designed for local use.