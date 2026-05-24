"""本地检索器 — 向量相似度搜索（单 chunk 级别）

适合具体问题，如 "TPS7A47 的输入电压范围是多少？"
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_system.graph_rag.schemas import RetrievalResult, GraphRAGConfig

logger = logging.getLogger(__name__)


class LocalRetriever:
    """本地检索：基于向量相似度"""

    def __init__(self, vector_indexer, config: Optional[GraphRAGConfig] = None):
        self.vector_indexer = vector_indexer
        self.config = config or GraphRAGConfig()

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """
        向量相似度检索

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            检索结果列表
        """
        results = self.vector_indexer.search(query, top_k=top_k)

        retrieval_results = []
        for r in results:
            retrieval_results.append(RetrievalResult(
                text=r.get("text", ""),
                score=r.get("score", 0.0),
                source=r.get("id", ""),
                retrieval_type="local",
                metadata={"source_file": r.get("source", "")},
            ))

        return retrieval_results
