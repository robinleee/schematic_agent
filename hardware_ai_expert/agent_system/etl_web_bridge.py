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
from load_topology import HardwareTopologyDB, infer_net_properties

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
        self.neo4j_password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "SecretPassword123")

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
            # Step 1: 解析
            components, topology = self._parse_files(file_paths)

            # Step 2: 质量检查
            if not skip_quality:
                quality_result = self._run_quality_check(components, topology)
                if not quality_result["passed"]:
                    return ETLResult(
                        success=False,
                        components_count=len(components),
                        topology_count=len(topology),
                        parttype_coverage=quality_result.get("parttype_coverage", 0),
                        quality_passed=False,
                        message="质量检查未通过",
                        details=quality_result,
                    )

            # Step 3: 加载到 Neo4j
            load_result = self._load_to_neo4j(components, topology)

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

                components[refdes] = {
                    "RefDes": refdes,
                    "Model": primitive_name,
                    "Value": value if value else "N/A",
                    "PartType": part_type,
                    "RawPartType": raw_parttype,
                }

        return components, topology

    def _run_quality_check(self, components: dict, topology: list) -> dict:
        """运行质量检查"""
        guard = QualityGuard(components=components, topology=topology)
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
        unknown = sum(1 for c in components.values() if c.get("PartType") == "UNKNOWN")
        return (total - unknown) / total * 100

    def _load_to_neo4j(self, components: dict, topology: list) -> dict:
        """加载到 Neo4j"""
        db = HardwareTopologyDB(self.neo4j_uri, self.neo4j_user, self.neo4j_password)
        try:
            # 创建索引
            db.create_topology_indexes()

            # 加载组件
            db.load_components(components)

            # 加载拓扑
            db.batch_insert_topology(topology)

            return {"loaded": True}
        finally:
            db.close()

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
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


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
