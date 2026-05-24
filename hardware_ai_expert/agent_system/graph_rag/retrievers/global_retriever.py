"""全局检索器 — 社区报告检索（社区级别）

适合宏观问题，如 "这个电源系统的整体架构是什么？"
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_system.graph_rag.schemas import RetrievalResult, GraphRAGConfig

logger = logging.getLogger(__name__)


class GlobalRetriever:
    """全局检索：基于社区摘要"""

    def __init__(self, driver, vector_indexer=None, config: Optional[GraphRAGConfig] = None):
        self.driver = driver
        self.vector_indexer = vector_indexer
        self.config = config or GraphRAGConfig()

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """
        社区报告检索

        策略：
        1. 如果有向量索引，用向量搜索匹配最相关的社区摘要
        2. 否则，用关键词匹配社区摘要
        3. 返回社区摘要 + 成员列表
        """
        # 方法 1：基于向量的社区搜索
        if self.vector_indexer:
            try:
                results = self._vector_community_search(query, top_k)
                if results:
                    return results
            except Exception as e:
                logger.debug(f"向量社区搜索失败: {e}")

        # 方法 2：关键词匹配
        return self._keyword_community_search(query, top_k)

    def _vector_community_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """用向量搜索匹配社区摘要"""
        # 先搜索 VectorChunk，然后找到相关的社区
        chunk_results = self.vector_indexer.search(query, top_k=top_k * 2)

        if not chunk_results:
            return []

        # 从 VectorChunk 找到关联的 KnowledgeSource → Component → Community
        sources = list(set(r.get("source", "") for r in chunk_results if r.get("source")))

        if not sources:
            return []

        # 查询社区
        cypher = """
        MATCH (cm:Community)<-[:BELONGS_TO]-(c:Component)
        WHERE c.Model CONTAINS $keyword OR c.RefDes CONTAINS $keyword
        RETURN DISTINCT cm.id AS comm_id, cm.summary AS summary, cm.member_count AS member_count
        LIMIT $limit
        """

        results = []
        seen_communities = set()

        for source in sources[:3]:  # 最多搜索 3 个来源
            keyword = source.split("_")[0] if "_" in source else source[:8]

            try:
                with self.driver.session() as session:
                    records = list(session.run(cypher, {"keyword": keyword, "limit": top_k}))

                for r in records:
                    comm_id = r["comm_id"]
                    if comm_id in seen_communities:
                        continue
                    seen_communities.add(comm_id)

                    results.append(RetrievalResult(
                        text=f"社区 {comm_id}: {r['summary']} (成员数: {r['member_count']})",
                        score=0.7,  # 社区搜索分数固定
                        source=str(comm_id),
                        retrieval_type="global",
                        metadata={"member_count": r["member_count"]},
                    ))
            except Exception:
                continue

        return results[:top_k]

    def _keyword_community_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """关键词匹配社区摘要"""
        keywords = query.lower().split()[:3]

        if not keywords:
            return []

        conditions = " AND ".join([
            f"toLower(cm.summary) CONTAINS '{kw}'" for kw in keywords
        ])

        cypher = f"""
        MATCH (cm:Community)
        WHERE {conditions}
        RETURN cm.id AS comm_id, cm.summary AS summary, cm.member_count AS member_count
        LIMIT $limit
        """

        try:
            with self.driver.session() as session:
                records = list(session.run(cypher, {"limit": top_k}))

            return [
                RetrievalResult(
                    text=f"社区 {r['comm_id']}: {r['summary']} (成员数: {r['member_count']})",
                    score=0.5,
                    source=str(r["comm_id"]),
                    retrieval_type="global",
                    metadata={"member_count": r["member_count"]},
                )
                for r in records
            ]
        except Exception:
            # 如果没有社区，返回空（不报错）
            return []
