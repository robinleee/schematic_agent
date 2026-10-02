"""Offline API product paths: real parsing/quality, fake project store and review.

No production graph, Chroma, PLM, Ollama, or external HTTP may be contacted.
"""

from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from agent_system import etl_web_bridge
from hardware_ai_expert.api import dependencies
from hardware_ai_expert.api.main import app
from hardware_ai_expert.tests.test_task5_safe_import import BOM, CHIP, NET, PRT


BASE = "/api/v1"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        GraphDatabase,
        "driver",
        lambda *a, **kw: pytest.fail("unexpected live Neo4j connection"),
    )
    import agent_system.knowledge_router as kr

    monkeypatch.setattr(
        kr,
        "_get_chroma_client",
        lambda: pytest.fail("unexpected live Chroma connection"),
    )
    records = {}

    class Executor(etl_web_bridge.ETLWebExecutor):
        def _load_to_neo4j(self, components, topology, project_id="default"):
            records[project_id] = dict(components)
            return {"components": len(components), "nets": 2}

    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", Executor)

    def review_engine():
        def run_rules(**kwargs):
            assert kwargs["enabled_only"] is True
            assert records["fixture-board"]["U1"]["MPN"] == "DEMO-MCU"
            return [
                {
                    "rule_id": "TEST-1",
                    "rule_name": "Fixture check",
                    "refdes": "U1",
                    "description": "Missing decoupling",
                    "severity": "WARNING",
                }
            ]

        return SimpleNamespace(run_rules=run_rules)

    monkeypatch.setattr(dependencies, "get_review_engine", review_engine)
    with TestClient(app) as client:
        yield client, records, tmp_path


def fixture_files(net=NET):
    return {
        "pstxnet": ("sample.dat", net.encode()),
        "pstxprt": ("sample.dat", PRT.encode()),
        "pstchip": ("sample.dat", CHIP.encode()),
        "bom": ("sample.csv", BOM.encode()),
    }


def completed(client, job_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = client.get(f"{BASE}/etl/progress/{job_id}")
        assert result.status_code == 200
        if result.json()["status"] not in ("queued", "running"):
            return result.json()
        sleep(0.02)
    pytest.fail("ETL job did not finish")


@pytest.mark.e2e
def test_import_preview_then_review_happy_path(isolated):
    client, records, tmp_path = isolated
    preview = client.post(BASE + "/etl/preview", files=fixture_files())
    assert preview.status_code == 200
    assert preview.json()["data"]["bom_enriched_components"] == 2
    accepted = client.post(
        BASE + "/etl/run", files=fixture_files(), data={"project_name": "fixture-board"}
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "queued"
    job = completed(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded" and job["result"]["quality_passed"]
    assert set(records["fixture-board"]) == {"U1", "C1"}
    review = client.post(BASE + "/review/run", json={})
    assert review.status_code == 200
    assert review.json()["data"]["summary"]["by_rule"] == {"TEST-1": 1}
    assert list((tmp_path / "uploads").rglob("hardware-upload-*")) == []


@pytest.mark.e2e
def test_bad_quality_cannot_replace_project_and_errors_are_bounded(isolated):
    client, records, tmp_path = isolated
    records["fixture-board"] = {"old": "untouched"}
    bad_net = NET.replace("NODE_NAME C1 2", "")
    preview = client.post(BASE + "/etl/preview", files=fixture_files(bad_net))
    assert preview.status_code == 200
    accepted = client.post(
        BASE + "/etl/run",
        files=fixture_files(bad_net),
        data={"project_name": "fixture-board"},
    )
    job = completed(client, accepted.json()["job_id"])
    assert job["status"] == "failed" and job["result"]["quality_passed"] is False
    assert records["fixture-board"] == {"old": "untouched"}
    assert client.get(BASE + "/etl/progress/missing").status_code == 404
    assert (
        client.post(
            BASE + "/etl/preview",
            files={
                **fixture_files(),
                "pstxnet": ("bad.exe", b"x"),
            },
        ).status_code
        == 400
    )
    assert (
        client.post(BASE + "/review/run", json={"project_id": "missing"}).status_code
        == 503
    )
    assert list((tmp_path / "uploads").rglob("hardware-upload-*")) == []


@pytest.mark.e2e
def test_knowledge_upload_ownership_cleanup_and_search_isolation(isolated, monkeypatch):
    """The API must never reuse one project's index for another or leak staged files."""
    client, _, tmp_path = isolated
    stores = {}

    class Router:
        def __init__(self, owner):
            self.owner = owner

        def upload_document(self, file_path, mpn, category, source):
            from pathlib import Path
            stores.setdefault(self.owner, {})[mpn] = Path(file_path).read_text()
            return {"chunk_count": 1, "mpn": mpn}

        def search(self, mpn, query, max_results):
            content = stores.get(self.owner, {}).get(mpn, "")
            return {"status": "success" if content else "not_found",
                    "tier": "Tier1" if content else "none", "content": content,
                    "source": "fixture", "confidence": 1 if content else 0,
                    "mpn": mpn}

    def get_router(project_id=None, shared=False):
        assert not (project_id and shared)
        return Router("shared" if shared else project_id)

    monkeypatch.setattr(dependencies, "get_knowledge_router", get_router)
    endpoint = BASE + "/knowledge"
    upload = lambda data: client.post(endpoint + "/upload",
                                      files={"file": ("note.txt", b"private specs")},
                                      data=data)
    for data in ({"mpn": "P"}, {"mpn": "P", "project_id": " "},
                 {"mpn": "P", "project_id": "A", "scope": "shared"}):
        assert upload(data).status_code == 422
    assert upload({"mpn": "P", "project_id": "A"}).json()["data"]["chunk_count"] == 1
    def search(owner):
        response = client.post(endpoint + "/search",
                               json={"mpn": "P", "query": "specs", "project_id": owner})
        assert response.status_code == 200
        return response.json()["data"]
    assert search("A")["content"] == "private specs"
    assert search("B")["status"] == "not_found"
    assert upload({"mpn": "P", "scope": "shared"}).status_code == 200
    assert search("B")["status"] == "not_found"  # no implicit shared fallback in fake
    assert client.post(endpoint + "/search", json={
        "query": "specs", "project_id": " "}).status_code == 422
    assert list((tmp_path / "uploads").rglob("hardware-upload-*")) == []


@pytest.mark.e2e
def test_hitl_batch_actions_report_partial_failure_and_validate_ids(isolated, monkeypatch):
    client, _, _ = isolated
    calls = []

    class Manager:
        def approve(self, rid, reviewer, comment):
            calls.append((rid, reviewer, comment))
            if rid == "broken":
                raise RuntimeError("fake update failed")
            return rid == "ok"

    monkeypatch.setattr("hardware_ai_expert.api.routers.hitl.get_hitl_manager",
                        lambda: Manager())
    endpoint = BASE + "/hitl/action"
    for ids in (["ok", "ok"], [" "], []):
        assert client.post(endpoint, json={
            "review_ids": ids, "action": "approve"}).status_code == 422
    response = client.post(endpoint, json={
        "review_ids": ["ok", "missing", "broken"], "action": "approve",
        "reviewer": "tester", "comment": "checked"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["data"]["succeeded"] == 1 and data["data"]["failed"] == 2
    assert [item["success"] for item in data["data"]["results"]] == [True, False, False]
    assert data["data"]["results"][1]["error"] == "Review not pending or update failed"
    assert data["data"]["results"][2]["error"] == "fake update failed"
    assert calls == [(rid, "tester", "checked") for rid in ("ok", "missing", "broken")]
