"""图遍历检索器 — 多跳关系检索

适合关联问题，如 "U60140 的所有下游负载和它们的规格？"
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_system.graph_rag.schemas import RetrievalResult, GraphRAGConfig

logger = logging.getLogger(__name__)


class GraphRetriever:
    """图遍历检索：沿图结构多跳查询"""

    def __init__(self, driver, config: Optional[GraphRAGConfig] = None):
        self.driver = driver
        self.config = config or GraphRAGConfig()

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """
        图遍历检索

        策略：
        1. 从查询中提取实体（RefDes、MPN、网络名等）
        2. 从实体出发，沿图关系遍历
        3. 收集沿途的信息
        """
        # 提取查询中的实体
        entities = self._extract_entities(query)

        if not entities:
            return []

        results = []

        for entity in entities[:2]:  # 最多处理 2 个实体
            # 尝试作为 RefDes 查找
            refdes_results = self._query_by_refdes(entity, top_k)
            results.extend(refdes_results)

            # 尝试作为 MPN/Model 查找
            model_results = self._query_by_model(entity, top_k)
            results.extend(model_results)

            # 尝试作为网络名查找
            net_results = self._query_by_net(entity, top_k)
            results.extend(net_results)

        # 去重
        seen = set()
        unique_results = []
        for r in results:
            if r.source not in seen:
                seen.add(r.source)
                unique_results.append(r)

        return unique_results[:top_k]

    def _extract_entities(self, query: str) -> list[str]:
        """从查询中提取可能的实体标识符"""
        import re

        entities = []

        # RefDes 模式: U12345, R12345, C12345, L12345
        for match in re.finditer(r'\b([URLCJFD])(\d{3,6})\b', query.upper()):
            entities.append(match.group(0))

        # MPN 模式: TPS7A47, TLV733, SN74LVC
        for match in re.finditer(r'\b([A-Z]{2,4}\d{2,5}[A-Z0-9]*)\b', query.upper()):
            mpn = match.group(0)
            if len(mpn) >= 4 and not mpn.startswith(('THE', 'AND', 'FOR')):
                entities.append(mpn)

        # 如果没有提取到实体，用原始查询词
        if not entities:
            words = query.split()
            for w in words:
                if len(w) >= 3 and w.upper() not in ('THE', 'AND', 'FOR', 'WHAT', 'HOW', 'ALL'):
                    entities.append(w)

        return entities

    def _query_by_refdes(self, refdes: str, top_k: int) -> list[RetrievalResult]:
        """通过 RefDes 查询器件及其关联"""
        cypher = """
        MATCH (c:Component {RefDes: $refdes})
        OPTIONAL MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        OPTIONAL MATCH (c)-[:POWERED_BY]->(src:Component)
        OPTIONAL MATCH (ks:KnowledgeSource)-[:HAS_KNOWLEDGE]->(c)
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model,
               collect(DISTINCT {pin: p.Name, net: n.Name, type: p.Type})[0..10] AS pins,
               collect(DISTINCT src.RefDes) AS power_sources,
               collect(DISTINCT ks.mpn) AS knowledge_sources
        """

        try:
            with self.driver.session() as session:
                record = session.run(cypher, {"refdes": refdes}).single()

            if not record:
                return []

            # 构建描述文本
            parts = [f"器件 {record['refdes']} ({record['part_type']}, {record.get('model', 'N/A')})"]

            power_sources = record.get("power_sources", [])
            if power_sources:
                parts.append(f"电源来源: {', '.join([ps for ps in power_sources if ps])}")

            pins = record.get("pins", [])
            if pins:
                pin_strs = [f"{p['pin']}→{p['net']}" for p in pins if p.get('pin') and p.get('net')]
                if pin_strs:
                    parts.append(f"引脚连接: {', '.join(pin_strs[:8])}")

            return [RetrievalResult(
                text="; ".join(parts),
                score=0.9,
                source=refdes,
                retrieval_type="graph",
                metadata={"entity_type": "Component"},
            )]
        except Exception:
            return []

    def _query_by_model(self, model: str, top_k: int) -> list[RetrievalResult]:
        """通过型号查询器件"""
        cypher = """
        MATCH (c:Component)
        WHERE c.Model CONTAINS $model OR c.Model STARTS WITH $model
        OPTIONAL MATCH (ks:KnowledgeSource)-[:HAS_KNOWLEDGE]->(c)
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model,
               collect(DISTINCT ks.mpn) AS knowledge_sources
        LIMIT $limit
        """

        try:
            with self.driver.session() as session:
                records = list(session.run(cypher, {"model": model, "limit": top_k}))

            results = []
            for r in records:
                text = f"器件 {r['refdes']} ({r['part_type']}, {r['model']})"
                ks = r.get("knowledge_sources", [])
                if ks:
                    text += f" — 关联知识: {', '.join([k for k in ks if k])}"

                results.append(RetrievalResult(
                    text=text,
                    score=0.8,
                    source=r["refdes"],
                    retrieval_type="graph",
                    metadata={"model": r["model"]},
                ))

            return results
        except Exception:
            return []

    def _query_by_net(self, net_name: str, top_k: int) -> list[RetrievalResult]:
        """通过网络名查询"""
        cypher = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.Name CONTAINS $name OR n.Name STARTS WITH $name
        RETURN n.Name AS net_name, n.VoltageLevel AS voltage, n.NetType AS net_type,
               collect(DISTINCT c.RefDes)[0..10] AS connected_components
        LIMIT $limit
        """

        try:
            with self.driver.session() as session:
                records = list(session.run(cypher, {"name": net_name, "limit": top_k}))

            results = []
            for r in records:
                text = f"网络 {r['net_name']}"
                if r.get("voltage"):
                    text += f" ({r['voltage']}V)"
                components = r.get("connected_components", [])
                if components:
                    text += f" — 连接器件: {', '.join(components[:8])}"

                results.append(RetrievalResult(
                    text=text,
                    score=0.7,
                    source=r["net_name"],
                    retrieval_type="graph",
                    metadata={"net_type": r.get("net_type", "")},
                ))

            return results
        except Exception:
            return []
