#!/usr/bin/env python3
"""Cypher query performance benchmark against a live Neo4j instance.

对应 PRD_GAP_ANALYSIS_V2.md P2 项「Cypher 性能基准」：验证 graph_tools.py 里
CYPHER_ROW_LIMIT=500 等保护措施是否必要，并给出核心查询的真实延迟分布。

Usage:
    source .venv/bin/activate
    python3 tools/cypher_perf_benchmark.py --project beet7_acceptance --iterations 20
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None


# 每个场景对应 graph_tools.py 里实际工具函数使用的核心 Cypher 模式，
# 用真实数据集（beet7_acceptance，12688 器件/8159 网络）里存在的样本值做参数化。
SCENARIOS = {
    "get_component_nets": {
        "query": """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE c.project_id = $project_id
            RETURN p.Name AS pin, n.Name AS net, n.NetType AS net_type
        """,
        "params": {"refdes": "U30004"},
    },
    "get_net_components (fan-out net)": {
        "query": """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE n.project_id = $project_id
            RETURN c.RefDes AS refdes, c.PartType AS part_type, p.Name AS pin
            LIMIT $row_limit
        """,
        "params": {"net_name": "SFTY_IGN"},
    },
    "get_power_domain (by voltage substring)": {
        "query": """
            MATCH (n:Net)
            WHERE n.project_id = $project_id AND n.Name CONTAINS '3V3'
            WITH n LIMIT $row_limit
            MATCH (n)<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            RETURN n.Name AS net, collect(DISTINCT c.RefDes)[0..10] AS components, count(DISTINCT c) AS cnt
        """,
        "params": {},
    },
    "get_power_tree (root fan-out)": {
        "query": """
            MATCH (root:Component {RefDes: $root_refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE root.project_id = $project_id
              AND (n.NetType = 'POWER' OR n.Name CONTAINS 'VCC' OR n.Name CONTAINS 'VDD'
                   OR n.Name CONTAINS '3V3' OR n.Name CONTAINS '1V8' OR n.Name CONTAINS '5V')
            WITH root, n
            MATCH (n)<-[:CONNECTS_TO]-(load_pin:Pin)<-[:HAS_PIN]-(load:Component)
            WHERE load <> root
            RETURN n.Name AS power_net,
                   collect(DISTINCT {refdes: load.RefDes, part_type: load.PartType})[0..10] AS loads,
                   count(DISTINCT load) AS load_count
            ORDER BY power_net
        """,
        "params": {"root_refdes": "UU90"},
    },
    "trace_power_chain (1-hop POWERED_BY)": {
        "query": """
            MATCH (src:Component {RefDes: $rd})-[r:POWERED_BY]->(load:Component)
            WHERE src.project_id = $project_id
            RETURN load.RefDes AS rd, load.PartType AS pt, r.voltage AS voltage
            ORDER BY r.voltage DESC
        """,
        "params": {"rd": "UU90"},
    },
    "get_common_cause_graph (shared-net scan)": {
        "query": """
            MATCH (c:Component)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE c.project_id = $project_id AND c.RefDes IN $refdes_list
            WITH n, count(DISTINCT c) AS shared
            WHERE shared > 1
            RETURN n.Name AS net, shared
            ORDER BY shared DESC
            LIMIT $row_limit
        """,
        "params": {"refdes_list": ["U30004", "U60140", "U60169", "UU30", "U60168"]},
    },
    "full-graph scan (worst case, no filter)": {
        "query": """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE c.project_id = $project_id
            RETURN c.RefDes AS refdes, n.Name AS net
            LIMIT $row_limit
        """,
        "params": {},
    },
}


def run_benchmark(driver, project_id: str, row_limit: int, iterations: int) -> dict:
    results = {}
    with driver.session() as session:
        for name, spec in SCENARIOS.items():
            params = dict(spec["params"])
            params["project_id"] = project_id
            params["row_limit"] = row_limit

            latencies = []
            row_counts = []
            error = None
            for _ in range(iterations):
                started = time.perf_counter()
                try:
                    records = list(session.run(spec["query"], params))
                    row_counts.append(len(records))
                except Exception as exc:  # noqa: BLE001 - benchmark must record, not crash
                    error = str(exc)
                    break
                latencies.append((time.perf_counter() - started) * 1000)

            if error:
                results[name] = {"status": "error", "error": error}
                continue

            sorted_lat = sorted(latencies)
            results[name] = {
                "status": "ok",
                "iterations": len(latencies),
                "row_count": row_counts[0] if row_counts else 0,
                "p50_ms": round(statistics.median(sorted_lat), 2),
                "p95_ms": round(sorted_lat[max(0, int(len(sorted_lat) * 0.95) - 1)], 2),
                "max_ms": round(max(sorted_lat), 2),
                "min_ms": round(min(sorted_lat), 2),
            }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="beet7_acceptance", help="project_id to scope queries to")
    parser.add_argument("--row-limit", type=int, default=int(os.getenv("CYPHER_ROW_LIMIT", "500")))
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if GraphDatabase is None:
        print(json.dumps({"status": "blocked", "reason": "neo4j package not installed"}))
        return 2

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        print(json.dumps({"status": "blocked", "reason": "NEO4J_PASSWORD not set"}))
        return 2

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as s:
            s.run("RETURN 1").single()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "blocked", "reason": f"Neo4j unreachable: {exc}"}))
        return 2

    try:
        results = run_benchmark(driver, args.project, args.row_limit, args.iterations)
    finally:
        driver.close()

    output = {
        "mode": "live-neo4j",
        "project_id": args.project,
        "row_limit": args.row_limit,
        "iterations": args.iterations,
        "scenarios": results,
    }
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all(r.get("status") == "ok" for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
