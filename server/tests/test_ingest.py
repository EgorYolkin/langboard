import uuid

import pytest
from fastapi.testclient import TestClient

from langboard_server import ingest as ingest_module
from langboard_server.db import connect, migrate
from langboard_server.ingest import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "secret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    return TestClient(app)


def batch_payload(n: int = 2) -> dict:
    return {
        "device_id": "dev1",
        "client_name": "pytest",
        "events": [
            {
                "id": str(uuid.uuid4()),
                "source_event_id": f"e{i}",
                "provider": "openai",
                "credential_label": "test",
                "ts_utc": "2026-11-04T00:00:00Z",
                "input_tokens": 10 + i,
                "output_tokens": 5,
            }
            for i in range(n)
        ],
    }


def open_db(tmp_path):
    conn = connect(tmp_path / "api.db")
    migrate(conn)
    return conn


def test_unauthorized_without_and_with_wrong_token(client):
    assert client.post("/ingest/events", json=batch_payload()).status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert client.post("/ingest/events", json=batch_payload(), headers=wrong).status_code == 401


def test_insert_then_dedup(client):
    headers = {"Authorization": "Bearer secret"}
    first = client.post("/ingest/events", json=batch_payload(2), headers=headers)
    assert first.status_code == 200
    assert first.json() == {"inserted": 2, "duplicates": 0}
    second = client.post("/ingest/events", json=batch_payload(2), headers=headers)
    assert second.json() == {"inserted": 0, "duplicates": 2}


def test_rows_written(client, tmp_path):
    headers = {"Authorization": "Bearer secret"}
    assert client.post("/ingest/events", json=batch_payload(2), headers=headers).status_code == 200
    conn = open_db(tmp_path)
    try:
        rows = conn.execute(
            "SELECT source, provider, input_tokens, output_tokens, accuracy "
            "FROM usage_event ORDER BY source_event_id"
        ).fetchall()
        assert rows == [
            ("ingest", "openai", 10, 5, "unverified"),
            ("ingest", "openai", 11, 5, "unverified"),
        ]
        kind = conn.execute("SELECT kind FROM credential WHERE label='test'").fetchone()[0]
        assert kind == "api_key"
    finally:
        conn.close()


def test_heartbeat_written_to_collect_runs(client, tmp_path):
    payload = batch_payload(1)
    payload["heartbeat"] = {"source": "collector", "status": "ok", "http_code": 200}
    headers = {"Authorization": "Bearer secret"}
    assert client.post("/ingest/events", json=payload, headers=headers).status_code == 200
    conn = open_db(tmp_path)
    try:
        row = conn.execute(
            "SELECT source, status, http_code, events_written FROM collect_runs"
        ).fetchone()
        assert row == ("collector", "ok", 200, 1)
    finally:
        conn.close()


def test_batch_size_limit(client, monkeypatch):
    monkeypatch.setattr(ingest_module, "MAX_INGEST_BATCH", 2)
    headers = {"Authorization": "Bearer secret"}
    response = client.post("/ingest/events", json=batch_payload(3), headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "batch too large"}
