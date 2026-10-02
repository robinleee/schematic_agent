# -*- coding: utf-8 -*-
"""
ETL Web 桥接模块

将命令行 ETL 管道封装为 Web 可调用的类，供 Streamlit 页面使用。

功能：
- 网表文件上传 → 解析 → 质量检查 → Neo4j 入库
- 进度跟踪
- 报告生成
"""

from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime

# ETL 管道导入
import sys
ETL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl_pipeline")
sys.path.insert(0, ETL_DIR)

from chip_parser import CadenceChipParser
from prt_parser import CadencePrtParser
from net_parser import CadenceNetlistParser
from part_type_standardizer import PartTypeStandardizer
from quality_guard import QualityGuard, QualityGuardException
from load_topology import infer_net_properties

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ETLJob:
    """ETL 作业记录"""
    job_id: str
    project_name: str
    status: str = "pending"  # pending/uploaded/parsing/validating/loading/completed/failed
    files: Dict[str, str] = field(default_factory=dict)  # file_type -> filepath
    stats: Dict[str, Any] = field(default_factory=dict)
    quality_report: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class ETLResult:
    """ETL 执行结果"""
    success: bool
    components_count: int = 0
    topology_count: int = 0
    parttype_coverage: float = 0.0
    quality_passed: bool = False
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# ETL 执行器
# ============================================================

class ETLWebExecutor:
    """
    ETL Web 执行器

    将网表/BOM 文件解析并导入 Neo4j 的完整流程
    """

    def __init__(self, neo4j_uri: str = None, neo4j_user: str = None,
                 neo4j_password: str = None):
        self.neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = neo4j_password or os.environ.get("NEO4J_PASSWORD")

    def run(self, file_paths: Dict[str, str], project_name: str = "",
            skip_quality: bool = False) -> ETLResult:
        """
        执行完整 ETL 流程

        Args:
            file_paths: 文件路径字典 {pstxnet, pstxprt, pstchip, bom}
            project_name: 项目名称
            skip_quality: 是否跳过质量检查

        Returns:
            ETLResult
        """
        try:
            # Reject bypasses before parsing; neither path may reach the database.
            if skip_quality:
                raise ValueError("Unsafe import: quality precheck cannot be skipped")
            # Step 1: 解析
            components, topology = self._parse_files(file_paths)
            bom_issues = self._bom_issues

            # Step 2: 质量检查
            # The public import must never bypass its preflight, even when called
            # through the legacy skip_quality argument.
            quality_result = self._run_quality_check(components, topology)
            if not quality_result["passed"]:
                return ETLResult(
                    success=False,
                    components_count=len(components),
                    topology_count=len(topology),
                    parttype_coverage=quality_result.get("parttype_coverage", 0),
                    quality_passed=False,
                    message="质量检查未通过",
                    details={**quality_result, "bom_issues": bom_issues},
                )

            # Step 3: 加载到 Neo4j（按项目隔离）
            pid = project_name or "default"
            
            load_result = self._load_to_neo4j(components, topology, project_id=pid)
            load_result["full_report"] = quality_result["full_report"]
            load_result["bom_issues"] = bom_issues

            return ETLResult(
                success=True,
                components_count=len(components),
                topology_count=len(topology),
                parttype_coverage=self._calc_parttype_coverage(components),
                quality_passed=True,
                message="ETL 完成",
                details=load_result,
            )

        except QualityGuardException as e:
            return ETLResult(
                success=False,
                message=str(e),
                quality_passed=False,
            )
        except Exception as e:
            logger.error(f"ETL failed: {e}", exc_info=True)
            return ETLResult(
                success=False,
                message=f"ETL 异常: {str(e)}",
            )

    def _parse_files(self, file_paths: Dict[str, str]) -> tuple:
        """解析网表文件"""
        # 读取文件内容
        with open(file_paths["pstxnet"], 'r', encoding='latin-1') as f:
            pstxnet_content = f.read()
        with open(file_paths["pstxprt"], 'r', encoding='latin-1') as f:
            pstxprt_content = f.read()
        with open(file_paths["pstchip"], 'r', encoding='latin-1') as f:
            pstchip_content = f.read()

        # 解析
        net_parser = CadenceNetlistParser()
        prt_parser = CadencePrtParser()
        chip_parser = CadenceChipParser()

        topology = net_parser.parse_pstxnet(pstxnet_content)
        ref_to_prim = prt_parser.parse_pstxprt(pstxprt_content)
        chip_library = chip_parser.parse_pstchip(pstchip_content)
        self._quality_metadata = {"ref_to_prim": ref_to_prim}
        self._chip_library = chip_library

        # PartType 标准化
        bom_path = file_paths.get("bom")
        standardizer = PartTypeStandardizer(bom_path=bom_path)

        components = {}
        for triplet in topology:
            refdes = triplet['Component_RefDes']
            if refdes not in components:
                primitive_name = ref_to_prim.get(refdes)
                properties = chip_library.get(primitive_name, {}).get("Properties", {})
                raw_parttype = properties.get("PART_NAME", "N/A")
                value = properties.get("VALUE", None)

                part_type = standardizer.standardize(
                    refdes=refdes, model=primitive_name, value=value
                )

                component = {
                    "RefDes": refdes,
                    "Model": primitive_name,
                    "Value": value if value else "N/A",
                    "PartType": part_type,
                    "RawPartType": raw_parttype,
                }
                components[refdes] = standardizer.enrich_component(refdes, component)

        self._bom_issues = standardizer.bom_report(components)
        return components, topology

    def _run_quality_check(self, components: dict, topology: list) -> dict:
        """运行质量检查"""
        guard = QualityGuard(
            components=components,
            topology=topology,
            chip_library=getattr(self, "_chip_library", None),
            metadata=getattr(self, "_quality_metadata", None),
        )
        report = guard.validate(raise_on_fail=False)
        return {
            "passed": report["passed"],
            "parttype_coverage": report["checks"][0]["metric"] if report["checks"] else 0,
            "full_report": report,
        }

    def _calc_parttype_coverage(self, components: dict) -> float:
        """计算 PartType 覆盖率"""
        total = len(components)
        if total == 0:
            return 0.0
        unknown = sum(1 for c in components.values()
                      if not c.get("PartType") or c["PartType"] == "UNKNOWN")
        return (total - unknown) / total * 100

    def _load_to_neo4j(self, components: dict, topology: list, project_id: str = "default") -> dict:
        """Replace only this project's topology in one Neo4j transaction.

        No legacy schema migrations or database-wide power-tree writes here.
        A failed query or count check rolls back the old graph intact.
        """
        if not project_id or not project_id.strip() or not components or not topology:
            raise ValueError("Empty project or netlist")
        pins = {}
        for trip in topology:
            ref, number, net = (trip.get(k) for k in
                                ("Component_RefDes", "Pin_Number", "Net_Name"))
            if not all(isinstance(v, str) and v.strip() for v in (ref, number, net)):
                raise ValueError("Incomplete netlist connection")
            if ref not in components or (ref, number) in pins:
                raise ValueError("Conflicting or missing component pin")
            pins[ref, number] = net
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password))
        try:
            with driver.session() as session:
                return session.execute_write(self._replace_project, project_id, components, topology, len(pins))
        finally:
            driver.close()

    @staticmethod
    def _replace_project(tx, pid, components, topology, expected_pins):
        # Lock the project marker before deleting; concurrent imports for an
        # existing project serialize on this write. The marker is rolled back
        # together with the topology if anything fails.
        tx.run("""MERGE (project:Project {project_id: $pid})
                  SET project.name = $pid, project.import_lock = randomUUID()""", pid=pid).consume()
        tx.run("""MATCH (n) WHERE n.project_id = $pid
                  AND (n:Component OR n:Pin OR n:Net)
                  DETACH DELETE n""", pid=pid).consume()
        items = [dict(data, RefDes=ref, project_id=pid) for ref, data in components.items()]
        for start in range(0, len(items), 500):
            tx.run("""UNWIND $items AS row
                      CREATE (c:Component {project_id: $pid, RefDes: row.RefDes})
                      SET c.Model = row.Model, c.Value = row.Value,
                          c.PartType = row.PartType, c.RawPartType = row.RawPartType,
                          c.MPN = row.MPN, c.Manufacturer = row.Manufacturer,
                          c.Description = row.Description, c.Quantity = row.Quantity,
                          c.Package = row.Package,
                          c.MPNRaw = row.MPNRaw, c.MPNNormalized = row.MPNNormalized,
                          c.ManufacturerRaw = row.ManufacturerRaw,
                          c.BOMSourceLine = row.BOMSourceLine,
                          c.BOMRefDesRaw = row.BOMRefDesRaw,
                          c.BOMRefDesList = row.BOMRefDesList""",
                   items=items[start:start + 500], pid=pid).consume()
        for start in range(0, len(topology), 500):
            rows = [dict(trip, **infer_net_properties(trip["Net_Name"]))
                    for trip in topology[start:start + 500]]
            tx.run("""UNWIND $rows AS row
                      MATCH (c:Component {project_id: $pid, RefDes: row.Component_RefDes})
                      MERGE (p:Pin {project_id: $pid, Id: row.Component_RefDes + '_' + row.Pin_Number})
                      SET p.Number = row.Pin_Number, p.Type = 'SIGNAL'
                      MERGE (c)-[:HAS_PIN]->(p)
                      MERGE (n:Net {project_id: $pid, Name: row.Net_Name})
                      SET n.NetType = row.NetType, n.VoltageLevel = row.VoltageLevel
                      MERGE (p)-[:CONNECTS_TO]->(n)""",
                   rows=rows, pid=pid).consume()
        # Power tree is computed inside the same transaction and scoped at
        # every hop. A failed generation must not commit a partial replacement.
        tx.run("""MATCH (src:Component {project_id: $pid})-[:HAS_PIN]->(:Pin {project_id: $pid})
                        -[:CONNECTS_TO]->(n:Net {project_id: $pid})
                  WHERE src.PartType IN ['PMIC', 'LDO', 'BUCK'] AND n.NetType = 'POWER'
                  MATCH (n)<-[:CONNECTS_TO]-(:Pin {project_id: $pid})
                        <-[:HAS_PIN]-(tgt:Component {project_id: $pid})
                  WHERE src <> tgt AND NOT tgt.PartType IN
                        ['CAPACITOR', 'RESISTOR', 'INDUCTOR', 'DIODE']
                  WITH DISTINCT src, tgt, n
                  MERGE (src)-[r:POWERED_BY {net: n.Name}]->(tgt)
                  SET r.voltage = n.VoltageLevel""", pid=pid).consume()
        counts = tx.run("""MATCH (n) WHERE n.project_id = $pid
                           RETURN count(CASE WHEN n:Component THEN 1 END) AS components,
                                  count(CASE WHEN n:Pin THEN 1 END) AS pins,
                                  count(CASE WHEN n:Net THEN 1 END) AS nets""", pid=pid).single()
        if (counts["components"] != len(components) or counts["pins"] != expected_pins
                or counts["nets"] != len({t["Net_Name"] for t in topology})):
            raise ValueError("Imported graph counts differ from parsed netlist")
        return {"loaded": True, "project_id": pid, "pins": counts["pins"], "nets": counts["nets"]}

    def get_preview_stats(self, file_paths: Dict[str, str]) -> dict:
        """
        获取预览统计（不执行入库）

        Returns:
            统计信息字典
        """
        try:
            components, topology = self._parse_files(file_paths)

            # PartType 分布
            parttype_dist = {}
            for c in components.values():
                pt = c.get("PartType", "UNKNOWN")
                parttype_dist[pt] = parttype_dist.get(pt, 0) + 1

            # 网络统计
            net_names = set(t['Net_Name'] for t in topology)
            power_nets = [n for n in net_names if infer_net_properties(n)['NetType'] == 'POWER']
            ground_nets = [n for n in net_names if infer_net_properties(n)['NetType'] == 'GROUND']

            bom_enriched = sum(1 for c in components.values() if c.get("MPN") or c.get("Manufacturer") or c.get("Description"))
            return {
                "success": True,
                "components_count": len(components),
                "topology_count": len(topology),
                "unique_nets": len(net_names),
                "parttype_coverage": self._calc_parttype_coverage(components),
                "parttype_distribution": dict(sorted(parttype_dist.items(), key=lambda x: -x[1])[:15]),
                "power_nets_count": len(power_nets),
                "ground_nets_count": len(ground_nets),
                "top_nets": sorted(list(net_names))[:10],
                "bom_enriched_components": bom_enriched,
                "bom_issues": self._bom_issues,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # FastAPI router compatibility wrappers
    def preview(self, file_paths: Dict[str, str]) -> dict:
        """Alias used by FastAPI router."""
        return self.get_preview_stats(file_paths)

    def run_etl(self, file_paths: Dict[str, str], project_name: str = "default",
                skip_quality: bool = False) -> dict:
        """Alias used by FastAPI router; returns a JSON-serializable dict."""
        result = self.run(file_paths, project_name=project_name, skip_quality=skip_quality)
        return {
            "success": result.success,
            "components_count": result.components_count,
            "topology_count": result.topology_count,
            "parttype_coverage": result.parttype_coverage,
            "quality_passed": result.quality_passed,
            "message": result.message,
            "details": result.details,
            "quality_report": getattr(result, "quality_report", result.details.get("full_report") if result.details else None),
        }

    def create_project(self, project_name: str) -> dict:
        """Create a logical project marker without requiring netlist import."""
        from neo4j import GraphDatabase
        pid = project_name or "default"
        driver = GraphDatabase.driver(self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password))
        try:
            with driver.session() as session:
                session.run(
                    """
                    MERGE (p:Project {project_id: $pid})
                    ON CREATE SET p.created_at = datetime()
                    SET p.name = $pid, p.updated_at = datetime()
                    """,
                    {"pid": pid},
                )
            return {"project_id": pid}
        finally:
            driver.close()

    def delete_project(self, project_name: str) -> dict:
        """Delete a logical project and its isolated graph data."""
        from neo4j import GraphDatabase
        if not project_name or not project_name.strip():
            raise ValueError("project_name must not be blank")
        pid = project_name
        driver = GraphDatabase.driver(self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password))
        try:
            with driver.session() as session:
                # Refuse a partial cleanup when the vector store is unavailable.
                # Legacy unscoped records must be audited separately, never guessed.
                from agent_system.knowledge_router import delete_project_vectors
                vectors = delete_project_vectors(pid)
                deleted = session.run(
                    """
                    MATCH (n)
                    WHERE n.project_id = $pid
                    DETACH DELETE n
                    RETURN count(n) AS deleted
                    """,
                    {"pid": pid},
                ).single()
                session.run("MATCH (p:Project {project_id: $pid}) DETACH DELETE p", {"pid": pid})
            return {"project_id": pid, "deleted_nodes": str(deleted["deleted"] if deleted else 0),
                    "deleted_vectors": vectors}
        finally:
            driver.close()

    def get_progress(self, job_id: str) -> dict:
        """Synchronous ETL currently has no background jobs; return a stable completed/unknown status."""
        return {"step": "completed", "progress": 100.0, "message": f"job {job_id} is not tracked asynchronously"}


# ============================================================
# 便捷函数
# ============================================================

def run_etl_pipeline(file_paths: Dict[str, str], project_name: str = "",
                     skip_quality: bool = False) -> ETLResult:
    """便捷函数：执行 ETL 管道"""
    executor = ETLWebExecutor()
    return executor.run(file_paths, project_name, skip_quality)


def get_etl_preview(file_paths: Dict[str, str]) -> dict:
    """便捷函数：获取预览统计"""
    executor = ETLWebExecutor()
    return executor.get_preview_stats(file_paths)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("ETL Web Bridge 模块加载成功")
    print("使用方法:")
    print("  from agent_system.etl_web_bridge import run_etl_pipeline")
    print("  result = run_etl_pipeline({")
    print("      'pstxnet': 'path/to/pstxnet.dat',")
    print("      'pstxprt': 'path/to/pstxprt.dat',")
    print("      'pstchip': 'path/to/pstchip.dat',")
    print("      'bom': 'path/to/BOM.csv',")
    print("  })")
