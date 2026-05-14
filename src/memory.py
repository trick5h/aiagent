from datetime import datetime
from pathlib import Path
import re

from config import SESSION_LOG_HEADER, SESSION_MEMORY_LIMIT

# =========================
# Memory
# =========================

def load_recent_memory_notes(path: Path, limit: int = SESSION_MEMORY_LIMIT) -> str:
    if not path.exists():
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    session_lines = [
        line for line in lines
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},", line)
    ]
    if not session_lines:
        return ""
    return "\n".join(session_lines[-limit:])

def append_memory_summary(path: Path, summary: str) -> None:
    summary = " ".join(summary.split()).strip()
    if not summary:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        existing_text = ""

    needs_header = SESSION_LOG_HEADER not in existing_text
    with open(path, "a", encoding="utf-8") as fh:
        if needs_header:
            if existing_text and not existing_text.endswith("\n"):
                fh.write("\n")
            fh.write(f"\n{SESSION_LOG_HEADER}\n")
        fh.write(f"{timestamp}, {summary}\n")