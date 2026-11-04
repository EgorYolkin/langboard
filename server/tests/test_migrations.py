import sqlite3

from langboard_server.db import connect, migrate

EXPECTED_TABLES = {
    "credential",
    "connection",
    "usage_event",
    "raw_usage",
    "provider_aggregate",
    "reconciliation_result",
    "price_snapshot",
    "cost_entry",
    "quota_observation",
    "model_alias",
    "collect_runs",
}


def tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_all_tables_created(tmp_path):
    conn = connect(tmp_path / "t.db")
    try:
        migrate(conn)
        assert EXPECTED_TABLES <= tables(conn)
    finally:
        conn.close()


def test_migrate_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    try:
        migrate(conn)
        before = tables(conn)
        assert migrate(conn) == []
        assert tables(conn) == before
    finally:
        conn.close()


def test_credential_kind_check_constraint(tmp_path):
    conn = connect(tmp_path / "t.db")
    try:
        migrate(conn)
        try:
            conn.execute(
                "INSERT INTO credential (id, provider, kind, label) "
                "VALUES ('x', 'openai', 'bogus', 'l')"
            )
            raise AssertionError("CHECK constraint did not fire")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()
