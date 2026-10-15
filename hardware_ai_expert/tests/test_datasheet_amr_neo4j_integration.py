"""Real-Neo4j Datasheet AMR round trip (no mocking of the driver/session).

Requires a live Neo4j reachable via NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD
(loaded from hardware_ai_expert/.env). Skipped automatically when the
database is unreachable, so it never blocks a plain unit-test run.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

from agent_system.datasheet_hitl import DatasheetHITLManager
from agent_system.datasheet_parser import ExtractedComponent, DatasheetParameter, ParamType
from agent_system.amr_neo4j_source import Neo4jAMRSource
from agent_system.amr_engine import AMRDataSource

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None


def _neo4j_available() -> bool:
    if GraphDatabase is None:
        return False
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
        )
        with driver.session() as session:
            session.run("RETURN 1").single()
        driver.close()
        return True
    except Exception:
        return False


requires_neo4j = pytest.mark.skipif(
    not _neo4j_available(), reason="live Neo4j not reachable"
)


@pytest.fixture
def prefix():
    return f"TESTAMR_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup(prefix):
    yield
    if not _neo4j_available():
        return
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )
    with driver.session() as session:
        session.run(
            "MATCH (p:AMRParam) WHERE p.Mpn STARTS WITH $prefix DETACH DELETE p",
            {"prefix": prefix},
        )
    driver.close()


@requires_neo4j
def test_approve_and_persist_writes_real_amrparam_node(prefix, tmp_path, monkeypatch):
    """save_approved_to_amr must write a real :AMRParam node to Neo4j in
    addition to the YAML file, not just update in-process state."""
    manager = DatasheetHITLManager()
    monkeypatch.setattr(manager, "AMR_DATA_FILE", str(tmp_path / "amr_data.yaml"))
    monkeypatch.setattr(manager, "PENDING_FILE", str(tmp_path / "pending.yaml"))

    mpn = f"{prefix}_CAP_10UF_50V"
    component = ExtractedComponent(
        mpn=mpn,
        source_file="/tmp/test_datasheet.pdf",
        extraction_method="regex",
        parameters=[
            DatasheetParameter(
                param_type=ParamType.CAP_VOLTAGE_RATING,
                name="Voltage Rating",
                value=50.0,
                unit="V",
                source_text="Voltage Rating: 50V DC",
            ),
        ],
    )
    review_ids = manager.add_extracted_component(component)
    assert manager.approve(review_ids[0], reviewer="qa", comment="confirmed") is True

    result = manager.save_approved_to_amr()
    assert result["saved"] == 1

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )
    with driver.session() as session:
        record = session.run(
            "MATCH (p:AMRParam {Mpn: $mpn, ParamType: $param_type}) "
            "RETURN p.Value AS value, p.Unit AS unit, p.ApprovedBy AS approved_by",
            {"mpn": mpn, "param_type": "cap_voltage_rating"},
        ).single()
    driver.close()

    assert record is not None, "AMRParam node must exist in the real graph after persist"
    assert record["value"] == 50.0
    assert record["unit"] == "V"
    assert record["approved_by"] == "qa"


@requires_neo4j
def test_neo4j_amr_source_read_matches_written_value(prefix, tmp_path, monkeypatch):
    """Neo4jAMRSource.get_capacitor_voltage_rating must return the value
    written through the HITL approval flow."""
    manager = DatasheetHITLManager()
    monkeypatch.setattr(manager, "AMR_DATA_FILE", str(tmp_path / "amr_data.yaml"))
    monkeypatch.setattr(manager, "PENDING_FILE", str(tmp_path / "pending.yaml"))

    mpn = f"{prefix}_CAP_4U7_16V"
    component = ExtractedComponent(
        mpn=mpn,
        source_file="/tmp/test_datasheet2.pdf",
        extraction_method="regex",
        parameters=[
            DatasheetParameter(
                param_type=ParamType.CAP_VOLTAGE_RATING,
                name="Voltage Rating",
                value=16.0,
                unit="V",
                source_text="Voltage Rating: 16V",
            ),
        ],
    )
    review_ids = manager.add_extracted_component(component)
    manager.approve(review_ids[0], reviewer="qa")
    manager.save_approved_to_amr()

    source = Neo4jAMRSource()
    try:
        voltage = source.get_capacitor_voltage_rating(mpn)
    finally:
        source.close()
    assert voltage == 16.0


@requires_neo4j
def test_amr_engine_fallback_chain_reaches_neo4j_tier(prefix, tmp_path, monkeypatch):
    """AMRDataSource.get_capacitor_voltage_rating must fall through to the
    Neo4j tier when the MPN exists only in Neo4j, not in amr_data.yaml."""
    manager = DatasheetHITLManager()
    empty_yaml = tmp_path / "amr_data.yaml"
    monkeypatch.setattr(manager, "AMR_DATA_FILE", str(empty_yaml))
    monkeypatch.setattr(manager, "PENDING_FILE", str(tmp_path / "pending.yaml"))

    # Package code deliberately avoided so the "package+value lookup table"
    # tier (tier 0) cannot short-circuit the test before reaching Neo4j.
    mpn = f"{prefix}_CUSTOM_PART"
    component = ExtractedComponent(
        mpn=mpn,
        source_file="/tmp/test_datasheet3.pdf",
        extraction_method="regex",
        parameters=[
            DatasheetParameter(
                param_type=ParamType.CAP_VOLTAGE_RATING,
                name="Voltage Rating",
                value=25.0,
                unit="V",
                source_text="Voltage Rating: 25V",
            ),
        ],
    )
    review_ids = manager.add_extracted_component(component)
    manager.approve(review_ids[0], reviewer="qa")
    manager.save_approved_to_amr()

    source = AMRDataSource()
    try:
        voltage = source.get_capacitor_voltage_rating("C1", mpn, "100nF")
    finally:
        if source._neo4j_amr_source:
            source._neo4j_amr_source.close()
    assert voltage == 25.0
