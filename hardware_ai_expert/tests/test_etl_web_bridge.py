"""Regression tests for ETL web bridge Cypher queries."""

from agent_system.etl_web_bridge import ETLWebExecutor
from neo4j import GraphDatabase


class FakeSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher, params):
        self.calls.append((cypher, params))


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session

    def close(self):
        pass


def test_create_project_uses_valid_merge_timestamp_clause_order(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        GraphDatabase,
        "driver",
        lambda *args, **kwargs: FakeDriver(session),
    )

    assert ETLWebExecutor().create_project("project-a") == {"project_id": "project-a"}

    query, params = session.calls[0]
    assert params == {"pid": "project-a"}
    assert query.index("MERGE") < query.index("ON CREATE SET")
    assert query.index("ON CREATE SET") < query.index("SET p.name")
    assert "p.created_at = datetime()" in query
    assert "p.updated_at = datetime()" in query
