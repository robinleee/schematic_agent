"""Real-Neo4j HITL round trip (no mocking of the driver/session).

Requires a live Neo4j reachable via NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD
(loaded from hardware_ai_expert/.env). Skipped automatically when the
database is unreachable, so it never blocks a plain unit-test run.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

from agent_system.hitl_workflow import HITLManager, PendingReview, GraphDatabase
from api.routers.hitl import _run_actions
from api.schemas.hitl import DatasheetReviewActionRequest


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
    return f"TESTHITL_{uuid.uuid4().hex[:8]}"


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
            "MATCH (pr:PendingReview) WHERE pr.review_id STARTS WITH $prefix DETACH DELETE pr",
            {"prefix": prefix},
        )
    driver.close()


@requires_neo4j
def test_add_approve_persist_round_trips_through_real_neo4j(prefix, tmp_path, monkeypatch):
    """add_pending -> approve -> save_approved_rules must be visible in the
    real graph at every step, not just in the in-process _pending list."""
    manager = HITLManager(shared=True)
    monkeypatch.setattr(manager, "RULES_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "CUSTOM_RULES_FILE", str(tmp_path / "custom_rules.yaml"))

    review = PendingReview(
        review_id=f"{prefix}_1",
        rule_id=f"{prefix}_RULE",
        rule_name="Integration decap check",
        refdes="C101",
        net_name="VDD_3V3",
        description="Missing decoupling capacitor",
        severity="WARNING",
        expected=">=1 decap within 5mm",
        actual="0 decap found",
        suggested_fix="Add 100nF X7R near C101",
    )
    assert manager.add_pending(review) is True

    driver = manager._get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (pr:PendingReview {review_id: $rid}) "
            "RETURN pr.status AS status, pr.rule_name AS rule_name",
            {"rid": review.review_id},
        ).single()
    assert record is not None, "node must exist in the real graph right after add_pending"
    assert record["status"] == "pending"
    assert record["rule_name"] == "Integration decap check"

    assert manager.approve(review.review_id, reviewer="qa", comment="confirmed") is True
    with driver.session() as session:
        record = session.run(
            "MATCH (pr:PendingReview {review_id: $rid}) "
            "RETURN pr.status AS status, pr.reviewer AS reviewer",
            {"rid": review.review_id},
        ).single()
    assert record["status"] == "approved"
    assert record["reviewer"] == "qa"

    result = manager.save_approved_rules()
    assert result["saved"] == 1
    assert review.rule_id in result["rules"]

    custom_rules_path = Path(result["location"])
    assert custom_rules_path.exists()
    saved = yaml.safe_load(custom_rules_path.read_text(encoding="utf-8"))
    assert saved[review.rule_id]["name"] == "Integration decap check"
    assert saved[review.rule_id]["examples"][0]["refdes"] == "C101"

    with driver.session() as session:
        record = session.run(
            "MATCH (pr:PendingReview {review_id: $rid}) RETURN pr.status AS status",
            {"rid": review.review_id},
        ).single()
    assert record["status"] == "persisted", (
        "save_approved_rules must flip the real node to persisted via "
        "_mark_persisted_in_neo4j, not just the in-memory copy"
    )


@requires_neo4j
def test_reject_marks_real_node_and_blocks_double_transition(prefix):
    manager = HITLManager(shared=True)
    review = PendingReview(
        review_id=f"{prefix}_2",
        rule_id=f"{prefix}_RULE2",
        rule_name="Integration ESD check",
        refdes="D5",
    )
    assert manager.add_pending(review) is True
    assert manager.reject(review.review_id, reviewer="qa", comment="false positive") is True

    driver = manager._get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (pr:PendingReview {review_id: $rid}) "
            "RETURN pr.status AS status, pr.review_comment AS comment",
            {"rid": review.review_id},
        ).single()
    assert record["status"] == "rejected"
    assert record["comment"] == "false positive"

    # A pending-only MATCH must refuse a second transition on an already-rejected node.
    assert manager.approve(review.review_id) is False


@requires_neo4j
def test_batch_action_endpoint_against_real_neo4j(prefix):
    manager = HITLManager(shared=True)
    good = PendingReview(review_id=f"{prefix}_3", rule_id=f"{prefix}_RULE3",
                          rule_name="Batch A", refdes="R1")
    other = PendingReview(review_id=f"{prefix}_4", rule_id=f"{prefix}_RULE4",
                           rule_name="Batch B", refdes="R2")
    assert manager.add_pending(good) and manager.add_pending(other)

    request = DatasheetReviewActionRequest(
        review_ids=[good.review_id, "unknown_id", other.review_id],
        action="approve",
        reviewer="qa",
    )
    result = _run_actions(manager, request)
    assert (result.data.succeeded, result.data.failed) == (2, 1)

    driver = manager._get_driver()
    with driver.session() as session:
        rows = list(session.run(
            "MATCH (pr:PendingReview) WHERE pr.review_id IN $ids "
            "RETURN pr.review_id AS id, pr.status AS status",
            {"ids": [good.review_id, other.review_id]},
        ))
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[good.review_id] == "approved"
    assert statuses[other.review_id] == "approved"
