#!/usr/bin/env python3
"""
check_data_quality.py — 统一数据质量报告（对应 ROADMAP P0-1 / P1-6）

连接 Neo4j，按 project_id 只读统计注入后的核心网络、连通性、电压标注及电容耐压。
显式数字轨才作为电压映射依据；不从 VTT/VDDQ/VPP 名称推测电压。

用法:
  .venv/bin/python scripts/check_data_quality.py                # 全部项目
  .venv/bin/python scripts/check_data_quality.py --project beet7_acceptance

环境变量: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD（从 hardware_ai_expert/.env 读取）
退出码: 成功=0，连接失败=2
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
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


CORE_RAIL = re.compile(
    r"(?i)^(?:VCC\w*|VDD\w*|VSS(?:[_-]|$)|GND(?:[_-]|$)|"
    r"AVDD\w*|DVDD\w*|IOVDD\w*|VIN(?:[_-]|$)|VOUT(?:[_-]|$)|"
    r"VBAT(?:[_-]|$)|VPP(?:[_-]|$)|VTT(?:[_-]|$)|"
    r"[0-9]+[VP][0-9]+(?:[_-]|$)|[0-9]+(?:\.[0-9]+)?V(?:[_-]|$))"
)
DDR_RAIL = re.compile(r"(?i)(?:^|[_-])(?:LPDDR|DDR[345]?)(?:[_-]|$)")
NUMERIC_RAIL = re.compile(
    r"(?i)(?<![A-Z0-9])(?:[0-9]+V[0-9]+|[0-9]+P[0-9]+|"
    r"[0-9]+(?:\.[0-9]+)?V)(?![A-Z0-9])"
)


def _rail_family(name: str) -> str | None:
    """Only classify rail names, not DDR data/address signals."""
    if not name or not CORE_RAIL.search(name):
        return None
    upper = name.upper()
    if re.search(r"(?:^|[_-])VDDQ(?:[_-]|$)", upper):
        return "VDDQ"
    if re.search(r"(?:^|[_-])VPP(?:[_-]|$)", upper):
        return "VPP"
    if re.search(r"(?:^|[_-])VTT(?:[_-]|$)", upper):
        return "VTT"
    if DDR_RAIL.search(name):
        return "DDR/LPDDR power"
    return "other core rail"


def _expected_voltage(name: str) -> str | None:
    """Only explicit numeric tokens are evidence; VTT/VDDQ/VPP alone are ambiguous."""
    matches = NUMERIC_RAIL.findall(name)
    values = set()
    for token in matches:
        token = token.upper().rstrip("V").replace("P", ".").replace("V", ".")
        values.add(float(token))
    if len(values) == 1:
        return f"{values.pop():g}V"
    return None


def _quality_details(session, pid: str) -> dict:
    """Read-only, exact project scope; never borrow another project's pins or BOM."""
    nets = session.run(
        "MATCH (n:Net {project_id: $pid}) "
        "OPTIONAL MATCH (p:Pin {project_id: $pid})-[:CONNECTS_TO]->(n) "
        "RETURN n.Name AS name, n.VoltageLevel AS voltage, "
        "count(DISTINCT p) AS pin_count ORDER BY name", pid=pid
    ).data()
    selected = []
    for row in nets:
        family = _rail_family(row["name"])
        if family:
            selected.append({**row, "family": family})
    missing_connectivity = [r["name"] for r in selected if r["pin_count"] < 2]
    missing_voltage = [r["name"] for r in selected
                       if r["voltage"] is None or not str(r["voltage"]).strip()]
    grounded_missing = {name: _expected_voltage(name) for name in missing_voltage
                        if _expected_voltage(name) is not None}
    families = Counter(r["family"] for r in selected)
    caps = session.run(
        "MATCH (c:Component {project_id: $pid}) "
        "WHERE c.PartType = 'CAPACITOR' OR c.RefDes STARTS WITH 'C' "
        "RETURN c.RefDes AS refdes, c.MPN AS mpn, c.Package AS package, "
        "c.Manufacturer AS manufacturer, c.PartType AS parttype, "
        "c.voltage_rating AS rating ORDER BY refdes", pid=pid
    ).data()
    missing_caps = [r for r in caps if r["rating"] is None
                    or not str(r["rating"]).strip()
                    or str(r["rating"]).strip().upper() == "N/A"]
    groups = Counter((str(r["mpn"] or "(missing)"), str(r["package"] or "(missing)"),
                      str(r["manufacturer"] or "(missing)"))
                     for r in missing_caps)
    return {
        "families": families,
        "net_total": len(nets),
        "core_total": len(selected),
        "existence": {
            "numerator": len(selected), "denominator": len(nets), "missing": [],
        },
        "connectivity": {
            "numerator": sum(r["pin_count"] >= 2 for r in selected),
            "denominator": len(selected), "missing": missing_connectivity,
        },
        "annotation": {
            "numerator": sum(
                bool(r["voltage"] is not None and str(r["voltage"]).strip())
                for r in selected
            ),
            "denominator": len(selected), "missing": missing_voltage,
        },
        "missing_connectivity": missing_connectivity,
        "missing_voltage": missing_voltage,
        "grounded_missing": grounded_missing,
        "cap_total": len(caps),
        "missing_caps": missing_caps,
        "cap_groups": groups,
    }


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
    if project is None:
        print("  核心网络/电容明细: 无 project_id，不合并无归属数据")
        return

    detail = _quality_details(session, project)
    total = detail["core_total"]
    existence = detail["existence"]
    connectivity = detail["connectivity"]
    annotation = detail["annotation"]
    # Existence is an inventory of actual nets, NOT a claim that every board needs
    # every DDR rail. No inferred/project-crossing denominator is introduced.
    print(f"  核心网络存在    : {existence['numerator']}/{existence['denominator']} "
          f"(实际匹配/项目所有网络; 非必备轨覆盖率)")
    print(f"  网络族存在      : {dict(sorted(detail['families'].items()))}")
    print(f"  核心网络连通    : {connectivity['numerator']}/{connectivity['denominator']} "
          f"({connectivity['numerator'] / connectivity['denominator'] * 100:.1f}%)"
          if connectivity["denominator"] else "  核心网络连通    : 0/0 (N/A)")
    print(f"  核心电压已标注  : {annotation['numerator']}/{annotation['denominator']} "
          f"({annotation['numerator'] / annotation['denominator'] * 100:.1f}%)"
          if annotation["denominator"] else "  核心电压已标注  : 0/0 (N/A)")
    for key, title in (("missing_connectivity", "连通不足 (<2 pins)"),
                       ("missing_voltage", "缺失 VoltageLevel")):
        print(f"  {title} ({len(detail[key])}): {detail[key]}")
    print(f"  缺失标注但名称含明确电压 (仅建议, 不写入): {detail['grounded_missing']}")
    cap_total = detail["cap_total"]
    cap_known = cap_total - len(detail["missing_caps"])
    print(f"  电容 voltage_rating: {cap_known}/{cap_total} "
          f"({cap_known / cap_total * 100:.1f}%)" if cap_total
          else "  电容 voltage_rating: 0/0 (N/A)")
    print(f"  缺失电容 RefDes ({len(detail['missing_caps'])}): "
          f"{[r['refdes'] for r in detail['missing_caps']]}")
    print("  缺失分组 (MPN, Package, Manufacturer):")
    for group, count in sorted(detail["cap_groups"].items()):
        print(f"    {group}: {count}")


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
            projects = [args.project] if args.project else _project_ids(session)
            if not projects:
                print("无带 project_id 的数据，无法生成项目级质量指标")
            for pid in projects:
                _report(session, pid)
        driver.close()
    except Exception as exc:  # noqa: BLE001
        print(f"Neo4j 连接/查询失败: {exc!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
