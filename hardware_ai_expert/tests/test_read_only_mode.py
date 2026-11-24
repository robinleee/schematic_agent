"""NEO4J_READ_ONLY opens READ_ACCESS sessions so the server itself rejects writes."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_system import graph_tools  # noqa: E402


class _FakeSession:
    def __init__(self, opened):
        self.opened = opened

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, params):
        return []


class _FakeDriver:
    def __init__(self):
        self.kwargs = None

    def session(self, **kwargs):
        self.kwargs = kwargs
        return _FakeSession(kwargs)


@pytest.mark.parametrize("read_only, expected", [
    (True, {"default_access_mode": graph_tools.READ_ACCESS}),
    (False, {}),
])
def test_session_access_mode_follows_read_only_flag(monkeypatch, read_only, expected):
    driver = _FakeDriver()
    monkeypatch.setattr(graph_tools, "READ_ONLY_MODE", read_only)
    monkeypatch.setattr(graph_tools, "_get_driver", lambda: driver)
    graph_tools._run_cypher("MATCH (n) RETURN count(n) AS c")
    assert driver.kwargs == expected


def test_write_keywords_still_rejected_before_reaching_server(monkeypatch):
    monkeypatch.setattr(graph_tools, "READ_ONLY_MODE", True)
    monkeypatch.setattr(graph_tools, "_get_driver", lambda: pytest.fail("must not connect"))
    with pytest.raises(PermissionError):
        graph_tools._run_cypher("MATCH (n) SET n.x = 1")
