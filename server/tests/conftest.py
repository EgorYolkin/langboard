import pytest

from langboard_server.db import connect, migrate


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    yield conn
    conn.close()
