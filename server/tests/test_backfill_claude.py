import json
import shutil
from pathlib import Path

from langboard_server.backfill import claude_jsonl

FIXTURES = Path(__file__).parent / "fixtures"

SELECT_ROW = (
    "SELECT source_event_id, input_tokens, output_tokens, cached_read_tokens, "
    "cache_write_tokens, cache_write_ttl_5m_tokens, cache_write_ttl_1h_tokens, "
    "total_tokens, provider, source, tokens_source, accuracy, model_raw "
    "FROM usage_event ORDER BY source_event_id"
)


def prepare_root(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    shutil.copy(FIXTURES / "claude" / "sample.jsonl", root / "session.jsonl")
    return root


def test_import_and_categories(db, tmp_path):
    imported = claude_jsonl.backfill(db, root=prepare_root(tmp_path))
    assert imported == 2
    rows = db.execute(SELECT_ROW).fetchall()
    assert rows == [
        (
            "a1",
            100,
            50,
            20,
            10,
            4,
            6,
            None,  # total_tokens: source does not provide it — never invented
            "anthropic",
            "claude_code_jsonl",
            "client_telemetry",
            "unverified",
            "claude-sonnet-4.5",
        ),
        (
            "a2",
            7,
            3,
            1,
            2,
            1,
            1,
            None,
            "anthropic",
            "claude_code_jsonl",
            "client_telemetry",
            "unverified",
            "claude-sonnet-4.5",
        ),
    ]


def test_raw_usage_is_usage_subtree_only(db, tmp_path):
    claude_jsonl.backfill(db, root=prepare_root(tmp_path))
    payloads = [json.loads(row[0]) for row in db.execute("SELECT payload FROM raw_usage")]
    assert len(payloads) == 2
    for payload in payloads:
        assert "role" not in payload
        assert "content" not in payload
        assert "input_tokens" in payload


def test_reimport_is_idempotent(db, tmp_path):
    root = prepare_root(tmp_path)
    claude_jsonl.backfill(db, root=root)
    before = db.execute(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cached_read_tokens), "
        "SUM(cache_write_tokens) FROM usage_event"
    ).fetchone()
    claude_jsonl.backfill(db, root=root)
    after = db.execute(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cached_read_tokens), "
        "SUM(cache_write_tokens) FROM usage_event"
    ).fetchone()
    assert before == after == (2, 107, 53, 21, 12)

def test_synthetic_and_zero_skipped(db, tmp_path, capsys):
    root = prepare_root(tmp_path)
    claude_jsonl.backfill(db, root=root)
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert summary == {"file": str(root / "session.jsonl"), "imported": 2, "skipped": 2}
