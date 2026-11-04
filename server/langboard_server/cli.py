"""CLI: migrate | serve | backfill | stats."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import config
from .db import connect, migrate

DEFAULT_CLAUDE_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_ROOT = Path.home() / ".codex" / "sessions"


def cmd_migrate(_args: argparse.Namespace) -> int:
    conn = connect(config.db_path())
    try:
        applied = migrate(conn)
        print(json.dumps({"applied": applied, "db": str(config.db_path())}))
    finally:
        conn.close()
    return 0


def cmd_serve(_args: argparse.Namespace) -> int:
    if not config.ingest_token():
        print(
            "error: INGEST_TOKEN is not set — refusing to start the server "
            "(export INGEST_TOKEN=<secret> first)",
            file=sys.stderr,
        )
        return 1
    import uvicorn

    from .ingest import app

    conn = connect(config.db_path())
    try:
        migrate(conn)
    finally:
        conn.close()
    uvicorn.run(app, host=config.host(), port=config.port())
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    conn = connect(config.db_path())
    try:
        migrate(conn)
        total = 0
        if args.source in ("claude", "all"):
            from .backfill import claude_jsonl

            total += claude_jsonl.backfill(
                conn,
                root=Path(args.root) if args.root and args.source == "claude" else DEFAULT_CLAUDE_ROOT,
                credential_label=args.credential_label or "Claude Code (local)",
                dry_run=args.dry_run,
            )
        if args.source in ("codex", "all"):
            from .backfill import codex_rollout

            total += codex_rollout.backfill(
                conn,
                root=Path(args.root) if args.root and args.source == "codex" else DEFAULT_CODEX_ROOT,
                credential_label=args.credential_label or "Codex (local)",
                dry_run=args.dry_run,
            )
        print(json.dumps({"total_imported": total, "dry_run": args.dry_run}))
    finally:
        conn.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(config.db_path())
    conn.row_factory = sqlite3.Row
    try:
        where = ""
        params: tuple = ()
        if args.days:
            where = "WHERE ts_utc >= date('now', ?)"
            params = (f"-{args.days} days",)
        rows = conn.execute(
            "SELECT date(ts_utc) AS day, provider, model_raw, COUNT(*) AS requests, "
            "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            "SUM(cached_read_tokens) AS cached_read_tokens, "
            "SUM(cache_write_tokens) AS cache_write_tokens, "
            "SUM(reasoning_tokens) AS reasoning_tokens "
            f"FROM usage_event {where} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3",
            params,
        ).fetchall()
        for row in rows:
            print(json.dumps(dict(row)))
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="langboard_server.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply pending migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("serve", help="run the API server").set_defaults(func=cmd_serve)

    backfill = sub.add_parser("backfill", help="import local history into usage_event")
    backfill.add_argument("--source", required=True, choices=["claude", "codex", "all"])
    backfill.add_argument("--root", help="source root (default: platform location)")
    backfill.add_argument("--credential-label", help="override auto-created credential label")
    backfill.add_argument("--dry-run", action="store_true", help="count only, do not write")
    backfill.set_defaults(func=cmd_backfill)

    stats = sub.add_parser("stats", help="daily usage sums as JSON lines")
    stats.add_argument("--days", type=int, help="limit to the last N days")
    stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
