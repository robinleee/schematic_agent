#!/usr/bin/env python3
"""Report capacitor voltage-rating AMR coverage from Neo4j Component nodes.

The tool does not mutate data. It checks capacitor-like components and reports
which ones lack a voltage_rating property or FileBasedAMRSource cap_voltage_rating
entry keyed by MPN/Model/Value.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))


def _load_amr_source():
    try:
        from agent_system.datasheet_hitl import FileBasedAMRSource
        return FileBasedAMRSource()
    except Exception as exc:
        print(f"warning: AMR source unavailable: {exc}", file=sys.stderr)
        return None


def _fetch_caps(project_id: str):
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is required")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (c:Component)
                WHERE (c.project_id = $project_id OR ($project_id = 'default' AND c.project_id IS NULL))
                  AND (c.PartType = 'CAPACITOR' OR c.RefDes STARTS WITH 'C')
                RETURN c.RefDes AS refdes, c.Model AS model, c.Value AS value,
                       c.MPN AS mpn, c.Manufacturer AS manufacturer,
                       c.voltage_rating AS voltage_rating
                ORDER BY c.RefDes
                """,
                {"project_id": project_id},
            )
            return [dict(r) for r in result]
    finally:
        driver.close()


def _has_rating(row: dict, amr_source) -> tuple[bool, str]:
    if row.get("voltage_rating") not in (None, "", "N/A"):
        return True, "component.voltage_rating"
    if amr_source:
        for key in (row.get("mpn"), row.get("model"), row.get("value")):
            if not key:
                continue
            try:
                param = amr_source.get_parameter(str(key), "cap_voltage_rating")
                if param:
                    return True, f"amr:{key}"
            except Exception:
                pass
    return False, "missing"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--output-csv", help="write missing capacitor list")
    parser.add_argument("--min-coverage", type=float, default=0.95)
    args = parser.parse_args()

    try:
        caps = _fetch_caps(args.project_id)
    except Exception as exc:
        print(json.dumps({
            "project_id": args.project_id,
            "error": f"Neo4j unavailable: {exc}",
            "hint": "Start Neo4j or set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD, then rerun this coverage tool.",
        }, ensure_ascii=False, indent=2))
        return 2
    amr = _load_amr_source()
    missing = []
    covered = 0
    sources = {}
    for row in caps:
        ok, source = _has_rating(row, amr)
        sources[source] = sources.get(source, 0) + 1
        if ok:
            covered += 1
        else:
            missing.append(row)

    total = len(caps)
    coverage = covered / total if total else 1.0
    report = {
        "project_id": args.project_id,
        "total_capacitors": total,
        "covered": covered,
        "missing": len(missing),
        "coverage": coverage,
        "sources": sources,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output_csv:
        with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["refdes", "model", "value", "mpn", "manufacturer"])
            writer.writeheader()
            for row in missing:
                writer.writerow({k: row.get(k) for k in writer.fieldnames})
        print(f"missing list written: {args.output_csv}")

    return 0 if coverage >= args.min_coverage else 1


if __name__ == "__main__":
    raise SystemExit(main())
