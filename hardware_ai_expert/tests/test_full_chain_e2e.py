"""Single end-to-end test chaining the full product path:

  netlist+BOM upload -> ETL run -> quality-gated project replace ->
  review run (violations) -> HITL pending queue -> approve -> persist
  to custom_rules.yaml -> reload and confirm the custom rule is visible.

Every other API test file exercises one or two stages of this chain in
isolation (test_task12_api_e2e.py: upload->ETL->review; test_task12_coverage_gaps.py
and test_hitl_neo4j_integration.py: HITL alone). This file is the one
that walks all the way through, end to end, in a single test, matching
what docs/product/PRD_GAP_ANALYSIS_V2.md flags as still missing.

No production graph, Chroma, PLM, Ollama, or external network access is
used -- Neo4j writes go through a fake in-memory HITLManager driver and
a fake ETL loader, exactly like test_task12_api_e2e.py's `isolated`
fixture, so this is safe to run in any environment including CI.
"""
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from agent_system import etl_web_bridge
from agent_system.hitl_workflow import HITLManager, PendingReview
from hardware_ai_expert.api import dependencies
from hardware_ai_expert.api.main import app
from hardware_ai_expert.tests.test_task5_safe_import import BOM, CHIP, NET, PRT


BASE = "/api/v1"


class _FakeSession:
    def __init__(self, records):
        self._records = records

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, params=None, **kwargs):
        params = params or {}

        class _Result:
            def __init__(self, row=None):
                self._row = row

            def single(self):
                return self._row

            def __iter__(self):
                return iter(())

        if "MERGE" in query:
            rid = params["review_id"]
            self._records[rid] = {
                "status": "pending", "scope": params["scope"],
                "project_id": params["project_id"],
            }
            return _Result()
        if "status: 'pending'" in query:
            rid = params["review_id"]
            record = self._records.get(rid)
            if record is None or record["status"] != "pending":
                return _Result()
            record["status"] = params["status"]
            record["reviewer"] = params["reviewer"]
            record["review_comment"] = params["comment"]
            return _Result({"review_id": rid})
        if "SET pr.status = 'persisted'" in query:
            rid = params["review_id"]
            if rid in self._records and self._records[rid]["status"] == "approved":
                self._records[rid]["status"] = "persisted"
            return _Result()
        return _Result()


class _FakeDriver:
    def __init__(self):
        self.records = {}

    def session(self):
        return _FakeSession(self.records)

    def close(self):
        pass


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Wire every stage of the pipeline to fakes/fixtures, like
    test_task12_api_e2e.py's `isolated`, but also stand up a real
    (in-memory-backed) HITLManager so approve/persist is genuinely
    exercised end to end rather than mocked at the router boundary."""
    monkeypatch.setenv("ETL_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        GraphDatabase, "driver",
        lambda *a, **kw: pytest.fail("unexpected live Neo4j connection"),
    )

    import agent_system.knowledge_router as kr
    monkeypatch.setattr(
        kr, "_get_chroma_client",
        lambda: pytest.fail("unexpected live Chroma connection"),
    )

    records = {}

    class Executor(etl_web_bridge.ETLWebExecutor):
        def _load_to_neo4j(self, components, topology, project_id="default"):
            records[project_id] = dict(components)
            return {"components": len(components), "nets": 2}

    monkeypatch.setattr(etl_web_bridge, "ETLWebExecutor", Executor)

    violations_by_project = {}

    def review_engine(project_id=None):
        def run_rules(**kwargs):
            comps = records.get(project_id or "fixture-board", {})
            assert "U1" in comps
            violations = [
                {
                    "rule_id": "DECAP-001",
                    "rule_name": "Missing decoupling capacitor",
                    "refdes": "U1",
                    "net_name": "VCC_3V3",
                    "description": "U1 lacks a nearby decoupling capacitor",
                    "severity": "WARNING",
                    "expected": ">=1 decap within 5mm",
                    "actual": "0 found",
                    "suggested_fix": "Add 100nF X7R near U1 pin 1",
                }
            ]
            violations_by_project[project_id] = violations
            return violations

        return SimpleNamespace(run_rules=run_rules)

    monkeypatch.setattr(dependencies, "get_review_engine", review_engine)

    rules_dir = tmp_path / "rules_config"
    hitl_manager = HITLManager(shared=True)
    fake_driver = _FakeDriver()
    monkeypatch.setattr(hitl_manager, "_get_driver", lambda: fake_driver)
    monkeypatch.setattr(hitl_manager, "RULES_DIR", str(rules_dir))
    monkeypatch.setattr(hitl_manager, "CUSTOM_RULES_FILE", str(rules_dir / "custom_rules.yaml"))
    monkeypatch.setattr(
        "hardware_ai_expert.api.routers.hitl.get_hitl_manager",
        lambda: hitl_manager,
    )

    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, records=records, tmp_path=tmp_path,
            hitl_manager=hitl_manager, rules_dir=rules_dir,
        )


def fixture_files():
    return {
        "pstxnet": ("sample.dat", NET.encode()),
        "pstxprt": ("sample.dat", PRT.encode()),
        "pstchip": ("sample.dat", CHIP.encode()),
        "bom": ("sample.csv", BOM.encode()),
    }


def wait_for_etl(client, job_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = client.get(f"{BASE}/etl/progress/{job_id}")
        assert result.status_code == 200
        if result.json()["status"] not in ("queued", "running"):
            return result.json()
        sleep(0.02)
    pytest.fail("ETL job did not finish")


@pytest.mark.e2e
def test_netlist_bom_etl_review_hitl_approve_persist_full_chain(pipeline):
    """The full chain, step by step, each assertion checking that stage's
    contract before moving to the next -- a failure anywhere identifies
    exactly which stage of the pipeline broke."""
    client = pipeline.client

    # Stage 1: ETL preview -- BOM-enriched component count before committing.
    preview = client.post(BASE + "/etl/preview", files=fixture_files())
    assert preview.status_code == 200
    preview_data = preview.json()["data"]
    assert preview_data["bom_enriched_components"] == 2

    # Stage 2: ETL run -- async job, poll until terminal, then verify the
    # graph loader actually received the BOM-merged components.
    accepted = client.post(
        BASE + "/etl/run", files=fixture_files(),
        data={"project_name": "fixture-board"},
    )
    assert accepted.status_code == 200
    job_id = accepted.json()["job_id"]
    assert accepted.json()["status"] == "queued"

    job = wait_for_etl(client, job_id)
    assert job["status"] == "succeeded"
    assert job["result"]["quality_passed"] is True
    assert set(pipeline.records["fixture-board"]) == {"U1", "C1"}
    assert pipeline.records["fixture-board"]["U1"]["MPN"] == "DEMO-MCU"

    # Stage 3: Review run -- the loaded project produces a violation.
    review = client.post(BASE + "/review/run", json={"project_id": "fixture-board"})
    assert review.status_code == 200
    review_data = review.json()["data"]
    assert review_data["summary"]["total"] == 1
    assert review_data["summary"]["by_rule"] == {"DECAP-001": 1}
    violation = review_data["violations"][0]
    assert violation["refdes"] == "U1"
    assert violation["rule_id"] == "DECAP-001"

    # Stage 4: violation enters the HITL pending queue (this is the part of
    # the chain production code wires through HITLManager.add_violations;
    # here we drive it explicitly to prove the schema HITL expects matches
    # what review/run actually returns).
    pending_review = PendingReview(
        review_id="",
        rule_id=violation["rule_id"],
        rule_name=violation["rule_name"],
        refdes=violation["refdes"],
        net_name=violation.get("net_name") or "",
        description=violation["description"],
        severity=violation["severity"],
        expected=violation.get("expected") or "",
        actual=violation.get("actual") or "",
        suggested_fix=violation.get("suggested_fix") or "",
    )
    assert pipeline.hitl_manager.add_pending(pending_review)
    review_id = pending_review.review_id
    assert review_id

    pending_list = client.get(BASE + "/hitl/pending")
    assert pending_list.status_code == 200
    pending_data = pending_list.json()
    assert pending_data["total"] == 1
    assert pending_data["data"][0]["review_id"] == review_id
    assert pending_data["data"][0]["refdes"] == "U1"

    # Stage 5: approve via the API (not the manager directly), proving the
    # action endpoint and the manager singleton returned by get_hitl_manager
    # share the same in-memory state.
    action = client.post(BASE + "/hitl/action", json={
        "review_ids": [review_id], "action": "approve",
        "reviewer": "qa", "comment": "confirmed on silkscreen",
    })
    assert action.status_code == 200
    action_data = action.json()["data"]
    assert action_data["succeeded"] == 1 and action_data["failed"] == 0
    assert action_data["results"][0]["success"] is True

    # Approved items leave the pending queue.
    pending_after = client.get(BASE + "/hitl/pending")
    assert pending_after.json()["total"] == 0

    # Stage 6: persist the approved rule to custom_rules.yaml via /hitl/export.
    export = client.post(BASE + "/hitl/export", json={})
    assert export.status_code == 200
    export_data = export.json()["data"]
    assert export_data["saved"] == 1
    assert export_data["rules"] == ["DECAP-001"]
    assert export_data["location"] == "custom_rules.yaml"

    # Stage 7: the YAML written to disk actually contains the approved rule
    # with the original violation's evidence, independent of the API layer.
    custom_rules_path = pipeline.rules_dir / "custom_rules.yaml"
    assert custom_rules_path.exists()
    saved_rules = yaml.safe_load(custom_rules_path.read_text(encoding="utf-8"))
    assert saved_rules["DECAP-001"]["name"] == "Missing decoupling capacitor"
    assert saved_rules["DECAP-001"]["examples"][0]["refdes"] == "U1"
    assert saved_rules["DECAP-001"]["examples"][0]["net_name"] == "VCC_3V3"

    # A second export with nothing newly approved reports zero, not an error.
    export_again = client.post(BASE + "/hitl/export", json={})
    assert export_again.status_code == 200
    assert export_again.json()["data"]["saved"] == 0

    # No staged upload files are left behind by any stage of the chain.
    assert list((pipeline.tmp_path / "uploads").rglob("hardware-upload-*")) == []
