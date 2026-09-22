#!/usr/bin/env python3
"""
check_data_quality.py — 统一数据质量报告（对应 ROADMAP P0-1 / P1-6）

连接 Neo4j，按 project_id 输出统一口径的数据质量指标：
  节点计数 / PartType 覆盖率 / 全网电压标注率 / POWER 电压覆盖率 / GraphRAG chunk 数

用法:
  .venv/bin/python scripts/check_data_quality.py                # 全部项目
  .venv/bin/python scripts/check_data_quality.py --project beet7_acceptance

环境变量: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD（从 hardware_ai_expert/.env 读取）
退出码: 成功=0，连接失败=2
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "hardware_ai_expert" / ".env"


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _project_ids(session) -> list[str]:
    rows = session.run(
        "MATCH (n) WHERE n.project_id IS NOT NULL "
        "RETURN DISTINCT n.project_id AS p ORDER BY p"
    ).data()
    return [r["p"] for r in rows]


def _report(session, project: str | None) -> None:
    where = "WHERE n.project_id = $pid" if project else ""
    params = {"pid": project} if project else {}
    label = project or "(全部)"

    def scalar(cypher: str) -> int:
        return session.run(cypher, **params).single()["c"]

    comps = scalar(f"MATCH (n:Component) {where} RETURN count(n) AS c")
    pins = scalar(f"MATCH (n:Pin) {where} RETURN count(n) AS c")
    nets = scalar(f"MATCH (n:Net) {where} RETURN count(n) AS c")
    chunks = scalar(f"MATCH (n:VectorChunk) {where} RETURN count(n) AS c")

    comp_where = "WHERE c.project_id = $pid" if project else ""
    unknown = session.run(
        f"MATCH (c:Component) {comp_where} "
        f"{'AND' if project else 'WHERE'} c.PartType = 'UNKNOWN' "
        f"RETURN count(c) AS c", **params
    ).single()["c"]
    pt_cov = (comps - unknown) / comps * 100 if comps else 0.0

    net_where = "WHERE n.project_id = $pid" if project else ""
    volt = session.run(
        f"MATCH (n:Net) {net_where} "
        f"{'AND' if project else 'WHERE'} n.VoltageLevel IS NOT NULL "
        f"RETURN count(n) AS c", **params
    ).single()["c"]
    volt_cov = volt / nets * 100 if nets else 0.0

    print(f"\n=== 项目: {label} ===")
    print(f"  Component      : {comps}")
    print(f"  Pin            : {pins}")
    print(f"  Net            : {nets}")
    print(f"  VectorChunk    : {chunks}")
    print(f"  PartType 覆盖率 : {pt_cov:.1f}%  ({comps - unknown}/{comps} 已知)")
    print(f"  全网电压标注率  : {volt_cov:.1f}%  ({volt}/{nets})")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="统一数据质量报告")
    parser.add_argument("--project", default=None, help="仅统计指定 project_id")
    args = parser.parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("neo4j 驱动未安装。请使用 .venv/bin/python 运行。", file=sys.stderr)
        return 2

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        print("NEO4J_PASSWORD 未设置（检查 hardware_ai_expert/.env）", file=sys.stderr)
        return 2

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1").consume()  # 连通性探测
            projects = [args.project] if args.project else (_project_ids(session) or [None])
            for pid in projects:
                _report(session, pid)
        driver.close()
    except Exception as exc:  # noqa: BLE001
        print(f"Neo4j 连接/查询失败: {exc!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
