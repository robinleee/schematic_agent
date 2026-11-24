"""Project scoping for graph visualization and the project list."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_system import graph_tools  # noqa: E402
from agent_system.graph_tools import set_current_project  # noqa: E402
from web_ui.sub_pages import graph_viz  # noqa: E402


def _capture(monkeypatch):
    queries = []

    def fake_run(query, params=None):
        queries.append(query)
        return []

    monkeypatch.setattr(graph_viz, "_run_cypher_raw", fake_run)
    return queries


def test_component_graph_filters_by_selected_project(monkeypatch):
    queries = _capture(monkeypatch)
    set_current_project("board-a")
    try:
        graph_viz._build_component_relation_dot("U1", depth=1)
    finally:
        set_current_project("default")
    assert queries
    assert all("/*PID:" not in q for q in queries)
    assert all("c.project_id = $project_id" in q for q in queries)


def test_component_graph_default_scope_has_no_project_filter(monkeypatch):
    queries = _capture(monkeypatch)
    set_current_project("default")
    graph_viz._build_component_relation_dot("U1", depth=1)
    assert queries
    assert all("/*PID:" not in q and "$project_id" not in q for q in queries)


def test_list_projects_reads_both_project_schemas(monkeypatch):
    monkeypatch.setattr(graph_tools, "_run_cypher", lambda q, *a, **k: [
        {"id": "beet7_acceptance"}, {"id": "HW7.0"}, {"id": "default"},
        {"id": "legacy"}, {"id": None}, {"id": "beet7_acceptance"},
    ])
    assert graph_tools.list_projects() == ["default", "HW7.0", "beet7_acceptance", "legacy"]
