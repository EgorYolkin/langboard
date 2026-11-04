"""Privacy regression (report §5.2 rule 10): no columns for conversation content."""

FORBIDDEN_COLUMNS = {"content", "role", "messages", "prompt"}


def test_no_content_columns_in_schema(db):
    tables = [
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    assert tables, "schema must have tables"
    for table in tables:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        leak = columns & FORBIDDEN_COLUMNS
        assert not leak, f"table {table} must not have content-like columns: {leak}"
