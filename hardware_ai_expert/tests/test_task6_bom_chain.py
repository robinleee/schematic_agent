"""Task 6: offline BOM edge cases and scoped API lookup."""
import csv
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from etl_pipeline.part_type_standardizer import PartTypeStandardizer
from agent_system.etl_web_bridge import ETLWebExecutor
from api.main import app


@pytest.mark.parametrize("ref,mpn,mfr,expected,reason", [
    ("C1", " GRM188R61C106KAALD ", "Murata Electronics", "GRM188R61C106KAALD", None),
    ("c2", "grm188r61c106kaald", "MURATA", "GRM188R61C106KAALD", None),
    ("R1 R2", " RC0402 ", "TI", "RC0402", None),
    ("C1,C2", "TDK-01", "TDK Corporation", "TDK-01", None),
    ("U1;U2", "ABC-1", "Acme", "ABC-1", None),
    ("L1\tL2", "AB-2", "Yageo Corporation", "AB-2", None),
    ("U1", "", "Acme", "", "missing_mpn"),
    ("U1", " A, B ", "Acme", "", "multiple_mpn"),
    ("U1", "A;B", "Acme", "", "multiple_mpn"),
    ("U1", "A|B", "Acme", "", "multiple_mpn"),
    ("U1", "A\nB", "Acme", "", "multiple_mpn"),
    ("", "A", "Acme", None, "missing_refdes"),
    ("  ", "A", "Acme", None, "missing_refdes"),
    ("X99", "A", "Acme", "A", "unmatched_refdes"),
    ("U1", "a-b", "", "A-B", None),
    ("U1", "A B", "", "AB", None),
    ("U1", "A_B", "", "A_B", None),
    ("U1", "A/B", "", "A/B", None),
    ("U1", "A+B", "", "A+B", None),
    ("U1", "A.1", "", "A.1", None),
    ("U1", "A(1)", "", "A(1)", None),
    ("U1", "A#1", "", "A#1", None),
    ("U1", "Å1", "", "Å1", None),
    ("U1", "  ", "", "", "missing_mpn"),
])
def test_bom_fixture(tmp_path, ref, mpn, mfr, expected, reason):
    path = tmp_path / "bom.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["RefDes", "MPN", "Manufacturer", "Description", "Package", "Qty"])
        writer.writerow([ref, mpn, mfr, "Capacitor", "0402", "2"])
    loader = PartTypeStandardizer(str(path))
    refs = [r.upper() for r in ref.replace(",", " ").replace(";", " ").split()]
    issues = loader.bom_report({"U1", "U2", "C1", "C2", "R1", "R2", "L1", "L2"})
    if reason:
        assert any(i["reason"] == reason for i in issues)
    if expected is not None:
        record = loader.get_bom_record(refs[0])
        assert record["mpn_normalized"] == expected
        assert record["mpn_raw"] == mpn
        assert record["source_line"] == (3 if "\n" in mpn else 2)
        assert record["refdes_list"] == refs
        enriched = loader.enrich_component(refs[0], {"RefDes": refs[0]})
        assert enriched.get("MPN") == (expected or None)
        assert enriched["ManufacturerRaw"] == mfr


def test_duplicate_conflict_never_enriches(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text("RefDes,MPN,Description\nC1 C2,A,Capacitor\nC2,B,Capacitor\nC2,C,Capacitor\n",
                    encoding="utf-8")
    loader = PartTypeStandardizer(str(path))
    assert loader.get_bom_record("C2") == {}
    assert loader.get_bom_record("C1")["mpn_normalized"] == "A"
    assert [i["reason"] for i in loader.bom_report({"C1", "C2"})] == [
        "duplicate_refdes", "duplicate_refdes"]


def test_transaction_component_properties_and_report(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text("RefDes,MPN,Description\nC1,GRM188R61C106KAALD,Capacitor\nX99,A,Other\n",
                    encoding="utf-8")
    loader = PartTypeStandardizer(str(path))
    component = loader.enrich_component("C1", {"RefDes": "C1", "Model": "CAP",
        "Value": "10uF", "PartType": "CAPACITOR", "RawPartType": "CAP"})
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"components": 1, "pins": 1, "nets": 1}
    ETLWebExecutor._replace_project(tx, "project-a", {"C1": component},
        [{"Component_RefDes": "C1", "Pin_Number": "1", "Net_Name": "GND"}], 1)
    writes = [call for call in tx.run.call_args_list if "UNWIND $items" in call.args[0]]
    assert len(writes) == 1
    assert "c.BOMSourceLine = row.BOMSourceLine" in writes[0].args[0]
    assert writes[0].kwargs["items"][0]["MPNRaw"] == "GRM188R61C106KAALD"
    assert loader.bom_report({"C1"})[-1]["reason"] == "unmatched_refdes"


def test_api_scoped_component_decoder_chain(monkeypatch):
    driver = MagicMock()
    session = driver.session.return_value.__enter__.return_value
    session.run.return_value.single.return_value = {
        "mpn": "GRM188R61C106KAALD", "mpn_raw": "GRM188R61C106KAALD",
        "manufacturer": "Murata", "description": "Capacitor",
        "source_line": 2, "package": "0603"}
    monkeypatch.setattr("neo4j.GraphDatabase.driver", lambda *a, **kw: driver)
    client = TestClient(app)
    response = client.get("/api/v1/knowledge/projects/project-a/components/C1/specs")
    assert response.status_code == 200
    data = response.json()
    assert data["decoder"]["mpn"] == "GRM188R61C106KAALD"
    assert data["tier3"]["status"] == "disabled"
    assert data["graphrag"]["status"] == "unavailable"
    assert session.run.call_args.kwargs == {"pid": "project-a", "ref": "C1"}
    assert "project_id: $pid" in session.run.call_args.args[0]
    assert driver.close.called


def test_api_other_project_not_found(monkeypatch):
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value.run.return_value.single.return_value = None
    monkeypatch.setattr("neo4j.GraphDatabase.driver", lambda *a, **kw: driver)
    response = TestClient(app).get("/api/v1/knowledge/projects/project-b/components/C1/specs")
    assert response.json() == {"status": "not_found", "reason": "component_not_in_project"}


def test_api_ambiguous_part_does_not_guess_or_call_external(monkeypatch):
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value.run.return_value.single.return_value = {
        "mpn": None, "mpn_raw": "A;B", "manufacturer": "Acme",
        "description": "Capacitor", "source_line": 8, "package": "0402"}
    monkeypatch.setattr("neo4j.GraphDatabase.driver", lambda *a, **kw: driver)
    response = TestClient(app).get("/api/v1/knowledge/projects/project-a/components/C1/specs")
    assert response.status_code == 200
    body = response.json()
    assert body["reason"] == "missing_or_ambiguous_mpn"
    assert body["decoder"] is None and body["amr"] is None
    assert body["component"]["mpn_raw"] == "A;B"
    assert body["datasheet"]["status"] == "unavailable"


def test_bom_excel_line_and_raw(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["RefDes", "MPN", "Description", "Manufacturer", "Qty", "Package"])
    sheet.append(["C1 C2", " grm01 ", "Capacitor", "TI", 2, "0402"])
    path = tmp_path / "bom.xlsx"
    workbook.save(path)
    loader = PartTypeStandardizer(str(path))
    assert loader.get_bom_record("C2")["source_line"] == 2
    assert loader.get_bom_record("C1")["mpn_raw"] == " grm01 "
    assert loader.get_bom_record("C1")["manufacturer"] == "Texas Instruments"


def test_real_beet_xls_headers_and_statistics():
    xlrd = pytest.importorskip("xlrd")
    path = (
        __file__.split("hardware_ai_expert")[0]
        + "beet_schematic_bom/700-00350-07_Rev02_DCN00192_bom.xls"
    )
    workbook = xlrd.open_workbook(path, on_demand=True)
    sheet = workbook.sheet_by_index(0)
    headers = {str(sheet.cell_value(0, column)).strip() for column in range(sheet.ncols)}
    assert {
        "BOM.Ref Des",
        "BOM.MPN",
        "BOM.Manufacturer",
        "BOM.Item Description",
        "BOM.Qty",
    } <= headers

    loader = PartTypeStandardizer(path)
    assert loader.bom_data
    assert loader.bom_records
    assert len(loader.bom_data) == len(loader.bom_records)
    assert all(2 <= record["source_line"] <= sheet.nrows
               for record in loader.bom_records.values())

    for refdes in loader.bom_records:
        loader.standardize(refdes, "", None)
    stats = loader.get_stats()
    assert stats["total"] == len(loader.bom_records)
    assert stats["bom_hits"] > 0
    assert stats["unknown"] < stats["total"]


def test_real_beet_legacy_xls_loads_with_beet_headers():
    path = (
        __file__.split("hardware_ai_expert")[0]
        + "beet_schematic_bom/700-00350-07_Rev02_DCN00192_bom.xls"
    )
    loader = PartTypeStandardizer(path)

    assert len(loader.bom_records) > 0
    assert max(len(record["refdes_list"]) for record in loader.bom_records.values()) > 1
    assert loader.bom_records
    assert all(record["source_line"] >= 2 for record in loader.bom_records.values())
    assert all(
        record["refdes_list"] and record["refdes_raw"]
        for record in loader.bom_records.values()
    )
    assert loader.get_bom_record(next(iter(loader.bom_records)))["manufacturer"]
