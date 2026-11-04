"""Backfill parser for Claude Code JSONL transcripts (~/.claude/projects).

Anthropic semantics (report §5.1): additive — input excludes cache; total_tokens
is not provided by the source and is NOT invented (stays NULL).
"""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from ..common import TOKEN_FIELDS, ensure_credential, event_uuid5, insert_usage_event, utcnow_iso

SOURCE = "claude_code_jsonl"
SYNTHETIC_MODEL = "<synthetic>"
DEFAULT_ROOT = Path.home() / ".claude" / "projects"


def iter_records(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_file(path: Path) -> Iterator[tuple[dict, int]]:
    """Yield (record, skipped) for assistant records; skipped=1 → synthetic/zero/no-usage."""
    for rec in iter_records(path):
        if rec.get("type") != "assistant":
            continue
        message = rec.get("message") or {}
        usage = message.get("usage")
        if not isinstance(usage, dict):
            yield rec, 1
            continue
        if message.get("model") == SYNTHETIC_MODEL:
            yield rec, 1
            continue
        four = (
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("cache_read_input_tokens"),
        )
        if all(isinstance(v, int) for v in four) and sum(four) == 0:
            yield rec, 1
            continue
        yield rec, 0


def to_event_row(rec: dict, credential_id: str) -> dict:
    message = rec.get("message") or {}
    usage = message.get("usage") or {}
    cache_creation = usage.get("cache_creation") or {}
    source_event_id = rec.get("uuid")
    row = {
        "id": event_uuid5(SOURCE, source_event_id),
        "source": SOURCE,
        "source_event_id": source_event_id,
        "credential_id": credential_id,
        "provider": "anthropic",
        "client_name": "claude-code",
        "model_raw": message.get("model"),
        "ts_utc": rec.get("timestamp"),
        "received_at_utc": utcnow_iso(),
        "attempt_no": 1,
        "streaming": None,
        "incomplete": 0,
        "tokens_source": "client_telemetry",
        "accuracy": "unverified",
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "cache_write_ttl_5m_tokens": cache_creation.get("ephemeral_5m_input_tokens"),
        "cache_write_ttl_1h_tokens": cache_creation.get("ephemeral_1h_input_tokens"),
    }
    for field in TOKEN_FIELDS:
        row.setdefault(field, None)
    return row


def backfill(
    conn: sqlite3.Connection,
    root: Path = DEFAULT_ROOT,
    credential_label: str = "Claude Code (local)",
    dry_run: bool = False,
) -> int:
    credential_id = (
        ensure_credential(conn, "anthropic", "subscription", credential_label)
        if not dry_run
        else ""
    )
    total_imported = 0
    for path in sorted(Path(root).rglob("*.jsonl")):
        imported = 0
        skipped = 0
        conn.execute("BEGIN")
        try:
            for rec, flag in parse_file(path):
                if flag:
                    skipped += 1
                    continue
                if dry_run:
                    imported += 1
                    continue
                insert_usage_event(
                    conn, to_event_row(rec, credential_id), raw_payload=rec["message"]["usage"]
                )
                imported += 1
            conn.execute("COMMIT" if not dry_run else "ROLLBACK")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        total_imported += imported
        print(json.dumps({"file": str(path), "imported": imported, "skipped": skipped}))
    return total_imported
