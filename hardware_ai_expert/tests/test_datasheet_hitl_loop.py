import sys
import hashlib
import os
import yaml
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

from agent_system.datasheet_hitl import DatasheetHITLManager, FileBasedAMRSource
from agent_system.datasheet_parser import ExtractedComponent, DatasheetParameter, ParamType, DatasheetParser
from api.routers.hitl import _run_actions
from api.schemas.hitl import DatasheetReviewActionRequest
from agent_system.hitl_workflow import HITLManager, PendingReview
from agent_system.review_engine.engine import RuleConfigManager


def test_datasheet_hitl_approve_and_persist_to_amr(tmp_path, monkeypatch):
    pending = tmp_path / "pending_datasheet_reviews.yaml"
    amr = tmp_path / "amr_data.yaml"
    monkeypatch.setattr(DatasheetHITLManager, "PENDING_FILE", str(pending))
    monkeypatch.setattr(DatasheetHITLManager, "AMR_DATA_FILE", str(amr))
    monkeypatch.setattr(DatasheetHITLManager, "AMR_DATA_DIR", str(tmp_path))

    manager = DatasheetHITLManager()
    component = ExtractedComponent(
        mpn="TESTCAP123",
        manufacturer="TestMfr",
        source_file="test.pdf",
        parameters=[
            DatasheetParameter(
                param_type=ParamType.CAP_VOLTAGE_RATING,
                name="Voltage rating",
                value=16.0,
                unit="V",
                confidence=0.95,
                source_text="Rated voltage 16 V",
            )
        ],
        extraction_method="unit-test",
    )

    review_ids = manager.add_extracted_component(component)
    assert len(review_ids) == 1
    assert len(manager.get_pending_list()) == 1

    assert manager.approve(review_ids[0], reviewer="qa", comment="ok") is True
    assert len(manager.get_approved_list()) == 1

    result = manager.save_approved_to_amr()
    assert result["saved"] == 1
    text = amr.read_text(encoding="utf-8")
    assert "TESTCAP123" in text
    assert "cap_voltage_rating" in text
    assert "16.0" in text


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    monkeypatch.setattr(DatasheetHITLManager, "PENDING_FILE", str(directory / "pending.yaml"))
    monkeypatch.setattr(DatasheetHITLManager, "AMR_DATA_FILE", str(directory / "amr_data.yaml"))
    monkeypatch.setattr(DatasheetHITLManager, "AMR_DATA_DIR", str(directory))
    monkeypatch.setattr(FileBasedAMRSource, "AMR_DATA_FILE", str(directory / "amr_data.yaml"))
    return directory


def test_batch_audit_and_restart(isolated):
    manager = DatasheetHITLManager()
    live_source = FileBasedAMRSource()
    component = ExtractedComponent(mpn="TESTCAP", source_file="cap.pdf", parameters=[
        DatasheetParameter(ParamType.CAP_VOLTAGE_RATING, "rating", 16, "V", source_text="Rating 16V"),
        DatasheetParameter(ParamType.CAPACITANCE, "capacitance", 10, "uF", source_text="Capacitance 10uF"),
    ])
    ids = manager.add_extracted_component(component)
    assert not (isolated / "amr_data.yaml").exists()
    assert FileBasedAMRSource().get_parameter("TESTCAP", "cap_voltage_rating") is None
    request = DatasheetReviewActionRequest(review_ids=[ids[0], "unknown", ids[1]], action="approve", reviewer="qa")
    # Reject second ID first; batch has a successful and two failed transitions.
    assert manager.reject(ids[1], "qa", "not supported")
    result = _run_actions(manager, request)
    assert (result.data.succeeded, result.data.failed) == (1, 2)
    assert [r.success for r in result.data.results] == [True, False, False]
    assert not manager.approve(ids[0])
    assert manager.save_approved_to_amr()["saved"] == 1
    assert live_source.get_parameter("TESTCAP", "cap_voltage_rating")["value"] == 16
    assert manager.save_approved_to_amr()["saved"] == 0
    assert not manager.reject(ids[0])
    restarted = DatasheetHITLManager()
    assert restarted.get_stats() == {"pending": 0, "approved": 0, "rejected": 1, "persisted": 1, "total": 2}
    persisted = restarted.get_persisted_list()[0]
    assert persisted.review_id == ids[0] and persisted.source_text == "Rating 16V"
    assert persisted.reviewer == "qa" and persisted.persisted_at
    assert restarted.get_rejected_list()[0].review_comment == "not supported"
    source = FileBasedAMRSource()
    assert source.get_capacitor_voltage_rating("C1", "", "") is None
    assert source.get_capacitor_voltage_rating("C1", "TESTCAP", "") == 16
    assert source.get_parameter("TESTCAP", "capacitance") is None
    assert source.get_parameter("TESTCAP", "cap_voltage_rating")["review_id"] == ids[0]
    source.reload()
    assert source.get_parameter("TESTCAP", "cap_voltage_rating")["source_text"] == "Rating 16V"
    assert yaml.safe_load((isolated / "amr_data.yaml").read_text())["components"]["TESTCAP"]["parameters"].keys() == {"cap_voltage_rating"}


def test_duplicate_ids_and_failed_yaml_write(isolated, monkeypatch):
    manager = DatasheetHITLManager()
    component = ExtractedComponent(mpn="X", parameters=[DatasheetParameter(
        ParamType.VOLTAGE_MAX, "max", 5, "V", source_text="max 5V")])
    first = manager.add_extracted_component(component)[0]
    second = manager.add_extracted_component(component)[0]
    assert first != second
    with pytest.raises(ValueError):
        DatasheetReviewActionRequest(review_ids=[first, first], action="approve")
    with pytest.raises(ValueError):
        DatasheetReviewActionRequest(review_ids=[" "], action="approve")
    original = manager._write_yaml
    def fail_pending(path, data):
        if path == manager.PENDING_FILE:
            raise OSError("disk full")
        return original(path, data)
    monkeypatch.setattr(manager, "_write_yaml", fail_pending)
    with pytest.raises(OSError):
        manager.approve(first)
    assert manager.get_stats()["pending"] == 2
    assert DatasheetHITLManager().get_stats()["pending"] == 2


def test_invalid_existing_amr_does_not_get_overwritten(isolated):
    manager = DatasheetHITLManager()
    rid = manager.add_extracted_component(ExtractedComponent(
        mpn="X", parameters=[DatasheetParameter(
            ParamType.VOLTAGE_MAX, "max", 5, "V", source_text="max 5V")]))[0]
    assert manager.approve(rid)
    amr = isolated / "amr_data.yaml"
    amr.write_text("components: [invalid]\n", encoding="utf-8")
    before = amr.read_bytes()
    assert manager.save_approved_to_amr()["saved"] == 0
    assert amr.read_bytes() == before
    assert DatasheetHITLManager().get_approved_list()[0].review_id == rid


@pytest.mark.parametrize("filename,sha", [
    ("sn74lvc1g34.pdf", "ec69c9cc71669bf34229fdb5e78c6ac941ec9bfa54da3d5d8b36b466d30f8721"),
    ("tlv733p-q1.pdf", "f4b9cb11524a358f4585e320b2fcde700623ca1fb3040ca840e5398327190b34"),
    ("tps389006.pdf", "f0bdfabf235be5a457649ae3d966e759edadcb9ddda73fc75a469048c8351881"),
])
def test_real_pdf_pending_evidence_only(isolated, filename, sha):
    pdf = ROOT / "datasheets" / filename
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == sha
    component = DatasheetParser(use_llm=False).parse_pdf(str(pdf), component_hint="ic")
    assert component.mpn == pdf.stem and component.source_file == str(pdf)
    assert component.extraction_method == "regex"
    if filename == "tps389006.pdf":
        assert [(p.param_type.value, p.value) for p in component.parameters] == [
            ("voltage_min", 2.5), ("voltage_max", 5.5)]
    manager = DatasheetHITLManager()
    ids = manager.add_extracted_component(component)
    assert len(ids) == len(component.parameters)
    for item in manager.get_pending_list():
        assert item.source_file == str(pdf)
        assert item.source_text
        assert item.status == "pending"
    assert not (isolated / "amr_data.yaml").exists()
    assert DatasheetHITLManager().get_stats()["pending"] == len(ids)


def test_neo4j_mock_audit_and_rule_file_reload(tmp_path, monkeypatch):
    """A mock of Neo4j's conditional MATCH, not an independent DB integration test."""
    records = {}
    class Result:
        def __init__(self, row=None):
            self.row = row
        def single(self):
            return self.row
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def run(self, query, params):
            rid = params["review_id"]
            if "MERGE" in query:
                records[rid] = {"status": "pending"}
                return Result()
            if "status: 'pending'" in query:
                if records.get(rid, {}).get("status") != "pending":
                    return Result()
                records[rid].update(status=params["status"], reviewer=params["reviewer"],
                                    comment=params["comment"])
                return Result({"review_id": rid})
            if rid in records and records[rid]["status"] == "approved":
                records[rid]["status"] = "persisted"
            return Result()
    class Driver:
        def session(self):
            return Session()
    manager = HITLManager(shared=True)
    monkeypatch.setattr(manager, "_get_driver", lambda: Driver())
    monkeypatch.setattr(manager, "RULES_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "CUSTOM_RULES_FILE", str(tmp_path / "custom_rules.yaml"))
    pr = PendingReview(review_id="REV_A", rule_id="R_A", rule_name="A", refdes="C1")
    rejected = PendingReview(review_id="REV_B", rule_id="R_B", rule_name="B", refdes="C2")
    assert manager.add_pending(pr) and manager.add_pending(rejected)
    assert not manager.CUSTOM_RULES_FILE in [str(p) for p in tmp_path.iterdir()]
    response = _run_actions(manager, DatasheetReviewActionRequest(
        review_ids=["REV_A", "unknown"], action="approve"))
    assert (response.data.succeeded, response.data.failed) == (1, 1)
    assert manager.reject("REV_B", reviewer="qa", comment="false positive")
    assert not manager.approve("REV_A")
    assert not manager.reject("REV_B")
    assert manager.save_approved_rules()["saved"] == 1
    assert records["REV_A"]["status"] == "persisted"
    assert records["REV_B"]["status"] == "rejected"
    assert records["REV_B"]["comment"] == "false positive"
    assert "R_B" not in yaml.safe_load((tmp_path / "custom_rules.yaml").read_text())
    assert manager.save_approved_rules()["saved"] == 0
    # The exported example rules are NOT executable RuleConfig entries.
    # Check real rule reload separately, using an isolated valid config.
    config = tmp_path / "rules.yaml"
    config.write_text("rules: []\n", encoding="utf-8")
    loader = RuleConfigManager()
    loader.load_from_file(config)
    assert loader.list_rules() == []
    config.write_text("rules:\n  - id: R_VALID\n    template_id: decap_check\n"
                      "    name: isolated\n    severity: ERROR\n    enabled: true\n"
                      "    params: {}\n", encoding="utf-8")
    os.utime(config, (config.stat().st_mtime + 2, config.stat().st_mtime + 2))
    assert loader.reload_if_stale()
    assert loader.get("R_VALID").name == "isolated"
    restarted_loader = RuleConfigManager()
    restarted_loader.load_from_file(config)
    assert restarted_loader.get("R_VALID") is not None
