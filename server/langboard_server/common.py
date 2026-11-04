import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

# Detached namespace for deterministic backfill event ids (idempotent re-import).
NAMESPACE = uuid.NAMESPACE_URL

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "uncached_input_tokens",
    "cached_read_tokens",
    "cache_write_tokens",
    "cache_write_ttl_5m_tokens",
    "cache_write_ttl_1h_tokens",
    "cache_write_ttl_30m_tokens",
    "cache_write_ttl_12h_tokens",
    "cache_hit_tokens",
    "cache_miss_tokens",
    "reasoning_tokens",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_uuid5(source: str, source_event_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{source}:{source_event_id}"))


def ensure_credential(conn: sqlite3.Connection, provider: str, kind: str, label: str) -> str:
    """Get or create a credential by natural key (provider, label)."""
    row = conn.execute(
        "SELECT id FROM credential WHERE provider = ? AND label = ?", (provider, label)
    ).fetchone()
    if row:
        return row[0]
    cred_id = str(uuid.uuid4())
    conn.execute(
        "INSERT OR IGNORE INTO credential (id, provider, kind, label) VALUES (?, ?, ?, ?)",
        (cred_id, provider, kind, label),
    )
    row = conn.execute(
        "SELECT id FROM credential WHERE provider = ? AND label = ?", (provider, label)
    ).fetchone()
    return row[0]


def map_codex_provider(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if "zai" in normalized:
        return "zai"
    if "anthropic" in normalized:
        return "anthropic"
    return "openai"


TokensSource = Literal["provider_response", "client_telemetry", "proxy", "estimated"]
Accuracy = Literal["verified", "unverified"]


class Heartbeat(BaseModel):
    source: str
    status: str
    http_code: int | None = None
    error: str | None = None


class IngestEvent(BaseModel):
    id: str
    source_event_id: str
    provider: str
    credential_label: str
    model_raw: str | None = None
    ts_utc: str
    attempt_no: int = 1
    streaming: bool | None = None
    tokens_source: TokensSource | None = None
    accuracy: Accuracy | None = "unverified"
    raw_usage: dict | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    uncached_input_tokens: int | None = None
    cached_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_write_ttl_5m_tokens: int | None = None
    cache_write_ttl_1h_tokens: int | None = None
    cache_write_ttl_30m_tokens: int | None = None
    cache_write_ttl_12h_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None


class IngestBatch(BaseModel):
    device_id: str
    client_name: str
    client_version: str | None = None
    heartbeat: Heartbeat | None = None
    events: list[IngestEvent]


def insert_usage_event(
    conn: sqlite3.Connection, row: dict, raw_payload: dict | None = None, provider_ids: dict | None = None
) -> None:
    """Insert one usage_event (+raw_usage) with OR IGNORE; dedup by (source, source_event_id)."""
    columns = [
        "id",
        "source",
        "source_event_id",
        "credential_id",
        "connection_id",
        "provider",
        "device_id",
        "client_name",
        "client_version",
        "model_raw",
        "canonical_model",
        "ts_utc",
        "received_at_utc",
        "attempt_no",
        "streaming",
        "incomplete",
        "tokens_source",
        "accuracy",
        *TOKEN_FIELDS,
    ]
    values = [row.get(c) for c in columns]
    conn.execute(
        f"INSERT OR IGNORE INTO usage_event ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        values,
    )
    if raw_payload is not None:
        conn.execute(
            "INSERT OR IGNORE INTO raw_usage (usage_event_id, provider_ids, payload) VALUES (?, ?, ?)",
            (row["id"], json.dumps(provider_ids) if provider_ids else None, json.dumps(raw_payload)),
        )
