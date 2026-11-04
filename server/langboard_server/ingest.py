"""POST /ingest/events — batched event intake with dedup (report §4.2 flow 1)."""

import sqlite3
import uuid

from fastapi import FastAPI, Header, HTTPException

from . import config
from .common import IngestBatch, ensure_credential, insert_usage_event, utcnow_iso
from .db import connect, migrate

MAX_INGEST_BATCH = 10_000
_SELECT_CHUNK = 500  # stay far below SQLITE_MAX_VARIABLE_NUMBER

app = FastAPI(title="langboard")


def _existing_source_event_ids(conn: sqlite3.Connection, ids: list[str]) -> set[str]:
    existing: set[str] = set()
    for i in range(0, len(ids), _SELECT_CHUNK):
        chunk = ids[i : i + _SELECT_CHUNK]
        placeholders = ", ".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT source_event_id FROM usage_event "
            f"WHERE source = 'ingest' AND source_event_id IN ({placeholders})",
            chunk,
        ).fetchall()
        existing.update(row[0] for row in rows)
    return existing


@app.post("/ingest/events")
def ingest_events(
    batch: IngestBatch,
    authorization: str = Header(default=""),
) -> dict:
    token = config.ingest_token()
    if not token or authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")
    if len(batch.events) > MAX_INGEST_BATCH:
        raise HTTPException(status_code=400, detail="batch too large")

    conn = connect(config.db_path())
    try:
        migrate(conn)
        conn.execute("BEGIN")
        try:
            existing = _existing_source_event_ids(conn, [e.source_event_id for e in batch.events])
            cred_cache: dict[tuple[str, str], str] = {}
            received = utcnow_iso()
            inserted = 0
            for event in batch.events:
                if event.source_event_id in existing:
                    continue
                key = (event.provider, event.credential_label)
                if key not in cred_cache:
                    cred_cache[key] = ensure_credential(
                        conn, event.provider, "api_key", event.credential_label
                    )
                row = {
                    "id": event.id,
                    "source": "ingest",
                    "source_event_id": event.source_event_id,
                    "credential_id": cred_cache[key],
                    "provider": event.provider,
                    "device_id": batch.device_id,
                    "client_name": batch.client_name,
                    "client_version": batch.client_version,
                    "model_raw": event.model_raw,
                    "ts_utc": event.ts_utc,
                    "received_at_utc": received,
                    "attempt_no": event.attempt_no,
                    "streaming": event.streaming,
                    "incomplete": 0,
                    "tokens_source": event.tokens_source,
                    "accuracy": event.accuracy,
                }
                for field in (
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
                ):
                    row[field] = getattr(event, field)
                before = conn.total_changes
                insert_usage_event(conn, row, raw_payload=event.raw_usage)
                inserted += int(conn.total_changes > before)
            duplicates = len(batch.events) - inserted

            if batch.heartbeat is not None:
                now = utcnow_iso()
                conn.execute(
                    "INSERT INTO collect_runs "
                    "(id, source, started_at, finished_at, status, http_code, error, events_written) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        batch.heartbeat.source,
                        now,
                        now,
                        batch.heartbeat.status,
                        batch.heartbeat.http_code,
                        batch.heartbeat.error,
                        len(batch.events),
                    ),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"inserted": inserted, "duplicates": duplicates}
    finally:
        conn.close()
