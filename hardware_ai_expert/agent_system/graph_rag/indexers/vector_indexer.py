"""Neo4j 原生向量索引器

使用 Neo4j 5.x VECTOR INDEX 进行向量存储和检索。
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

from agent_system.graph_rag.schemas import VectorChunk, GraphRAGConfig

logger = logging.getLogger(__name__)


class Neo4jVectorIndexer:
    """Neo4j 原生向量索引管理"""

    DEFAULT_DIMENSIONS = 384
    SIMILARITY = "cosine"

    def __init__(self, driver, config: Optional[GraphRAGConfig] = None):
        self.driver = driver
        # Only fall back to the environment when the caller didn't pass an
        # explicit config — an explicitly-passed embedding_model/embedding_dim
        # must not be silently overridden by SCHEMATIC_EMBEDDING_* env vars.
        if config is None:
            self.config = GraphRAGConfig()
            self.config.embedding_model = os.environ.get("SCHEMATIC_EMBEDDING_MODEL", self.config.embedding_model)
            self.config.embedding_dim = int(os.environ.get("SCHEMATIC_EMBEDDING_DIM", str(self.config.embedding_dim)))
        else:
            self.config = config
        # Neo4j allows only one VECTOR INDEX per (label, property) pair, so
        # switching embedding models needs both a distinct index name AND a
        # distinct node property — otherwise CREATE ... IF NOT EXISTS silently
        # no-ops against the property the old model's index already claimed.
        legacy = self.config.embedding_model == "all-MiniLM-L6-v2"
        self.INDEX_NAME = os.environ.get("SCHEMATIC_VECTOR_INDEX_NAME") or (
            "chunk_embedding" if legacy else "chunk_embedding_v2")
        self.EMBEDDING_PROPERTY = "embedding" if legacy else "embedding_v2"
        self._embedding_fn = None

    # --------------------------------------------------------
    # 嵌入函数
    # --------------------------------------------------------

    def _get_embedding_fn(self):
        """延迟加载统一 embedding 模块"""
        if self._embedding_fn is None:
            from agent_system.embedding import embed_batch
            self._embedding_fn = lambda texts: embed_batch(texts, model_name=self.config.embedding_model)
        return self._embedding_fn

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量"""
        if not texts:
            return []
        fn = self._get_embedding_fn()
        vectors = fn(texts)
        if len(texts) == 1 and vectors and not isinstance(vectors[0], list):
            vectors = [vectors]
        if len(vectors) != len(texts):
            raise ValueError("embedding batch size mismatch")
        for vector in vectors:
            if (len(vector) != self.config.embedding_dim or
                    not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector) or
                    not any(x != 0 for x in vector)):
                raise ValueError("embedding dimension mismatch, non-finite or zero vector")
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """生成查询向量"""
        return self.embed_texts([query])[0]

    # --------------------------------------------------------
    # 索引管理
    # --------------------------------------------------------

    def _check_index(self, session, *, create: bool = False):
        """Never silently adopt a legacy or differently configured production index."""
        indexes = list(session.run(
            "SHOW INDEXES YIELD name, type, options WHERE name = $name "
            "RETURN name, type, options", {"name": self.INDEX_NAME}))
        metadata = session.run(
            "MATCH (m:VectorIndexMetadata {name: $name}) "
            "RETURN m.model AS model, m.dimension AS dimension, m.scope AS scope",
            {"name": self.INDEX_NAME}).single()
        expected = (self.config.embedding_model, self.config.embedding_dim, "shared+project")
        if indexes:
            idx = indexes[0]
            dimensions = idx["options"]["indexConfig"].get("vector.dimensions")
            if idx["type"] != "VECTOR" or dimensions != expected[1]:
                raise RuntimeError("existing vector index type/dimension mismatch; use an isolated index")
            if not metadata or tuple(metadata[k] for k in ("model", "dimension", "scope")) != expected:
                raise RuntimeError("unverified legacy vector index or model/scope mismatch; migration required")
        elif metadata:
            raise RuntimeError("vector index metadata exists without index; manual repair required")
        elif not create:
            raise RuntimeError("vector index not initialized")
        return bool(indexes)

    def create_index(self):
        """创建 VECTOR INDEX（如果不存在）"""
        cypher = f"""
        CREATE VECTOR INDEX {self.INDEX_NAME} IF NOT EXISTS
        FOR (vc:VectorChunk) ON (vc.{self.EMBEDDING_PROPERTY})
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {self.config.embedding_dim},
            `vector.similarity_function`: '{self.SIMILARITY}'
          }}
        }}
        """
        with self.driver.session() as session:
            exists = self._check_index(session, create=True)
            from agent_system.embedding import get_actual_embedding_dim
            if get_actual_embedding_dim(self.config.embedding_model) != self.config.embedding_dim:
                raise ValueError("configured embedding dimension differs from loaded model")
            if not exists:
                session.run(cypher)
                session.run(
                    "CREATE (m:VectorIndexMetadata {name: $name, model: $model, "
                    "dimension: $dimension, scope: $scope})",
                    {"name": self.INDEX_NAME, "model": self.config.embedding_model,
                     "dimension": self.config.embedding_dim, "scope": "shared+project"})
        logger.info("向量索引 '%s' 已确认，dim=%s model=%s", self.INDEX_NAME, self.config.embedding_dim, self.config.embedding_model)

    # --------------------------------------------------------
    # 写入
    # --------------------------------------------------------

    def index_chunks(self, chunks: list[VectorChunk], batch_size: int = 50):
        """批量索引 chunks 到 Neo4j"""
        if not chunks:
            return
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if any(c.scope not in ("shared", "project") or
               (c.scope == "project" and not c.project_id) or
               (c.scope == "shared" and c.project_id is not None)
               for c in chunks):
            raise ValueError("VectorChunk requires explicit valid scope and ownership")
        # 生成嵌入
        texts = [c.text for c in chunks]
        embeddings = self.embed_texts(texts)
        with self.driver.session() as session:
            self._check_index(session)

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
                    "embedding_model": self.config.embedding_model,
                    "embedding_dim": self.config.embedding_dim,
                    "source": chunk.source,
                    "chunk_index": chunk.chunk_index,
                    "scope": chunk.scope,
                    "project_id": chunk.project_id if chunk.scope == "project" else None,
                })

            cypher = f"""
            UNWIND $records AS r
            MERGE (vc:VectorChunk {{id: r.id}})
            SET vc.text = r.text,
                vc.{self.EMBEDDING_PROPERTY} = r.embedding,
                vc.embedding_model = r.embedding_model,
                vc.embedding_dim = r.embedding_dim,
                vc.source = r.source,
                vc.chunk_index = r.chunk_index,
                vc.scope = r.scope,
                vc.project_id = r.project_id
            """
            with self.driver.session() as session:
                session.run(cypher, {"records": records}).consume()

        logger.info(f"已索引 {len(chunks)} 个 VectorChunk")

    # --------------------------------------------------------
    # 检索
    # --------------------------------------------------------

    def search(self, query: str, top_k: int = 5, project_id: Optional[str] = None) -> list[dict]:
        """向量相似度搜索"""
        query_embedding = self.embed_query(query)
        with self.driver.session() as session:
            self._check_index(session)

        cypher = """
        CALL db.index.vector.queryNodes($index_name, $candidate_k, $query_embedding)
        YIELD node, score
        WHERE (node.scope = 'shared'
           OR (node.scope = 'project' AND node.project_id = $project_id))
          AND node.embedding_model = $model AND node.embedding_dim = $dimension
        RETURN node.id AS id, node.text AS text, node.source AS source, score
        ORDER BY score DESC
        LIMIT $top_k
        """

        try:
            with self.driver.session() as session:
                results = list(session.run(cypher, {
                    "index_name": self.INDEX_NAME,
                    "top_k": top_k,
                    "candidate_k": max(top_k * 20, 100),
                    "project_id": project_id,
                    "model": self.config.embedding_model,
                    "dimension": self.config.embedding_dim,
                    "query_embedding": query_embedding,
                }))
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"向量搜索失败，降级到文本搜索: {e}")
            return self._fallback_text_search(query, top_k, project_id)

    def _fallback_text_search(self, query: str, top_k: int = 5,
                              project_id: Optional[str] = None) -> list[dict]:
        """向量搜索失败时的文本降级搜索"""
        # 使用 CONTAINS 进行简单文本匹配
        keywords = query.lower().split()[:3]
        if not keywords:
            return []

        conditions = " AND ".join(f"toLower(vc.text) CONTAINS $kw{i}"
                                  for i in range(len(keywords)))
        cypher = f"""
        MATCH (vc:VectorChunk)
        WHERE ({conditions}) AND (vc.scope = 'shared' OR
              (vc.scope = 'project' AND vc.project_id = $project_id))
          AND vc.embedding_model = $model AND vc.embedding_dim = $dimension
        RETURN vc.id AS id, vc.text AS text, vc.source AS source, 0.5 AS score
        LIMIT $top_k
        """

        try:
            with self.driver.session() as session:
                return [dict(r) for r in session.run(
                    cypher, {"top_k": top_k, "project_id": project_id,
                             "model": self.config.embedding_model,
                             "dimension": self.config.embedding_dim,
                             **{f"kw{i}": kw for i, kw in enumerate(keywords)}})]
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
