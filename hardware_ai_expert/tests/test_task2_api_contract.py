"""Offline HTTP contract tests; never touch live databases or rule files."""
from types import SimpleNamespace
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from hardware_ai_expert.api.main import app
from hardware_ai_expert.api.routers import chat, etl, hitl, system
from hardware_ai_expert.api import dependencies


client = TestClient(app)
BASE = "/api/v1"


@pytest.fixture(autouse=True)
def block_live_stores(monkeypatch):
    """Contract tests must fail, rather than silently consult a developer DB."""
    from neo4j import GraphDatabase
    from agent_system import knowledge_router

    def unexpected_live_access(*args, **kwargs):
        raise AssertionError("live store access in offline contract test")

    monkeypatch.setattr(GraphDatabase, "driver", unexpected_live_access)
    monkeypatch.setattr(knowledge_router, "_get_chroma_client", unexpected_live_access)
    monkeypatch.setattr(knowledge_router.KnowledgeRouter, "graphrag",
                        property(lambda self: None))

def test_project_list_ignores_legacy_null_ids(monkeypatch):
    import agent_system.graph_tools as graph_tools
    monkeypatch.setattr(graph_tools, "list_projects",
                        lambda: ["default", None, "board-a", ""])
    response = client.get(BASE + "/etl/projects")
    assert response.status_code == 200
    assert response.json()["data"] == ["default", "board-a"]


@pytest.mark.parametrize("path", ["/hitl/action", "/hitl/datasheet/action"])
@pytest.mark.parametrize("body", [
    {"review_ids": [], "action": "approve"},
    {"review_ids": ["one"], "action": "modify"},
    {"review_ids": [" "], "action": "reject"},
    {"review_ids": ["one", "one"], "action": "approve"},
])
def test_invalid_actions(path, body):
    assert client.post(BASE + path, json=body).status_code == 422


def test_normal_partial_and_single(monkeypatch):
    manager = SimpleNamespace(
        approve=lambda rid, **kw: rid == "ok",
        reject=lambda rid, **kw: rid == "ok",
        get_pending_list=lambda status: [],
    )
    monkeypatch.setattr(hitl, "get_hitl_manager", lambda: manager)
    result = client.post(BASE + "/hitl/action",
                         json={"review_ids": ["ok", "missing"], "action": "approve"})
    assert result.status_code == 200
    assert result.json()["success"] is False
    assert result.json()["data"] == {
        "results": [
            {"review_id": "ok", "action": "approve", "success": True, "error": None},
            {"review_id": "missing", "action": "approve", "success": False,
             "error": "Review not pending or update failed"},
        ],
        "succeeded": 1, "failed": 1,
    }
    assert client.post(BASE + "/hitl/action",
                       json={"review_ids": ["ok"], "action": "reject"}).json()["success"]
    assert client.get(BASE + "/hitl/pending").json()["total"] == 0


def test_datasheet_partial(monkeypatch):
    import agent_system.datasheet_hitl as datasheet
    monkeypatch.setattr(datasheet, "DatasheetHITLManager",
                        lambda: SimpleNamespace(approve=lambda rid, **kw: rid == "ok"))
    response = client.post(BASE + "/hitl/datasheet/action",
                           json={"review_ids": ["ok", "bad"], "action": "approve"})
    assert response.status_code == 200
    assert response.json()["data"]["failed"] == 1
    assert response.json()["success"] is False


def test_export_actual_result_and_empty(monkeypatch):
    monkeypatch.setattr(hitl, "get_hitl_manager",
                        lambda: SimpleNamespace(save_approved_rules=lambda: {
                            "saved": 1, "rules": ["R1"], "location": "/tmp/rules.yaml"}))
    result = client.post(BASE + "/hitl/export", json={})
    assert result.status_code == 200
    assert result.json()["data"] == {
        "saved": 1, "rules": ["R1"], "location": "custom_rules.yaml"}
    assert client.post(BASE + "/hitl/export", json={"review_ids": ["R1"]}).status_code == 422
    monkeypatch.setattr(hitl, "get_hitl_manager",
                        lambda: SimpleNamespace(save_approved_rules=lambda: {"saved": 0}))
    assert client.post(BASE + "/hitl/export", json={}).json()["data"]["saved"] == 0


def test_unavailable(monkeypatch):
    monkeypatch.setattr(hitl, "get_hitl_manager", lambda: None)
    assert client.get(BASE + "/hitl/pending").status_code == 503
    assert client.post(BASE + "/hitl/action",
                       json={"review_ids": ["a"], "action": "approve"}).status_code == 503
    assert client.post(BASE + "/hitl/export", json={}).status_code == 503
    monkeypatch.setattr(dependencies, "get_knowledge_router", lambda **kw: None)
    assert client.post(BASE + "/knowledge/upload", data={"mpn": "M", "project_id": "A"},
                       files={"file": ("a.txt", b"hello")}).status_code == 503
    assert client.post(BASE + "/knowledge/upload", data={"mpn": "M"},
                       files={"file": ("a.txt", b"hello")}).status_code == 422
    assert client.post(BASE + "/knowledge/search", json={"query": "a"}).status_code == 503
    assert client.get(BASE + "/knowledge/stats").status_code == 503
    monkeypatch.setattr(dependencies, "get_review_engine", lambda: None)
    assert client.get(BASE + "/review/rules").status_code == 503


def test_upload_text_validation_and_partial(monkeypatch):
    class Router:
        def upload_document(self, file_path, mpn, category, source):
            from agent_system.knowledge_router import KnowledgeRouter
            return KnowledgeRouter.upload_document(self, file_path, mpn, category, source)

        def import_text_knowledge(self, mpn, pages):
            return sum(bool(v.strip()) for v in pages.values())

    seen = []
    def owned_router(**kw):
        seen.append(kw)
        return Router()
    monkeypatch.setattr(dependencies, "get_knowledge_router", owned_router)
    def upload(name, content, mpn="M"):
        return client.post(BASE + "/knowledge/upload", data={"mpn": mpn, "project_id": "A"},
                           files={"file": (name, content)})

    assert upload("a.txt", b"hello").json()["data"]["chunk_count"] == 1
    assert seen[-1] == {"project_id": "A", "shared": False}
    assert client.post(BASE + "/knowledge/upload",
                       data={"mpn": "M", "scope": "shared"},
                       files={"file": ("shared.txt", b"hello")}).status_code == 200
    assert seen[-1] == {"project_id": None, "shared": True}
    assert client.post(BASE + "/knowledge/upload", data={"mpn": "M"},
                       files={"file": ("unowned.txt", b"hello")}).status_code == 422
    assert client.post(BASE + "/knowledge/upload",
                       data={"mpn": "M", "project_id": "A", "scope": "shared"},
                       files={"file": ("ambiguous.txt", b"hello")}).status_code == 422
    import fitz
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "hello")
    assert upload("a.pdf", pdf.tobytes()).json()["data"]["chunk_count"] == 1
    pdf.close()
    assert upload("a.txt", b"").status_code == 400
    assert upload("a.txt", b"\xff").status_code == 400
    assert upload("a.pdf", b"not pdf").status_code == 400
    assert upload("a.csv", b"hello").status_code == 400
    assert upload("a.txt", b"hello", mpn=" ").status_code == 422
    class Partial(Router):
        def import_text_knowledge(self, mpn, pages):
            return 0
    monkeypatch.setattr(dependencies, "get_knowledge_router", lambda **kw: Partial())
    assert upload("a.txt", b"hello").status_code == 503
    monkeypatch.setattr(dependencies, "get_knowledge_router",
                        lambda **kw: SimpleNamespace(upload_document=lambda **params:
                                                (_ for _ in ()).throw(
                                                    RuntimeError("/private/index: connection lost"))))
    unavailable = upload("a.txt", b"hello")
    assert unavailable.status_code == 503
    assert "/private/" not in unavailable.json()["detail"]


def test_normal_manager_status_and_saved_rules(monkeypatch, tmp_path):
    from agent_system.hitl_workflow import HITLManager, PendingReview

    class Session:
        status = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def run(self, query, params):
            if "RETURN pr.review_id" in query:
                self.status = params["status"]
            return SimpleNamespace(single=lambda: {"review_id": "id"})

    session = Session()
    manager = HITLManager()
    manager._driver = SimpleNamespace(session=lambda: session)
    manager.RULES_DIR = str(tmp_path)
    manager.CUSTOM_RULES_FILE = str(tmp_path / "custom_rules.yaml")
    manager._pending = [PendingReview(review_id="id", rule_id="R1",
                                      rule_name="Rule", refdes="U1")]
    assert manager.approve("id")
    assert session.status == "approved"
    result = manager.save_approved_rules()
    assert result["saved"] == 1
    assert result["location"] == manager.CUSTOM_RULES_FILE
    assert (tmp_path / "custom_rules.yaml").exists()
    assert manager.save_approved_rules()["saved"] == 0


def test_system_observability_and_openapi(monkeypatch):
    system.record_agent_query("review", 2, 17, "success")
    stats = system.get_agent_stats()
    assert stats.query_count >= 1
    assert stats.recent_queries[0].tool_calls == 2
    assert stats.token_usage is None
    schema = client.get("/openapi.json").json()
    action = schema["paths"][BASE + "/hitl/action"]["post"]
    ref = action["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ReviewActionResponse")
    data = schema["components"]["schemas"]["ReviewActionData"]["properties"]
    assert data["results"]["items"]["$ref"].endswith("/ReviewActionResult")
    assert "422" in action["responses"]
    assert "location" in schema["components"]["schemas"]["ExportResult"]["properties"]


def test_system_unavailable_data_not_fabricated(monkeypatch):
    import agent_system.connection_pool as pool
    import chromadb

    monkeypatch.setattr(pool, "get_neo4j_driver", lambda: None)
    monkeypatch.setattr(pool, "get_ollama_client", lambda: None)
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: SimpleNamespace(
        heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("offline"))))
    result = client.get(BASE + "/system/status")
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["data_stats"]["status"] == "unavailable"
    assert data["data_stats"]["components"] is None
    assert data["agent_stats"]["token_usage"] is None
    assert data["agent_stats"]["status"] == "degraded"
    assert all("/" not in (s.get("message") or "") for s in data["services"])


def test_chat_http_success_failure_and_ws_stats(monkeypatch):
    monkeypatch.setattr(chat, "_run_agent", lambda message, task_type, project_id=None: {
        "status": "success", "task_type": task_type, "report": "ok",
        "execution_trace": [], "tool_call_count": 2})
    before = system.get_agent_stats().query_count
    response = client.post(BASE + "/chat", json={"message": "hello", "task_type": "query"})
    assert response.status_code == 200
    assert response.json()["data"]["tool_call_count"] == 2
    assert client.post(BASE + "/chat", json={"message": " "}).status_code == 422
    assert client.post(BASE + "/chat", json={"message": "hello", "task_type": "other"}).status_code == 422
    assert client.post(BASE + "/chat", json={"message": "hello", "project_id": " "}).status_code == 422
    assert system.get_agent_stats().query_count == before + 1

    class FakeAgent:
        def run(self, message, task_type, project_id=None):
            return {"report": "ws ok", "task_type": task_type, "tool_call_count": 1}

    monkeypatch.setitem(sys.modules, "agent_system.react_agent",
                        SimpleNamespace(ReActAgent=FakeAgent))
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "chat", "payload": {"message": "hello", "task_type": "query"}})
        assert ws.receive_json()["type"] == "result"
    stats = system.get_agent_stats()
    assert stats.query_count == before + 2
    assert stats.recent_queries[0].task_type.startswith("ws:")

    def unavailable(*args):
        raise RuntimeError("offline")
    monkeypatch.setattr(chat, "_run_agent", unavailable)
    assert client.post(BASE + "/chat", json={"message": "hello"}).status_code == 500


def test_hitl_pending_fields_and_datasheet_persist(monkeypatch):
    from agent_system.hitl_workflow import PendingReview
    import agent_system.datasheet_hitl as datasheet

    item = PendingReview(review_id="one", rule_id="RULE", rule_name="Real rule",
                         refdes="U1", net_name="VCC", description="bad",
                         review_comment="note", created_at="2026-01-01")
    monkeypatch.setattr(hitl, "get_hitl_manager",
                        lambda: SimpleNamespace(get_pending_list=lambda status: [item]))
    response = client.get(BASE + "/hitl/pending")
    assert response.status_code == 200
    assert response.json()["data"][0]["rule_id"] == "RULE"
    assert response.json()["data"][0]["review_comment"] == "note"
    assert client.get(BASE + "/hitl/pending?page=0").status_code == 422
    monkeypatch.setattr(datasheet, "DatasheetHITLManager",
                        lambda: SimpleNamespace(get_pending_list=lambda: [],
                                                save_approved_to_amr=lambda: {"saved": 0}))
    assert client.get(BASE + "/hitl/datasheet/pending").json()["total"] == 0
    assert client.post(BASE + "/hitl/datasheet/persist").json()["data"]["saved"] == 0
    monkeypatch.setattr(datasheet, "DatasheetHITLManager",
                        lambda: SimpleNamespace(save_approved_to_amr=lambda: {
                            "saved": 0, "message": "保存失败: failed"}))
    assert client.post(BASE + "/hitl/datasheet/persist").status_code == 500


def test_knowledge_search_stats_and_invalid(monkeypatch):
    fake = SimpleNamespace(
        search=lambda **kw: {"status": "not_found", "tier": "none",
                             "source": "", "content": "", "confidence": 0},
        get_stats=lambda: {"tier1_chunks": 3, "tier2_enabled": False, "tier3_enabled": False},
    )
    seen = []
    def owned_router(**kw):
        seen.append(kw)
        return fake
    monkeypatch.setattr(dependencies, "get_knowledge_router", owned_router)
    response = client.post(BASE + "/knowledge/search", json={"query": "MPN"})
    assert response.status_code == 200
    assert seen[-1] == {"project_id": None}
    assert client.post(BASE + "/knowledge/search",
                       json={"query": "MPN", "project_id": "A"}).status_code == 200
    assert seen[-1] == {"project_id": "A"}
    assert response.json()["data"]["status"] == "not_found"
    assert client.get(BASE + "/knowledge/stats").json()["data"]["tier1_chunks"] == 3
    assert client.post(BASE + "/knowledge/search", json={"query": " "}).status_code == 422
    assert client.post(BASE + "/knowledge/search",
                       json={"query": "MPN", "max_results": 0}).status_code == 422
    fake.get_stats = lambda: (_ for _ in ()).throw(RuntimeError("/private/chroma"))
    unavailable = client.get(BASE + "/knowledge/stats")
    assert unavailable.status_code == 503
    assert "/private/" not in unavailable.json()["detail"]


def test_review_rules_and_summary(monkeypatch):
    engine = SimpleNamespace(
        config_manager=SimpleNamespace(list_rules=lambda enabled_only: [{
            "id": "R1", "name": "Rule", "template_id": "T",
            "severity": "WARNING", "enabled": True}]),
        run_rules=lambda **kw: [{"rule_id": "R1", "rule_name": "Rule",
                                 "refdes": "U1", "description": "bad",
                                 "severity": "WARNING"}],
    )
    monkeypatch.setattr(dependencies, "get_review_engine", lambda: engine)
    assert client.get(BASE + "/review/rules").json()["data"][0]["id"] == "R1"
    result = client.post(BASE + "/review/run", json={})
    assert result.status_code == 200
    assert result.json()["data"]["summary"]["by_rule"] == {"R1": 1}
    engine.run_rules = lambda **kw: []
    assert client.post(BASE + "/review/run", json={}).json()["data"]["summary"]["total"] == 0
    assert client.post(BASE + "/review/run", json={"enabled_only": "invalid"}).status_code == 422
    assert client.post(BASE + "/review/run", json={"project_id": "A"}).status_code == 503
    assert client.post(BASE + "/review/run", json={"project_id": " "}).status_code == 422
    monkeypatch.setattr(dependencies, "get_review_engine", lambda: None)
    assert client.post(BASE + "/review/run", json={}).status_code == 503


def test_graph_contract_without_live_graph(monkeypatch):
    fake = SimpleNamespace(
        _build_component_relation_dot=lambda **kw: 'digraph { U1 [label="U1"]; }',
        _build_power_chain_dot=lambda **kw: 'digraph {}',
        _build_fault_root_dot=lambda **kw: 'digraph {}',
        _build_common_cause_dot=lambda **kw: 'digraph {}',
        _build_power_tree_dot=lambda **kw: 'digraph {}',
    )
    monkeypatch.setitem(sys.modules, "web_ui.sub_pages.graph_viz", fake)
    response = client.post(BASE + "/graph/visualize", json={"mode": "component", "refdes": "U1"})
    assert response.status_code == 200
    assert response.json()["data"]["node_count"] == 1
    assert client.post(BASE + "/graph/visualize", json={"mode": "power_tree"}).status_code == 200
    for body in [{"mode": "component"}, {"mode": "invalid", "refdes": "U1"},
                 {"mode": "component", "refdes": "U1", "depth": 0}]:
        assert client.post(BASE + "/graph/visualize", json=body).status_code == 422


def test_projects_preview_run_and_progress_offline(monkeypatch, tmp_path):
    from agent_system import graph_tools, etl_web_bridge
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(graph_tools, "list_projects", lambda: ["isolated"])
    class FakeExecutor:
        def create_project(self, name):
            return {"project_id": name}
        def delete_project(self, name):
            return {"project_id": name, "deleted_nodes": "0"}
        def preview(self, paths):
            return {"success": True, "bom_enriched_components": 2}
        def run_etl(self, paths, name):
            return {"success": False, "quality_passed": False, "message": "quality failed"}
        def get_progress(self, job_id):
            return {"step": "completed", "progress": 100,
                    "message": f"job {job_id} is not tracked asynchronously"}
    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", FakeExecutor)
    assert client.get(BASE + "/etl/projects").json()["data"] == ["isolated"]
    assert client.post(BASE + "/etl/projects",
                       json={"project_name": "isolated"}).json()["data"]["project_id"] == "isolated"
    assert client.delete(BASE + "/etl/projects/isolated").json()["data"]["deleted_nodes"] == "0"
    assert client.post(BASE + "/etl/projects", json={"project_name": " "}).status_code == 422
    assert client.delete(BASE + "/etl/projects/%20").status_code == 422
    assert client.get(BASE + "/etl/progress/unknown").status_code == 404

    # Uploads are staged to unique temporary paths independent of client filenames.
    def files():
        return {key: (f"{uuid.uuid4().hex}.{key}", b"fixture")
                for key in ("pstxnet", "pstxprt", "pstchip")}
    preview = client.post(BASE + "/etl/preview", files=files())
    assert preview.status_code == 200
    assert preview.json()["data"]["bom_enriched_components"] == 2
    run = client.post(BASE + "/etl/run", data={"project_name": "isolated"}, files=files())
    assert run.status_code == 200
    assert run.json()["success"] is True  # accepted, not a completed import
    from hardware_ai_expert.tests.test_task4_etl_jobs import wait_for
    assert wait_for(run.json()["job_id"])["status"] == "failed"
    assert client.post(BASE + "/etl/preview").status_code == 422
    FakeExecutor.preview = lambda self, paths: {"success": False, "error": "/tmp/secret"}
    failed = client.post(BASE + "/etl/preview", files=files())
    assert failed.status_code == 200 and failed.json()["success"] is False
    assert "/tmp/" not in failed.json()["message"]
    assert client.post(BASE + "/etl/run", data={"project_name": " "},
                       files=files()).status_code == 422


def test_openapi_all_core_router_responses():
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        ("post", "/chat"): "ChatResponse",
        ("get", "/review/rules"): "RulesListResponse",
        ("post", "/review/run"): "ReviewResponse",
        ("get", "/hitl/pending"): "PendingListResponse",
        ("post", "/hitl/action"): "ReviewActionResponse",
        ("post", "/hitl/export"): "ExportResponse",
        ("get", "/hitl/datasheet/pending"): "DatasheetPendingListResponse",
        ("post", "/hitl/datasheet/action"): "ReviewActionResponse",
        ("post", "/hitl/datasheet/persist"): "DatasheetPersistResponse",
        ("post", "/knowledge/upload"): "UploadResponse",
        ("post", "/knowledge/search"): "SearchResponse",
        ("get", "/knowledge/stats"): "KnowledgeStatsResponse",
        ("get", "/etl/projects"): "ProjectListResponse",
        ("post", "/etl/projects"): "ProjectActionResponse",
        ("delete", "/etl/projects/{project_name}"): "ProjectActionResponse",
        ("post", "/etl/preview"): "ETLPreviewResponse",
        ("post", "/etl/run"): "ETLResponse",
        ("get", "/etl/progress/{job_id}"): "ETLProgress",
        ("post", "/graph/visualize"): "GraphResponse",
        ("get", "/system/status"): "SystemStatusResponse",
    }
    for (method, path), model in expected.items():
        response = paths[BASE + path][method]["responses"]["200"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/" + model)


def test_expected_http_errors_are_not_wrapped(monkeypatch):
    from fastapi import HTTPException
    from agent_system import etl_web_bridge
    from agent_system import graph_tools
    def unavailable(*args, **kwargs):
        raise HTTPException(status_code=503, detail="test dependency unavailable")

    monkeypatch.setattr(graph_tools, "list_projects", unavailable)
    assert client.get(BASE + "/etl/projects").status_code == 503
    monkeypatch.setattr(dependencies, "get_review_engine",
                        lambda: SimpleNamespace(run_rules=unavailable))
    assert client.post(BASE + "/review/run", json={}).status_code == 503
    fake = SimpleNamespace(
        _build_component_relation_dot=unavailable,
        _build_power_chain_dot=unavailable, _build_fault_root_dot=unavailable,
        _build_common_cause_dot=unavailable, _build_power_tree_dot=unavailable)
    monkeypatch.setitem(sys.modules, "web_ui.sub_pages.graph_viz", fake)
    assert client.post(BASE + "/graph/visualize",
                       json={"mode": "component", "refdes": "U1"}).status_code == 503
    class FakeExecutor:
        def get_progress(self, job_id):
            raise HTTPException(status_code=404, detail="unknown")
    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", FakeExecutor)
    assert client.get(BASE + "/etl/progress/unknown").status_code == 404


def test_system_available_stats_use_observed_counts(monkeypatch):
    import chromadb
    import agent_system.connection_pool as pool

    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def run(self, query):
            if query == "RETURN 1":
                return SimpleNamespace(single=lambda: {"value": 1})
            if "sum(CASE" in query:
                return SimpleNamespace(single=lambda: {"comps": 2, "unknown": 1})
            if "(p:Pin)" in query:
                return SimpleNamespace(single=lambda: {"c": 4})
            if "(n:Net)" in query:
                return SimpleNamespace(single=lambda: {"c": 3})
            return SimpleNamespace(data=lambda: [{"pt": "UNKNOWN", "c": 1},
                                                 {"pt": "IC", "c": 1}])

    monkeypatch.setattr(pool, "get_neo4j_driver",
                        lambda: SimpleNamespace(session=Session))
    monkeypatch.setattr(pool, "get_ollama_client",
                        lambda: SimpleNamespace(list=lambda: []))
    monkeypatch.setattr(chromadb, "HttpClient",
                        lambda **kw: SimpleNamespace(heartbeat=lambda: 1))
    response = client.get(BASE + "/system/status")
    assert response.status_code == 200
    stats = response.json()["data"]["data_stats"]
    assert stats["status"] == "available"
    assert (stats["components"], stats["pins"], stats["nets"]) == (2, 4, 3)
    assert stats["part_type_coverage"] == 50.0
