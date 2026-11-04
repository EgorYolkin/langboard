import shutil
from pathlib import Path

from langboard_server.backfill import codex_rollout
from langboard_server.common import map_codex_provider

FIXTURES = Path(__file__).parent / "fixtures"

SELECT_ROW = (
    "SELECT source_event_id, provider, model_raw, input_tokens, cached_read_tokens, "
    "cache_write_tokens, output_tokens, reasoning_tokens, total_tokens, tokens_source "
    "FROM usage_event ORDER BY source_event_id"
)


def prepare_root(tmp_path: Path, name: str = "rollout-2026-09-23-x.jsonl") -> Path:
    root = tmp_path / "sessions"
    root.mkdir()
    shutil.copy(FIXTURES / "codex" / "sample.jsonl", root / name)
    return root


def test_import_and_categories(db, tmp_path):
    imported = codex_rollout.backfill(db, root=prepare_root(tmp_path))
    assert imported == 2
    rows = db.execute(SELECT_ROW).fetchall()
    assert rows == [
        # turn_/thread_token_usage (999/99999) and cumulative token_count ignored
        ("resp_0974d4ed", "openai", "gpt-6-astra", 32108, 0, 0, 146, 0, 32254, "provider_response"),
        ("s1:20", "openai", "gpt-6-astra", 500, 200, 10, 30, 5, 530, "provider_response"),
    ]


def test_zst_files_parsed_identically(db, tmp_path):
    import zstandard

    root = tmp_path / "sessions"
    root.mkdir()
    content = (FIXTURES / "codex" / "sample.jsonl").read_bytes()
    (root / "rollout-2026-09-23-y.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(content)
    )
    imported = codex_rollout.backfill(db, root=root)
    assert imported == 2
    assert db.execute("SELECT COUNT(*) FROM usage_event").fetchone()[0] == 2


def test_reimport_is_idempotent(db, tmp_path):
    root = prepare_root(tmp_path)
    codex_rollout.backfill(db, root=root)
    before = db.execute(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cached_read_tokens) "
        "FROM usage_event"
    ).fetchone()
    codex_rollout.backfill(db, root=root)
    after = db.execute(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cached_read_tokens) "
        "FROM usage_event"
    ).fetchone()
    assert before == after == (2, 32608, 176, 200)


def test_provider_mapping():
    assert map_codex_provider("openai") == "openai"
    assert map_codex_provider("zai") == "zai"
    assert map_codex_provider("Z.AI") == "zai"
    assert map_codex_provider("anthropic") == "anthropic"
    assert map_codex_provider("") == "openai"
    assert map_codex_provider(None) == "openai"
