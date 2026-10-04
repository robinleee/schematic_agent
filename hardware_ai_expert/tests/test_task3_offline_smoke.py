"""Task 3 offline page-operation smoke coverage.

All collaborators are mocked and uploads/jobs use temporary paths.  This file
must not require Neo4j, Chroma, Ollama, a browser, or a live ETL import.
"""
import sys
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hardware_ai_expert.api import dependencies
from hardware_ai_expert.api.main import app
from hardware_ai_expert.api.routers import chat, etl, hitl
from agent_system import etl_web_bridge


BASE = "/api/v1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from neo4j import GraphDatabase
    from agent_system import knowledge_router

    def no_live(*args, **kwargs):
        pytest.fail("unexpected live dependency in offline smoke")

    monkeypatch.setenv("API_SECURITY_MODE", "offline")
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(GraphDatabase, "driver", no_live)
    monkeypatch.setattr(knowledge_router, "_get_chroma_client", no_live)
    with TestClient(app) as test_client:
        yield test_client


def _etl_files():
    return {
        "pstxnet": ("fixture.dat", b"NET"),
        "pstxprt": ("fixture.dat", b"PRT"),
        "pstchip": ("fixture.dat", b"CHIP"),
    }


def test_all_page_operations_and_websocket_contracts_are_offline(client, monkeypatch):
    """Exercise every frontend API operation using only deterministic fakes."""
    monkeypatch.setattr(chat, "_run_agent", lambda message, task_type, project_id=None: {
        "status": "success", "task_type": task_type, "report": "chat report",
        "execution_trace": [], "tool_call_count": 1,
    })
    assert client.post(f"{BASE}/chat", json={"message": "hello"}).json()["data"]["report"] == "chat report"
    invalid = client.post(f"{BASE}/chat", json={"message": " "})
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["body", "message"]
    assert isinstance(invalid.json()["detail"][0]["msg"], str)

    review_engine = SimpleNamespace(
        config_manager=SimpleNamespace(list_rules=lambda enabled_only: [{
            "id": "R1", "name": "Rule", "template_id": "T",
            "severity": "WARNING", "enabled": True,
        }]),
        run_rules=lambda **kwargs: [],
    )
    monkeypatch.setattr(dependencies, "get_review_engine", lambda: review_engine)
    assert client.get(f"{BASE}/review/rules").json()["data"][0]["id"] == "R1"
    assert client.post(f"{BASE}/review/run", json={"enabled_only": True}).json()["data"]["summary"]["total"] == 0

    hitl_manager = SimpleNamespace(
        get_pending_list=lambda status: [],
        approve=lambda review_id, **kwargs: True,
        reject=lambda review_id, **kwargs: True,
        save_approved_rules=lambda: {"saved": 0},
    )
    monkeypatch.setattr(hitl, "get_hitl_manager", lambda: hitl_manager)
    assert client.get(f"{BASE}/hitl/pending").json()["total"] == 0
    assert client.post(f"{BASE}/hitl/action", json={
        "review_ids": ["one"], "action": "approve",
    }).json()["data"]["succeeded"] == 1
    assert client.post(f"{BASE}/hitl/export", json={}).json()["data"]["saved"] == 0

    knowledge = SimpleNamespace(
        upload_document=lambda **kwargs: {"chunk_count": 1, "mpn": kwargs["mpn"]},
        search=lambda **kwargs: {
            "status": "not_found", "tier": "none", "content": "",
            "source": "", "confidence": 0, "cached": False,
        },
        get_stats=lambda: {
            "tier1_chunks": 1, "tier2_enabled": False,
            "tier3_enabled": False, "source_distribution": {},
        },
    )
    monkeypatch.setattr(dependencies, "get_knowledge_router", lambda **kwargs: knowledge)
    assert client.post(f"{BASE}/knowledge/upload",
                       data={"mpn": "M", "project_id": "board"},
                       files={"file": ("fixture.txt", b"hello")}).status_code == 200
    assert client.post(f"{BASE}/knowledge/search",
                       json={"query": "M", "project_id": "board"}).status_code == 200
    assert client.get(f"{BASE}/knowledge/stats").json()["data"]["tier1_chunks"] == 1
    assert client.post(f"{BASE}/knowledge/upload",
                       data={"mpn": "M"}, files={"file": ("fixture.txt", b"hello")}).status_code == 422

    class Executor:
        def create_project(self, name):
            return {"project_id": name}

        def delete_project(self, name):
            return {"project_id": name, "deleted_nodes": "0"}

        def preview(self, paths):
            return {"success": True, "bom_enriched_components": 1}

        def run_etl(self, paths, name):
            return {"success": False, "quality_passed": False, "message": "quality failed"}

        def get_progress(self, job_id):
            return {"step": "completed", "progress": 100, "message": job_id}

    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", Executor)
    monkeypatch.setattr("agent_system.graph_tools.list_projects", lambda: ["board"])
    assert client.get(f"{BASE}/etl/projects").json()["data"] == ["board"]
    assert client.post(f"{BASE}/etl/projects",
                       json={"project_name": "board"}).json()["data"]["project_id"] == "board"
    assert client.delete(f"{BASE}/etl/projects/board").json()["success"] is True
    assert client.post(f"{BASE}/etl/preview", files=_etl_files()).json()["data"]["success"] is True
    accepted = client.post(f"{BASE}/etl/run", data={"project_name": "board"},
                           files=_etl_files())
    assert accepted.json()["status"] == "queued"
    deadline = monotonic() + 5
    while True:
        progress = client.get(f"{BASE}/etl/progress/{accepted.json()['job_id']}")
        assert progress.status_code == 200
        if progress.json()["status"] not in ("queued", "running"):
            break
        assert monotonic() < deadline, "fake ETL worker did not finish"
        sleep(0.02)
    assert progress.json()["status"] == "failed"
    assert progress.json()["error"] == "quality failed"
    assert progress.json()["result"]["message"] == "quality failed"
    assert client.get(f"{BASE}/etl/progress/missing").status_code == 404

    graph = SimpleNamespace(
        _build_component_relation_dot=lambda **kwargs: 'digraph { U1; }',
        _build_power_chain_dot=lambda **kwargs: 'digraph {}',
        _build_fault_root_dot=lambda **kwargs: 'digraph {}',
        _build_common_cause_dot=lambda **kwargs: 'digraph {}',
        _build_power_tree_dot=lambda **kwargs: 'digraph {}',
    )
    monkeypatch.setitem(sys.modules, "web_ui.sub_pages.graph_viz", graph)
    assert client.post(f"{BASE}/graph/visualize",
                       json={"mode": "component", "refdes": "U1"}).status_code == 200
    import chromadb
    from agent_system import connection_pool
    monkeypatch.setattr(connection_pool, "get_neo4j_driver", lambda: None)
    monkeypatch.setattr(connection_pool, "get_ollama_client", lambda: None)
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kwargs:
                        SimpleNamespace(heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("offline"))))
    status = client.get(f"{BASE}/system/status")
    assert status.status_code == 200
    assert status.json()["data"]["data_stats"]["status"] == "unavailable"

    class Agent:
        def run(self, message, task_type, project_id=None):
            return {"status": "success", "task_type": task_type, "report": "ws report",
                    "execution_trace": [], "tool_call_count": 1}

    monkeypatch.setitem(sys.modules, "agent_system.react_agent",
                        SimpleNamespace(ReActAgent=Agent))
    with client.websocket_connect("/ws/chat", subprotocols=["chat.v1"]) as websocket:
        assert websocket.accepted_subprotocol == "chat.v1"
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}
        websocket.send_json({"type": "chat", "payload": {
            "message": "hello", "task_type": "query",
        }})
        result = websocket.receive_json()
        assert result["type"] == "result"
        assert result["payload"]["result"]["report"] == "ws report"

    class FailingAgent:
        def run(self, message, task_type, project_id=None):
            raise RuntimeError("offline agent failure")

    monkeypatch.setitem(sys.modules, "agent_system.react_agent",
                        SimpleNamespace(ReActAgent=FailingAgent))
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "chat", "payload": {
            "message": "hello", "task_type": "query",
        }})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["error"] == "offline agent failure"
