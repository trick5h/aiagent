import json
import os
from pathlib import Path
from pydantic import BaseModel, field_validator

# =========================
# Config (loaded from config.json with pydantic validation)
# =========================

class AppConfig(BaseModel):
    MODEL: str = "qwen2.5-coder:7b"
    SMALL_MODEL: str = MODEL
    SERVER_COMMAND: str = "python"
    SERVER_PATH: str = "mcpServer/server.py"
    SOUL_PATH: str = "SOUL.md"
    MEMORY_PATH: str = "MEMORY.md"
    WORKSPACE_DIR: str = "workspace/"
    MAX_TOOL_LOOPS: int = 8
    LOG_PATH: str  = "logs.jsonl"
    SESSION_LOG_HEADER: str = "## Session Summary Log"
    SESSION_MEMORY_LIMIT: int = 5

    @field_validator("SMALL_MODEL", mode="before")
    @classmethod
    def set_small_model_default(cls, v):
        return v

    @field_validator("LOG_PATH", mode="before")
    def default_log_path(cls, v):
        # default to same directory as this file
        if v:
            return v
        return str(Path(__file__).resolve().parent / "logs.jsonl")


def load_config(path: str | None = None) -> AppConfig:
    """Load configuration from JSON file (default: config.json).

    Relative paths in the config are interpreted relative to the config file.
    """
    cfg_path = Path(path or os.environ.get("AIAGENT_CONFIG", "config.json"))
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"> Failed to read config {cfg_path}: {e}")

    # Normalize path fields to be strings (pydantic will validate)
    # If relative, make them relative to config file directory
    cfg_dir = cfg_path.parent if cfg_path.exists() else Path.cwd()
    for key in ("SERVER_PATH", "SOUL_PATH", "MEMORY_PATH", "LOG_PATH", "WORKSPACE_DIR"):
        val = data.get(key)
        if isinstance(val, str) and val:
            p = Path(val)
            data[key] = str(p if p.is_absolute() else (cfg_dir / p))

    cfg = AppConfig(**data)
    return cfg

# Load config once and expose module-level constants
CONFIG = load_config()
MODEL = CONFIG.MODEL
SMALL_MODEL = CONFIG.SMALL_MODEL
SERVER_COMMAND = CONFIG.SERVER_COMMAND
SERVER_PATH = Path(CONFIG.SERVER_PATH)
SOUL_PATH = Path(CONFIG.SOUL_PATH)
MEMORY_PATH = Path(CONFIG.MEMORY_PATH)
WORKSPACE_DIR = Path(CONFIG.WORKSPACE_DIR)
MAX_TOOL_LOOPS = int(CONFIG.MAX_TOOL_LOOPS)
LOG_PATH = Path(CONFIG.LOG_PATH)
SESSION_LOG_HEADER = CONFIG.SESSION_LOG_HEADER
SESSION_MEMORY_LIMIT = int(CONFIG.SESSION_MEMORY_LIMIT)