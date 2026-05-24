"""社区检测器

使用 Louvain/Leiden 算法在 Neo4j 图谱上检测社区，
并为每个社区生成 LLM 摘要。
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_system.graph_rag.schemas import Community, GraphRAGConfig

logger = logging.getLogger(__name__)


class CommunityDetector:
    """Louvain 社区检测 + LLM 摘要"""

    def __init__(self, driver, llm_client=None, config: Optional[GraphRAGConfig] = None):
        self.driver = driver
        self.config = config or GraphRAGConfig()
        self._llm = llm_client

    def _get_llm(self):
        if self._llm is None:
            from agent_system.llm_client import LLMClient
            self._llm = LLMClient()
        return self._llm

    # --------------------------------------------------------
    # 社区检测
    # --------------------------------------------------------

    def detect_communities(self) -> list[Community]:
        """
        在 Neo4j 图谱上运行社区检测

        策略：
        1. 导出 Component + DESCRIBES/HAS_KNOWLEDGE 子图到 NetworkX
        2. 运行 Louvain 算法
        3. 返回社区划分
        """
        import networkx as nx

        try:
            import community as community_louvain
        except ImportError:
            logger.error("python-louvain 未安装，无法运行社区检测")
            return []

        # 1. 从 Neo4j 导出子图
        G = self._export_graph()
        if G.number_of_nodes() < 3:
            logger.info("图节点数不足，跳过社区检测")
            return []

        # 2. 运行 Louvain
        partition = community_louvain.best_partition(G, resolution=1.0)

        # 3. 整理为 Community 对象
        community_map: dict[int, list[str]] = {}
        for node, comm_id in partition.items():
            community_map.setdefault(comm_id, []).append(node)

        communities = []
        for comm_id, members in community_map.items():
            if len(members) >= 2:  # 只保留 2+ 成员的社区
                communities.append(Community(
                    id=comm_id,
                    member_ids=members,
                    member_count=len(members),
                ))

        logger.info(f"检测到 {len(communities)} 个社区（共 {sum(c.member_count for c in communities)} 个节点）")
        return communities

    def _export_graph(self):
        """从 Neo4j 导出 Component 子图到 NetworkX"""
        import networkx as nx

        G = nx.Graph()

        # 导出 Component 节点
        cypher_nodes = """
        MATCH (c:Component)
        WHERE c.PartType IN ['IC', 'PMIC', 'MCU', 'FPGA', 'SOC', 'LDO', 'DCDC']
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
        LIMIT 500
        """

        with self.driver.session() as session:
            nodes = list(session.run(cypher_nodes))

        for n in nodes:
            G.add_node(n["refdes"], part_type=n["part_type"], model=n.get("model", ""))

        # 导出关系（POWERED_BY + 同一 Net 上的连接）
        cypher_edges = """
        MATCH (c1:Component)-[:POWERED_BY]->(c2:Component)
        RETURN c1.RefDes AS src, c2.RefDes AS tgt
        """

        with self.driver.session() as session:
            edges = list(session.run(cypher_edges))

        for e in edges:
            if G.has_node(e["src"]) and G.has_node(e["tgt"]):
                G.add_edge(e["src"], e["tgt"], relation="POWERED_BY")

        # 补充：共享同一电源网络的器件间连边
        cypher_shared_nets = """
        MATCH (c1:Component)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(n:Net)<-[:CONNECTS_TO]-(:Pin)<-[:HAS_PIN]-(c2:Component)
        WHERE n.NetType = 'POWER' AND c1.RefDes < c2.RefDes
          AND c1.PartType IN ['IC', 'PMIC', 'MCU', 'FPGA', 'SOC', 'LDO', 'DCDC']
          AND c2.PartType IN ['IC', 'PMIC', 'MCU', 'FPGA', 'SOC', 'LDO', 'DCDC']
        RETURN DISTINCT c1.RefDes AS src, c2.RefDes AS tgt, n.Name AS net_name
        LIMIT 2000
        """

        with self.driver.session() as session:
            shared = list(session.run(cypher_shared_nets))

        for s in shared:
            if G.has_node(s["src"]) and G.has_node(s["tgt"]):
                if not G.has_edge(s["src"], s["tgt"]):
                    G.add_edge(s["src"], s["tgt"], relation="shared_power_net")

        logger.info(f"导出图: {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")
        return G

    # --------------------------------------------------------
    # 社区摘要
    # --------------------------------------------------------

    def generate_summaries(self, communities: list[Community]) -> list[Community]:
        """为每个社区生成 LLM 摘要"""
        for comm in communities:
            # 收集社区成员信息
            member_info = self._get_member_info(comm.member_ids)
            if not member_info:
                comm.summary = f"社区 {comm.id}：{comm.member_count} 个器件"
                continue

            # 构建 LLM prompt
            members_text = "\n".join([
                f"- {info['refdes']} ({info['part_type']}, {info.get('model', 'N/A')})"
                for info in member_info[:20]
            ])

            prompt = f"""请用一句话总结以下器件组成的电源社区：

{members_text}

要求：指出主要电源源和负载类型，不超过50字。"""

            try:
                llm = self._get_llm()
                response = llm.chat(prompt, temperature=0.1, max_tokens=100)
                comm.summary = response.strip()
            except Exception as e:
                logger.debug(f"社区摘要生成失败: {e}")
                comm.summary = f"社区 {comm.id}：{comm.member_count} 个器件"

        return communities

    def _get_member_info(self, member_ids: list[str]) -> list[dict]:
        """获取社区成员的详细信息"""
        cypher = """
        MATCH (c:Component)
        WHERE c.RefDes IN $refdes_list
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
        """

        try:
            with self.driver.session() as session:
                results = list(session.run(cypher, {"refdes_list": member_ids}))
            return [dict(r) for r in results]
        except Exception:
            return []

    # --------------------------------------------------------
    # 写入 Neo4j
    # --------------------------------------------------------

    def write_communities(self, communities: list[Community]):
        """将社区写入 Neo4j"""
        for comm in communities:
            # 创建社区节点
            cypher_create = """
            MERGE (cm:Community {id: $id})
            SET cm.summary = $summary, cm.member_count = $member_count
            """

            try:
                with self.driver.session() as session:
                    session.run(cypher_create, {
                        "id": str(comm.id),
                        "summary": comm.summary,
                        "member_count": comm.member_count,
                    })
            except Exception as e:
                logger.debug(f"写入社区节点失败: {e}")

            # 创建 BELONGS_TO 关系
            for member_id in comm.member_ids:
                cypher_link = """
                MATCH (cm:Community {id: $comm_id})
                MATCH (c:Component {RefDes: $refdes})
                MERGE (c)-[:BELONGS_TO]->(cm)
                """

                try:
                    with self.driver.session() as session:
                        session.run(cypher_link, {
                            "comm_id": str(comm.id),
                            "refdes": member_id,
                        })
                except Exception:
                    pass

        logger.info(f"已写入 {len(communities)} 个社区到 Neo4j")
