"""Environment-driven configuration (no settings framework, per stage-1 plan)."""

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def db_path() -> Path:
    default = _REPO_ROOT / "server" / "data" / "langboard.db"
    p = Path(os.environ.get("DB_PATH", str(default)))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def ingest_token() -> str:
    return os.environ.get("INGEST_TOKEN", "")


def host() -> str:
    return os.environ.get("HOST", "127.0.0.1")


def port() -> int:
    return int(os.environ.get("PORT", "8000"))
