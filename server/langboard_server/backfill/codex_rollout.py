"""Backfill parser for Codex rollout files (~/.codex/sessions, .jsonl and .jsonl.zst).

OpenAI semantics (report §5.1): nested — input_tokens includes cached and
cache-write; store as the provider returned them, never re-add.

Only `token_usage_record.payload.usage` is imported (per-response). The
`turn_token_usage` (duplicate) and `thread_token_usage` (cumulative) blocks and
the cumulative `event_msg/token_count` counters are deliberately ignored.
"""

import io
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from ..common import (
    TOKEN_FIELDS,
    ensure_credential,
    event_uuid5,
    insert_usage_event,
    map_codex_provider,
    utcnow_iso,
)

SOURCE = "codex_rollout"
DEFAULT_ROOT = Path.home() / ".codex" / "sessions"


def open_rollout(path: Path):
    if path.suffix == ".zst":
        import zstandard

        raw = zstandard.ZstdDecompressor().stream_reader(open(path, "rb"))
        return io.TextIOWrapper(raw, encoding="utf-8")
    return open(path, encoding="utf-8")


def iter_records(path: Path) -> Iterator[dict]:
    with open_rollout(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def rollout_files(root: Path) -> list[Path]:
    return sorted(
        p for p in Path(root).rglob("rollout-*") if p.suffix in {".jsonl", ".zst"} and p.is_file()
    )


def backfill(
    conn: sqlite3.Connection,
    root: Path = DEFAULT_ROOT,
    credential_label: str = "Codex (local)",
    dry_run: bool = False,
) -> int:
    cred_cache: dict[str, str] = {}
    total_imported = 0
    for path in rollout_files(root):
        provider = "openai"
        current_model: str | None = None
        imported = 0
        skipped = 0
        conn.execute("BEGIN")
        try:
            for rec in iter_records(path):
                rec_type = rec.get("type")
                if rec_type == "session_meta":
                    raw = (rec.get("payload") or {}).get("model_provider")
                    provider_name = raw if isinstance(raw, str) else None
                    provider = map_codex_provider(provider_name or "")
                elif rec_type == "turn_context":
                    model = (rec.get("payload") or {}).get("model")
                    if model:
                        current_model = model
                elif rec_type == "token_usage_record":
                    payload = rec.get("payload") or {}
                    usage = payload.get("usage")
                    if not isinstance(usage, dict):
                        skipped += 1
                        continue
                    source_event_id = payload.get("response_id")
                    if not source_event_id:
                        source_event_id = f"{payload.get('session_id')}:{rec.get('ordinal')}"
                    if dry_run:
                        imported += 1
                        continue
                    if provider not in cred_cache:
                        cred_cache[provider] = ensure_credential(
                            conn, provider, "subscription", credential_label
                        )
                    row = {
                        "id": event_uuid5(SOURCE, source_event_id),
                        "source": SOURCE,
                        "source_event_id": source_event_id,
                        "credential_id": cred_cache[provider],
                        "provider": provider,
                        "client_name": "codex",
                        "model_raw": current_model,
                        "ts_utc": rec.get("timestamp"),
                        "received_at_utc": utcnow_iso(),
                        "attempt_no": 1,
                        "streaming": None,
                        "incomplete": 0,
                        "tokens_source": "provider_response",
                        "accuracy": "unverified",
                        "input_tokens": usage.get("input_tokens"),
                        "cached_read_tokens": usage.get("cached_input_tokens"),
                        "cache_write_tokens": usage.get("cache_write_input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "reasoning_tokens": usage.get("reasoning_output_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    }
                    for field in TOKEN_FIELDS:
                        row.setdefault(field, None)
                    insert_usage_event(
                        conn,
                        row,
                        raw_payload=payload["usage"],
                        provider_ids={"response_id": payload.get("response_id")},
                    )
                    imported += 1
            if imported == 0:
                print(f"warning: no token_usage_record in {path}")
            conn.execute("COMMIT" if not dry_run else "ROLLBACK")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        total_imported += imported
        if imported or skipped:
            print(json.dumps({"file": str(path), "imported": imported, "skipped": skipped}))
    return total_imported
