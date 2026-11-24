# -*- coding: utf-8 -*-
"""
Neo4j AMR 数据源

存储/查询 Datasheet HITL 审批通过的器件参数（:AMRParam 节点）。
全局共享，不做 project_id 隔离：MPN 是器件物理规格，与具体项目/板子无关。

对应 PRD: Phase 4 - Datasheet 数据闭环 Neo4j 落库
"""

from __future__ import annotations

import os
import logging
from typing import List, Optional

from dotenv import load_dotenv

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

from agent_system.schemas.graph import AMRParamNode

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


class Neo4jAMRSource:
    """Neo4j 存储/查询 AMRParam 节点"""

    def __init__(self):
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            if GraphDatabase is None:
                raise RuntimeError("neo4j not installed")
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD")
            if not password:
                raise RuntimeError("NEO4J_PASSWORD is required")
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def store_params(self, params: List[AMRParamNode]) -> int:
        """批量写入 AMRParam 节点，单条失败不中断批次"""
        stored = 0
        driver = self._get_driver()
        with driver.session() as session:
            for param in params:
                try:
                    session.run(
                        """
                        MERGE (p:AMRParam {Mpn: $Mpn, ParamType: $ParamType})
                        SET p += $props
                        """,
                        {
                            "Mpn": param.mpn,
                            "ParamType": param.param_type,
                            "props": param.to_cypher_properties(),
                        },
                    )
                    stored += 1
                except Exception as e:
                    logger.error(f"Failed to store AMR param {param.mpn}/{param.param_type}: {e}")
        logger.info(f"Stored {stored}/{len(params)} AMR params to Neo4j")
        return stored

    def get_parameter(self, mpn: str, param_type: str) -> Optional[dict]:
        """按精确 MPN + 参数类型查询"""
        driver = self._get_driver()
        with driver.session() as session:
            record = session.run(
                """
                MATCH (p:AMRParam {ParamType: $param_type})
                WHERE p.Mpn = $mpn OR p.Mpn CONTAINS $mpn OR $mpn CONTAINS p.Mpn
                RETURN p.Value AS value, p.Unit AS unit
                LIMIT 1
                """,
                {"mpn": mpn, "param_type": param_type},
            ).single()
        return dict(record) if record else None

    def get_capacitor_voltage_rating(self, model: str) -> Optional[float]:
        """获取电容耐压值 (V)，供 amr_engine 回退链路调用"""
        try:
            result = self.get_parameter(model, "cap_voltage_rating")
            if result and result.get("value") is not None:
                return float(result["value"])
        except Exception as e:
            logger.debug(f"Neo4j AMR voltage query failed for {model}: {e}")
        return None

    def get_resistor_power_rating(self, model: str) -> Optional[float]:
        """获取电阻额定功率 (W)，供 amr_engine 回退链路调用"""
        try:
            result = self.get_parameter(model, "res_power_rating")
            if result and result.get("value") is not None:
                return float(result["value"])
        except Exception as e:
            logger.debug(f"Neo4j AMR power query failed for {model}: {e}")
        return None
