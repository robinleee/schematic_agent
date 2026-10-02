"""Public synthetic Cadence/BOM sample; all write tests use fake transactions."""
import hashlib
from pathlib import Path

import pytest

from agent_system.etl_web_bridge import ETLWebExecutor
from agent_system.review_engine.engine import ReviewRuleEngine
from etl_pipeline.quality_guard import QualityGuard


NET = ("NET_NAME\n'VCC_3V3'\nNODE_NAME U1 1\nNODE_NAME C1 1\n"
       "NET_NAME\n'GND'\nNODE_NAME U1 2\nNODE_NAME C1 2\n")
PRT = "PART_NAME\nU1 'MCU_DEMO'\nPART_NAME\nC1 'CAP_DEMO'\n"
CHIP = ("primitive 'MCU_DEMO'\nbody\nVALUE='DEMO'\nend_body\nend_primitive\n"
        "primitive 'CAP_DEMO'\nbody\nVALUE='0.1UF'\nend_body\nend_primitive\n")
BOM = "RefDes,MPN,Manufacturer,Description,Package,Quantity\nU1,DEMO-MCU,Example,Microcontroller,QFN,1\nC1,DEMO-C,Example,Capacitor,0402,1\n"
# Hashes are computed from literal UTF-8 sample bytes, not from private board files.
EXPECTED_SHA256 = {
    "pstxnet": "14c646f545e96be2cb0f38656f320da662810dbd6c475e80e8876b62d16c8eac",
    "pstxprt": "02b6ae4603c7d2f7742c76e5c9fffe933b4766a1390fdf5fd9d7b46ce44bcd4d",
    "pstchip": "4d76f68339497f85e5f42f1b82fbade446f55fdc0bab418b5216db1090a28170",
    "bom": "8efdcbc3da804b704d1b24d10f7f4d041fb7e98b36ea5052520a91900fe3c356",
}


def sample(tmp_path):
    paths = {}
    for name, text, suffix in (("pstxnet", NET, ".dat"), ("pstxprt", PRT, ".dat"),
                               ("pstchip", CHIP, ".dat"), ("bom", BOM, ".csv")):
        path = tmp_path / (name + suffix)
        path.write_bytes(text.encode("utf-8"))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_SHA256[name]
        paths[name] = str(path)
    return paths


def test_preview_and_quality_offline(tmp_path):
    executor = ETLWebExecutor()
    files = sample(tmp_path)
    preview = executor.preview(files)
    assert {key: preview[key] for key in
            ("components_count", "topology_count", "unique_nets", "bom_enriched_components",
             "power_nets_count", "ground_nets_count")} == {
                 "components_count": 2, "topology_count": 4, "unique_nets": 2,
                 "bom_enriched_components": 2, "power_nets_count": 1, "ground_nets_count": 1}
    components, topology = executor._parse_files(files)
    assert executor._run_quality_check(components, topology)["passed"]
    assert components["U1"]["MPN"] == "DEMO-MCU"
    assert components["C1"]["Package"] == "0402"
    assert components["U1"]["Manufacturer"] == "Example"
    assert components["U1"]["Quantity"] == "1"
    assert components["C1"]["Description"] == "Capacitor"
    assert components["U1"]["BOMSourceLine"] == 2
    assert executor._bom_issues == []

    def fake_load(comps, trips, project_id):
        assert project_id == "isolated-sample"
        assert len(comps) == preview["components_count"]
        assert len(trips) == preview["topology_count"]
        return {"loaded": True, "project_id": project_id, "pins": len(trips),
                "nets": len({t["Net_Name"] for t in trips})}

    executor._load_to_neo4j = fake_load
    result = executor.run_etl(files, "isolated-sample")
    assert result["success"] and result["quality_passed"]
    assert result["quality_report"]["passed"]
    assert result["components_count"] == preview["components_count"]
    assert result["topology_count"] == preview["topology_count"]
    assert result["details"]["pins"] == preview["topology_count"]
    assert result["details"]["nets"] == preview["unique_nets"]


def test_quality_failure_cannot_touch_database(monkeypatch, tmp_path):
    executor = ETLWebExecutor()
    files = sample(tmp_path)
    monkeypatch.setattr(executor, "_load_to_neo4j", lambda *args, **kwargs:
                        (_ for _ in ()).throw(AssertionError("database touched")))
    bad = Path(files["pstxnet"])
    bad.write_text(NET.replace("NODE_NAME C1 2", ""), encoding="utf-8")
    result = executor.run(files, "isolated-sample")
    assert not result.success and not result.quality_passed
    assert result.details["full_report"]["passed"] is False
    assert result.details["full_report"]["summary"]["total_triplets"] == 3
    assert any(not check["passed"] for check in result.details["full_report"]["checks"])
    assert executor.run_etl(files, "isolated-sample")["quality_report"]["passed"] is False
    assert executor.run(files, "isolated-sample", skip_quality=True).success is False
    assert not QualityGuard({"U1": {"PartType": None}}, []).validate(False)["passed"]


def test_quality_guard_structured_single_pin_recognition_is_fail_closed():
    components = {
        "R0": {"PartType": "RESISTOR", "Value": "0R", "Model": "RES_0R"},
        "R1": {"PartType": "RESISTOR", "Value": "1K", "Model": "RES_1K"},
        "U_EN": {"PartType": "IC", "Model": "LTC3309A"},
        "U_BMC": {"PartType": "IC", "Model": "BMC_CONTROLLER"},
        "U_PWR": {"PartType": "IC", "Model": "POWER_CONTROLLER"},
        "U_GND": {"PartType": "IC", "Model": "GROUND_CONTROLLER"},
    }
    topology = [
        {"Component_RefDes": "R0", "Pin_Number": "1", "Net_Name": "LTC_EN"},
        {"Component_RefDes": "R0", "Pin_Number": "2", "Net_Name": "VCC_EN"},
        {"Component_RefDes": "U_EN", "Pin_Number": "EN", "Net_Name": "LTC_EN"},
        {"Component_RefDes": "R1", "Pin_Number": "1", "Net_Name": "SENSOR_INPUT"},
        {"Component_RefDes": "R1", "Pin_Number": "2", "Net_Name": "VCC_SENSOR"},
        {"Component_RefDes": "U_BMC", "Pin_Number": "ADC0", "Net_Name": "SENSOR_INPUT"},
        {"Component_RefDes": "U_PWR", "Pin_Number": "1", "Net_Name": "VCC_CORE"},
        {"Component_RefDes": "U_PWR", "Pin_Number": "2", "Net_Name": "VCC_CORE"},
        {"Component_RefDes": "U_GND", "Pin_Number": "1", "Net_Name": "GND"},
        {"Component_RefDes": "U_PWR", "Pin_Number": "2", "Net_Name": "GND"},
    ]
    guard = QualityGuard(components, topology)
    report = guard.validate(raise_on_fail=False)
    check = report["checks"][1]
    assert report["passed"]
    assert set(check["structured_details"]["legitimate_single_pin_nets"]) == {
        "VCC_EN", "VCC_SENSOR"
    }

    unknown = list(topology)
    unknown[2] = {"Component_RefDes": "U_EN", "Pin_Number": "1", "Net_Name": "LTC_EN"}
    failed = QualityGuard(components, unknown).validate(raise_on_fail=False)
    failed_check = failed["checks"][1]
    assert not failed["passed"]
    assert "VCC_EN" in failed_check["structured_details"]["suspicious_nets"]


def test_atomic_order_rollback_and_repeat(monkeypatch, tmp_path):
    from neo4j import GraphDatabase
    executor = ETLWebExecutor()
    components, topology = executor._parse_files(sample(tmp_path))
    events = []
    graph = {"old": {"components": 7, "pins": 14, "nets": 3},
             "other": {"components": 9, "pins": 18, "nets": 4}}
    fail = [True]
    wrong_count = [False]

    class Result:
        def __init__(self, counts=None):
            self.counts = counts

        def consume(self):
            pass

        def single(self):
            return self.counts

    class Tx:
        def __init__(self, data):
            self.data = data

        def run(self, query, **kwargs):
            events.append(query.strip().splitlines()[0].strip())
            pid = kwargs["pid"]
            if "MERGE (project:Project" in query:
                self.data.setdefault(pid, {})
            elif "DETACH DELETE n" in query:
                self.data[pid] = {}
            elif "CREATE (c:Component" in query:
                self.data[pid]["components"] = len(kwargs["items"])
                assert all(row["project_id"] == pid for row in kwargs["items"])
                assert kwargs["items"][0]["MPN"] == "DEMO-MCU"
                assert kwargs["items"][1]["Package"] == "0402"
                assert "c.MPN = row.MPN" in query and "c.BOMSourceLine = row.BOMSourceLine" in query
            elif "MERGE (p:Pin" in query:
                if fail[0]:
                    raise RuntimeError("injected write failure")
                rows = kwargs["rows"]
                self.data[pid]["pins"] = len({(r["Component_RefDes"], r["Pin_Number"]) for r in rows})
                self.data[pid]["nets"] = len({r["Net_Name"] for r in rows})
            elif "RETURN count(CASE WHEN n:Component" in query:
                counts = self.data[pid].copy()
                if wrong_count[0]:
                    counts["nets"] += 1
                return Result(counts)
            return Result()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute_write(self, fn, *args):
            staged = {key: value.copy() for key, value in graph.items()}
            try:
                result = fn(Tx(staged), *args)
            except Exception:
                events.append("ROLLBACK")
                raise
            graph.clear()
            graph.update(staged)
            events.append("COMMIT")
            return result

    class Driver:
        def session(self):
            return Session()

        def close(self):
            pass

    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: Driver())
    # Replace the same project; its previous graph must survive a failed transaction.
    graph["isolated-sample"] = graph.pop("old")
    before = {key: value.copy() for key, value in graph.items()}
    try:
        executor._load_to_neo4j(components, topology, "isolated-sample")
        assert False, "expected failure"
    except RuntimeError:
        pass
    assert events[0].startswith("MERGE (project:Project")
    assert events[1].startswith("MATCH (n) WHERE n.project_id")
    assert events[-1] == "ROLLBACK"
    assert graph == before
    fail[0] = False
    for _ in range(2):
        assert executor._load_to_neo4j(components, topology, "isolated-sample")["nets"] == 2
    assert events.count("COMMIT") == 2
    assert graph["isolated-sample"] == {"components": 2, "pins": 4, "nets": 2}
    assert graph["other"] == before["other"]
    snapshot = {key: value.copy() for key, value in graph.items()}
    wrong_count[0] = True
    with pytest.raises(ValueError, match="counts differ"):
        executor._load_to_neo4j(components, topology, "isolated-sample")
    assert graph == snapshot and events[-1] == "ROLLBACK"
    with pytest.raises(ValueError, match="Conflicting"):
        executor._load_to_neo4j(components, topology + topology[:1], "isolated-sample")
    assert graph == snapshot


def test_project_review_fails_closed_without_graph_reads():
    class NoGraph:
        def session(self):
            raise AssertionError("unscoped graph read")

    engine = ReviewRuleEngine(NoGraph(), project_id="isolated-sample")
    with pytest.raises(RuntimeError, match="unscoped"):
        engine.run_rules()
