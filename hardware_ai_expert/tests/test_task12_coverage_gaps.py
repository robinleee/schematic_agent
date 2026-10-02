"""Task 12 offline branch coverage for graph, HITL, review, and ETL boundaries."""

from io import BytesIO
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_system import graph_tools
from agent_system.hitl_workflow import HITLManager, PendingReview
from agent_system.review_engine.engine import ReviewRuleEngine
from agent_system.review_engine.templates.base import RuleContext, _scope_review_query
from hardware_ai_expert.api.routers.etl import _etl_result
from hardware_ai_expert.api.services import uploads
from hardware_ai_expert.api.services.etl_jobs import JobStore


class _Session:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, params=None):
        self.calls.append((query, params or {}))
        return list(self.rows)


class _Driver:
    def __init__(self, rows=None):
        self.session_obj = _Session(rows)

    def session(self):
        return self.session_obj


@pytest.mark.unit
def test_power_tree_root_and_voltage_reports_use_expected_records(monkeypatch):
    monkeypatch.setattr(graph_tools, "get_current_project", lambda: "board-a")
    calls = []

    def run(query, params=None):
        calls.append((query, params))
        if "RETURN n.Name AS power_net" in query:
            return [{"power_net": "VDD_1V8", "voltage": "1.8",
                     "loads": [{"refdes": "U2", "part_type": "LDO", "model": "LDO-X"}],
                     "load_count": 1}]
        if "RETURN c.PartType AS pt" in query:
            return [{"pt": "PMIC", "model": "PMIC-X"}]
        return [{"net_name": "VDD_1V8", "devices": [
            {"refdes": "U2", "part_type": "LDO"}], "device_count": 1}]

    monkeypatch.setattr(graph_tools, "_run_cypher", run)
    root = graph_tools.get_power_tree.invoke({"root_refdes": "U1"})
    assert "U1 [PMIC] PMIC-X" in root
    assert "下级电源: U2" in root
    voltage = graph_tools.get_power_tree.invoke({"voltage": "1V8"})
    assert "电压 1V8 的电源树" in voltage
    assert any(params["project_id"] == "board-a" for _, params in calls if params)


@pytest.mark.unit
def test_common_cause_report_identifies_shared_single_point(monkeypatch):
    responses = {
        "direct": {
            "U2": [{"parent": "U1", "voltage": "3.3", "net": "VDD_3V3"}],
            "U3": [{"parent": "U1", "voltage": "3.3", "net": "VDD_3V3"}],
        },
        "path": {
            "U2": [{"ancestors": ["U1"], "edges": [{"voltage": "3.3", "net": "VDD_3V3"}]}],
            "U3": [{"ancestors": ["U1"], "edges": [{"voltage": "3.3", "net": "VDD_3V3"}]}],
        },
    }

    def run(query, params=None):
        if "RETURN p.RefDes AS parent" in query:
            return responses["direct"][params["refdes"]]
        if "RETURN [n IN nodes(path)" in query:
            return responses["path"][params["refdes"]]
        return [{"refdes": "U1", "pt": "PMIC", "model": "PMIC-X"}]

    monkeypatch.setattr(graph_tools, "_run_cypher", run)
    report = graph_tools.find_common_cause.invoke({"refdes_list": "U2,U3"})
    assert "共同上游电源节点" in report
    assert "U1" in report and "单点故障" in report
    assert "U2" in report and "U3" in report


@pytest.mark.unit
def test_trace_signal_path_finds_active_peer_and_skips_ground(monkeypatch):
    def run(query, params=None):
        if "WHERE p.Number = $pin_num" in query:
            return [{"refdes": "U1", "pt": "MCU", "pin_num": "1",
                     "pin_name": "SDA", "pid": 10}]
        if "WHERE id(p) = $pid" in query:
            return [{"net_name": "I2C_SDA", "nid": 20},
                    {"net_name": "GND", "nid": 21}]
        if "WHERE id(p) <> $pid" in query:
            return [{"refdes": "U2", "pt": "IC", "pin_num": "4",
                     "pin_name": "SDA", "peer_pid": 11}]
        return []

    monkeypatch.setattr(graph_tools, "_run_cypher", run)
    result = graph_tools.trace_signal_path.invoke({"start_pin": "U1.1", "max_depth": 2})
    assert "主动器件链路" in result
    assert "U2[IC]" in result
    assert "I2C" in result
    assert "Net:GND" not in result


@pytest.mark.unit
def test_hitl_requires_explicit_scope_and_does_not_queue_failed_save(monkeypatch):
    review = PendingReview("r1", "rule", "Rule", "U1")
    with pytest.raises(ValueError, match="project_id or shared"):
        HITLManager().add_pending(review)

    manager = HITLManager(project_id="board-a")
    monkeypatch.setattr(manager, "_get_driver", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert manager.add_pending(PendingReview("r2", "rule", "Rule", "U1")) is False
    assert manager.get_pending_list("all") == []


@pytest.mark.unit
def test_hitl_save_groups_approved_reviews_and_marks_persisted(tmp_path, monkeypatch):
    manager = HITLManager(shared=True)
    manager.RULES_DIR = str(tmp_path)
    manager.CUSTOM_RULES_FILE = str(tmp_path / "custom.yaml")
    manager._pending = [
        PendingReview("a", "R1", "Rule 1", "U1", net_name="VCC",
                      expected="1", actual="0", status="approved"),
        PendingReview("b", "R1", "Rule 1", "U2", net_name="VCC",
                      expected="1", actual="0", status="approved"),
        PendingReview("c", "R2", "Rule 2", "C1", status="rejected"),
    ]
    monkeypatch.setattr(manager, "_mark_persisted_in_neo4j", lambda ids: ids)
    result = manager.save_approved_rules()
    assert result["saved"] == 1
    assert result["rules"] == ["R1"]
    assert manager._pending[0].status == "persisted"
    assert "U1" in (tmp_path / "custom.yaml").read_text(encoding="utf-8")


@pytest.mark.unit
def test_review_query_scoping_handles_multiple_match_clauses_and_rejects_writes():
    query = (
        "MATCH (a:Component)-[:HAS_PIN]->(p:Pin) "
        "WHERE a.RefDes = $refdes "
        "OPTIONAL MATCH (p)-[:CONNECTS_TO]->(n:Net) "
        "RETURN a.RefDes, n.Name"
    )
    scoped = _scope_review_query(query)
    assert scoped.count("project_id = $project_id") == 4
    with pytest.raises(RuntimeError, match="writes"):
        _scope_review_query("MATCH (n:Net) SET n.x = 1 RETURN n")
    with pytest.raises(RuntimeError, match="no MATCH"):
        _scope_review_query("RETURN 1")


@pytest.mark.unit
def test_review_context_records_query_failures():
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, query, params):
            raise ConnectionError("offline")

    context = RuleContext(SimpleNamespace(session=lambda: BrokenSession()), project_id="A")
    with pytest.raises(ConnectionError):
        context.run_query("MATCH (n:Net) RETURN n")
    assert isinstance(context.infrastructure_error, ConnectionError)


@pytest.mark.unit
def test_review_engine_refuses_missing_driver_before_rules():
    engine = ReviewRuleEngine(None, config_path=None, auto_reload=False, project_id="A")
    with pytest.raises(RuntimeError, match="driver unavailable"):
        engine.run_rules()


@pytest.mark.unit
def test_etl_result_maps_quality_summary_and_safe_defaults():
    result = _etl_result({
        "success": True,
        "components_count": 4,
        "topology_count": 3,
        "parttype_coverage": 75.0,
        "quality_passed": True,
        "message": "done",
        "details": {"bom_issues": [{"field": "MPN", "message": "missing"}]},
        "quality_report": {
            "summary": {"total_components": 4},
            "pins": 8,
            "nets": 3,
            "part_type_coverage": 75.0,
            "passed": True,
        },
    })
    assert result.success is True
    assert result.quality_report.components == 4
    assert result.quality_report.pins == 8
    assert result.bom_issues == [{"field": "MPN", "message": "missing"}]
    failed = _etl_result({"success": False})
    assert failed.message == "ETL failed"
    assert failed.quality_passed is False


@pytest.mark.unit
def test_job_store_update_is_compare_and_set(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job_id = store.create("board-a")
    assert store.update(job_id, "running", "parsing", 5, "working") is True
    assert store.update(job_id, "succeeded", "completed", 100, "done",
                        result={"success": True}, expected=("queued",)) is False
    assert store.get(job_id)["status"] == "running"
    assert store.update(job_id, "succeeded", "completed", 100, "done",
                        result={"success": True}) is True
    assert store.get(job_id)["result"] == {"success": True}


@pytest.mark.unit
def test_upload_stage_rejects_extension_and_cleans_oversized_file(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(tmp_path))
    with pytest.raises(Exception) as invalid:
        asyncio.run(uploads.stage(UploadFile(filename="bad.exe", file=BytesIO(b"x")),
                                  {".dat"}, 10))
    assert getattr(invalid.value, "status_code", None) == 400
    with pytest.raises(Exception) as oversized:
        asyncio.run(uploads.stage(UploadFile(filename="x.dat", file=BytesIO(b"123")),
                                  {".dat"}, 2))
    assert getattr(oversized.value, "status_code", None) == 413
    assert not list(tmp_path.rglob("hardware-upload-*"))
