"""Neo4j 原生向量索引器

使用 Neo4j 5.x VECTOR INDEX 进行向量存储和检索。
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from agent_system.graph_rag.schemas import VectorChunk, GraphRAGConfig

logger = logging.getLogger(__name__)


class Neo4jVectorIndexer:
    """Neo4j 原生向量索引管理"""

    INDEX_NAME = "chunk_embedding"
    DIMENSIONS = 384
    SIMILARITY = "cosine"

    def __init__(self, driver, config: Optional[GraphRAGConfig] = None):
        self.driver = driver
        self.config = config or GraphRAGConfig()
        self._embedding_fn = None

    # --------------------------------------------------------
    # 嵌入函数
    # --------------------------------------------------------

    def _get_embedding_fn(self):
        """延迟加载 sentence-transformers 模型"""
        if self._embedding_fn is None:
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(self.config.embedding_model)
                self._embedding_fn = lambda texts: model.encode(texts, show_progress_bar=False).tolist()
            except ImportError:
                logger.warning("sentence-transformers 未安装，使用零向量")
                self._embedding_fn = lambda texts: [[0.0] * self.config.embedding_dim] * len(texts)
        return self._embedding_fn

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量"""
        fn = self._get_embedding_fn()
        if len(texts) == 1:
            return [fn(texts)[0]] if isinstance(fn(texts)[0], list) else fn(texts)
        return fn(texts)

    def embed_query(self, query: str) -> list[float]:
        """生成查询向量"""
        return self.embed_texts([query])[0]

    # --------------------------------------------------------
    # 索引管理
    # --------------------------------------------------------

    def create_index(self):
        """创建 VECTOR INDEX（如果不存在）"""
        cypher = f"""
        CREATE VECTOR INDEX {self.INDEX_NAME} IF NOT EXISTS
        FOR (vc:VectorChunk) ON (vc.embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {self.DIMENSIONS},
            `vector.similarity_function`: '{self.SIMILARITY}'
          }}
        }}
        """
        try:
            with self.driver.session() as session:
                session.run(cypher)
            logger.info(f"向量索引 '{self.INDEX_NAME}' 已创建/确认")
        except Exception as e:
            logger.warning(f"创建向量索引失败（可能已存在）: {e}")

    # --------------------------------------------------------
    # 写入
    # --------------------------------------------------------

    def index_chunks(self, chunks: list[VectorChunk], batch_size: int = 50):
        """批量索引 chunks 到 Neo4j"""
        # 生成嵌入
        texts = [c.text for c in chunks]
        embeddings = self.embed_texts(texts)

        # 批量写入
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]

            records = []
            for chunk, emb in zip(batch, batch_embeddings):
                records.append({
                    "id": chunk.id,
                    "text": chunk.text,
                    "embedding": emb,
                    "source": chunk.source,
                    "chunk_index": chunk.chunk_index,
                })

            cypher = """
            UNWIND $records AS r
            MERGE (vc:VectorChunk {id: r.id})
            SET vc.text = r.text,
                vc.embedding = r.embedding,
                vc.source = r.source,
                vc.chunk_index = r.chunk_index
            """
            try:
                with self.driver.session() as session:
                    session.run(cypher, {"records": records})
            except Exception as e:
                logger.error(f"批量写入 VectorChunk 失败: {e}")
                # 逐条写入
                for rec in records:
                    try:
                        with self.driver.session() as session:
                            session.run(cypher, {"records": [rec]})
                    except Exception:
                        pass

        logger.info(f"已索引 {len(chunks)} 个 VectorChunk")

    # --------------------------------------------------------
    # 检索
    # --------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """向量相似度搜索"""
        query_embedding = self.embed_query(query)

        cypher = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $query_embedding)
        YIELD node, score
        RETURN node.id AS id, node.text AS text, node.source AS source, score
        ORDER BY score DESC
        """

        try:
            with self.driver.session() as session:
                results = list(session.run(cypher, {
                    "index_name": self.INDEX_NAME,
                    "top_k": top_k,
                    "query_embedding": query_embedding,
                }))
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"向量搜索失败，降级到文本搜索: {e}")
            return self._fallback_text_search(query, top_k)

    def _fallback_text_search(self, query: str, top_k: int = 5) -> list[dict]:
        """向量搜索失败时的文本降级搜索"""
        # 使用 CONTAINS 进行简单文本匹配
        keywords = query.lower().split()[:3]
        if not keywords:
            return []

        conditions = " AND ".join([f"toLower(vc.text) CONTAINS '{kw}'" for kw in keywords])
        cypher = f"""
        MATCH (vc:VectorChunk)
        WHERE {conditions}
        RETURN vc.id AS id, vc.text AS text, vc.source AS source, 0.5 AS score
        LIMIT $top_k
        """

        try:
            with self.driver.session() as session:
                return [dict(r) for r in session.run(cypher, {"top_k": top_k})]
        except Exception:
            return []

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    def get_chunk_count(self) -> int:
        """获取 VectorChunk 总数"""
        try:
            with self.driver.session() as session:
                result = session.run("MATCH (vc:VectorChunk) RETURN count(vc) AS cnt").single()
                return result["cnt"] if result else 0
        except Exception:
            return 0
