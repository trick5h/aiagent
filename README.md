This README provides a professional overview of your AI Agent's architecture, specifically focusing on the integration between **OpenClaw**, **Python MCP**, and the **C# RDL Rendering Engine**.

---

## README.md

# RDL Report AI Agent (MCP)

This project implements an intelligent Report Management Agent using the **Model Context Protocol (MCP)**. It allows an AI (via OpenClaw) to analyze, parameterize, and execute local **SQL Server Reporting Services (SSRS) RDL files** to generate PDF reports.

## 🚀 Architecture Overview

The system operates through a three-layer architecture:

1. **Orchestrator (OpenClaw):** Manages user intent and tool selection.
2. **Bridge (Python MCP):** Acts as the brain, parsing RDL structures (XML) and managing logic.
3. **Engine (C# CLI):** A specialized .NET wrapper that utilizes `Microsoft.ReportViewer` to render pixel-perfect PDFs from RDL templates.

## 🛠️ Prerequisites & Packages

### 1. Python Environment (The Bridge)

The Python layer handles the MCP protocol and XML parsing.

* **Python 3.10+**
* **Packages:**
* `fastmcp`: High-level framework for building MCP servers.
* `xml.etree.ElementTree`: (Built-in) For RDL structure analysis.



```bash
pip install fastmcp

```

### 2. .NET Environment (The Engine)

Required to render RDL files locally without an SSRS Server.

* **.NET SDK 6.0/8.0** (Visual Studio 2022 recommended)
* **NuGet Packages:**
* `Microsoft.ReportingServices.ReportViewerControl.Winforms`: The core rendering engine.



### 3. System Requirements (Windows)

* **SQL Server Types:** Required by the Report Viewer control for spatial data support.

## 📂 Project Structure

```text
├── mcp-server/
│   ├── main.py              # Python MCP entry point
│   └── reports/             # Folder containing your .rdl files
├── rdl-engine/
│   ├── RdlExporter.cs       # C# CLI Source code
│   └── RdlExporter.exe      # Compiled rendering binary
└── exports/                 # Generated PDF destination

```

## 🔧 Tool Definitions

The agent exposes the following capabilities:

| Tool | Input | Description |
| --- | --- | --- |
| `analyze_report_data` | `report_name` | Parses the RDL XML to list available DataSets and Fields. |
| `generate_rdl_pdf` | `name`, `params` | Triggers the C# Engine to produce a PDF report. |

## ⚙️ Configuration in OpenClaw

To register this agent, run the following command in your terminal:

```powershell
$mcpConfig = '{"command": "python", "args": ["D:/path/to/main.py"]}'
openclaw mcp set report-manager $mcpConfig

```

## 📝 Usage Example

**User:** "Show me the structure of the SalesReport."
**Agent:** (Calls `analyze_report_data`) "This report contains fields: OrderID, Customer, and TotalAmount."

**User:** "Great, generate a PDF for Customer 'Gemini' and save it."
**Agent:** (Calls `generate_rdl_pdf`) "Success! Your report is ready at D:/Exports/SalesReport_result.pdf."

---

## 🔒 Security Note

This agent is designed for local use. Ensure that the RDL directory is secured and that user-provided parameters are sanitized within the Python bridge to prevent path traversal or SQL injection.
