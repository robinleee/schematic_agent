"""
True GraphRAG 桥接模块 (Neo4j 原生向量索引版)

实现 Neo4j 图谱中的原生向量检索：
  1. 文档切片作为 VectorChunk 节点存入 Neo4j（含 embedding 向量）
  2. 使用 Neo4j 5.x 原生 VECTOR INDEX 做相似度搜索
  3. VectorChunk 与 Component 通过 [:DESCRIBES] 关系关联
  4. 联合检索：向量相似度 + 图结构跳转

优势：无需 ChromaDB，单库（Neo4j）搞定图+向量。
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

from dotenv import load_dotenv

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

from agent_system.embedding import embed, embed_batch, EMBEDDING_DIM

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

VECTOR_DIM = EMBEDDING_DIM


# ============================================================
# 数据模型
# ============================================================

@dataclass
class VectorChunk:
    """向量切片元数据"""
    chunk_id: str
    mpn: str
    content: str
    chunk_type: str = "spec"
    page: int = 0
    source: str = ""


@dataclass
class GraphRAGResult:
    """联合检索结果"""
    content: str
    source: str
    chunk_type: str
    confidence: float
    graph_path: str = ""


# ============================================================
# GraphRAG Bridge
# ============================================================

class GraphRAGBridge:
    """True GraphRAG 桥接器（Neo4j 原生向量索引版）"""

    def __init__(self):
        self._driver = None
        self._vector_index_ready = False

    def _get_driver(self):
        if self._driver is None:
            if GraphDatabase is None:
                raise RuntimeError("neo4j package not installed")
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "SecretPassword123")
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    # --------------------------------------------------------
    # Embedding 生成
    # --------------------------------------------------------

    def embed(self, text: str, keep_loaded: bool = True) -> list[float]:
        """Generate semantic embedding using unified sentence-transformers model."""
        return embed(text, keep_loaded=keep_loaded)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts (more efficient than individual calls)."""
        return embed_batch(texts)

    # --------------------------------------------------------
    # 核心：索引与检索
    # --------------------------------------------------------

    def index_datasheet_chunk(self, chunk: VectorChunk) -> bool:
        """
        将文档切片索引到 Neo4j（图节点 + 向量）。
        注意：使用 Python 层计算相似度，不依赖 Neo4j 原生向量索引。
        """
        try:
            emb = self.embed(chunk.content)

            driver = self._get_driver()
            with driver.session() as session:
                # 创建 VectorChunk 节点（含 embedding 向量）
                session.run("""
                    MERGE (vc:VectorChunk {chunk_id: $chunk_id})
                    SET vc.mpn = $mpn,
                        vc.content = $content,
                        vc.content_preview = $preview,
                        vc.chunk_type = $chunk_type,
                        vc.page = $page,
                        vc.source = $source,
                        vc.embedding = $embedding,
                        vc.indexed_at = datetime(),
                        vc.vector_dim = $dim
                """, {
                    "chunk_id": chunk.chunk_id,
                    "mpn": chunk.mpn,
                    "content": chunk.content,
                    "preview": chunk.content[:200],
                    "chunk_type": chunk.chunk_type,
                    "page": chunk.page,
                    "source": chunk.source,
                    "embedding": emb,
                    "dim": len(emb)
                })

                # 建立 [:DESCRIBES] 关系（精确匹配）
                session.run("""
                    MATCH (vc:VectorChunk {chunk_id: $chunk_id})
                    MATCH (c:Component)
                    WHERE c.RefDes = $mpn OR c.Model CONTAINS $mpn OR $mpn CONTAINS c.Model
                    MERGE (vc)-[r:DESCRIBES]->(c)
                    SET r.rel_type = $rel_type,
                        r.confidence = 1.0,
                        r.created_at = datetime()
                """, {
                    "chunk_id": chunk.chunk_id,
                    "mpn": chunk.mpn,
                    "rel_type": chunk.chunk_type
                })

                # 模糊匹配 Model 字段
                session.run("""
                    MATCH (vc:VectorChunk {chunk_id: $chunk_id})
                    MATCH (c:Component)
                    WHERE c.Model =~ $pattern
                    MERGE (vc)-[r:DESCRIBES]->(c)
                    SET r.rel_type = $rel_type,
                        r.confidence = 0.9,
                        r.created_at = datetime()
                """, {
                    "chunk_id": chunk.chunk_id,
                    "pattern": f"(?i).*{chunk.mpn}.*",
                    "rel_type": chunk.chunk_type
                })

            logger.info(f"Indexed chunk: {chunk.chunk_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to index chunk {chunk.chunk_id}: {e}")
            return False

    def graph_rag_query(self, query: str, mpn: str = None,
                        refdes: str = None, n_results: int = 5) -> list[GraphRAGResult]:
        """
        True GraphRAG 联合检索。

        策略：
        1. refdes 优先：从 Component 出发 → [:DESCRIBES] → VectorChunk → 向量过滤
        2. mpn 次之：向量检索所有 VectorChunk → 图谱增强
        3. Fallback: ChromaDB hardware_knowledge 向量检索
        """
        results = []

        if refdes:
            results = self._query_from_component(refdes, query, n_results)

        if not results and mpn:
            results = self._vector_search_with_graph(mpn, query, n_results)

        # Fallback: ChromaDB hardware_knowledge
        if not results:
            results = self._chromadb_fallback(mpn, query, n_results)

        return results

    def _query_from_component(self, refdes: str, query: str, n: int) -> list[GraphRAGResult]:
        """从 Component 节点出发，沿 [:DESCRIBES] 做向量过滤检索"""
        try:
            query_emb = self.embed(query, keep_loaded=False)
            driver = self._get_driver()

            with driver.session() as session:
                # 方法：找到与 Component 关联的 VectorChunk，再计算向量相似度
                result = session.run("""
                    MATCH (c:Component {RefDes: $refdes})<-[r:DESCRIBES]-(vc:VectorChunk)
                    WITH vc, r.confidence AS rel_conf
                    WITH vc, rel_conf,
                         gds.similarity.cosine(vc.embedding, $query_emb) AS sim
                    WHERE sim IS NOT NULL
                    RETURN vc.content AS content,
                           vc.source AS source,
                           vc.chunk_type AS chunk_type,
                           sim * rel_conf AS score
                    ORDER BY score DESC
                    LIMIT $limit
                """, {"refdes": refdes, "query_emb": query_emb, "limit": n})

                records = list(result)
                return [
                    GraphRAGResult(
                        content=r["content"],
                        source=r["source"],
                        chunk_type=r["chunk_type"],
                        confidence=r["score"],
                        graph_path=f"Component({refdes})<-[:DESCRIBES]-VectorChunk"
                    )
                    for r in records
                ]

        except Exception as e:
            logger.error(f"Graph query from component failed: {e}")
            return []

    def _vector_search_with_graph(self, mpn: str, query: str, n: int) -> list[GraphRAGResult]:
        """向量检索 + 图谱关联增强（Python 层计算相似度）"""
        try:
            query_emb = self.embed(query, keep_loaded=False)
            driver = self._get_driver()

            with driver.session() as session:
                # 拉取候选 VectorChunk（按 mpn 过滤）
                result = session.run("""
                    MATCH (vc:VectorChunk)
                    WHERE vc.mpn = $mpn OR vc.mpn CONTAINS $mpn OR $mpn CONTAINS vc.mpn
                    RETURN vc.chunk_id AS chunk_id,
                           vc.content AS content,
                           vc.source AS source,
                           vc.chunk_type AS chunk_type,
                           vc.embedding AS embedding
                    LIMIT 100
                """, {"mpn": mpn})

                candidates = list(result)
                if not candidates:
                    return []

                # Python 层计算 cosine 相似度
                scored = []
                for r in candidates:
                    emb = r["embedding"]
                    if not emb:
                        continue
                    dot = sum(a * b for a, b in zip(query_emb, emb))
                    scored.append((dot, r))

                scored.sort(key=lambda x: x[0], reverse=True)

                # 取 top-n，图谱增强
                results = []
                for score, r in scored[:n]:
                    confidence = max(0.0, min(1.0, score))
                    results.append(GraphRAGResult(
                        content=r["content"],
                        source=r["source"],
                        chunk_type=r["chunk_type"],
                        confidence=confidence
                    ))

                return results

        except Exception as e:
            logger.error(f"Vector search with graph failed: {e}")
            return []

    def _chromadb_fallback(self, mpn: str, query: str, n: int) -> list[GraphRAGResult]:
        """Fallback: ChromaDB hardware_knowledge 向量检索"""
        try:
            import chromadb
            from agent_system.knowledge_router import _get_chroma_client

            client = _get_chroma_client()
            coll = client.get_collection("hardware_knowledge")

            # Enhance query with MPN for cross-language matching
            enhanced_query = f"{mpn} {query}" if mpn else query
            query_emb = self.embed(enhanced_query, keep_loaded=False)

            where_filter = {"mpn": {"$eq": mpn}} if mpn else None

            results = coll.query(
                query_embeddings=[query_emb],
                n_results=n,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            if not results or not results.get("documents") or not results["documents"][0]:
                return []

            graph_results = []
            for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
                confidence = max(0.0, 1.0 - dist)
                if confidence >= 0.2:
                    graph_results.append(GraphRAGResult(
                        content=doc,
                        source=meta.get("source", "chromadb"),
                        chunk_type=meta.get("type", "datasheet"),
                        confidence=confidence,
                        graph_path=f"ChromaDB({mpn})" if mpn else "ChromaDB"
                    ))

            return graph_results

        except Exception as e:
            logger.error(f"ChromaDB fallback failed: {e}")
            return []

    # --------------------------------------------------------
    # 统计与维护
    # --------------------------------------------------------

    def get_stats(self) -> dict:
        """获取 GraphRAG 统计"""
        stats = {
            "vector_chunks": 0,
            "describes_relations": 0,
            "linked_components": 0,
        }
        try:
            driver = self._get_driver()
            with driver.session() as session:
                stats["vector_chunks"] = session.run(
                    "MATCH (vc:VectorChunk) RETURN count(vc) AS cnt"
                ).single()["cnt"]
                stats["describes_relations"] = session.run(
                    "MATCH ()-[r:DESCRIBES]->() RETURN count(r) AS cnt"
                ).single()["cnt"]
                stats["linked_components"] = session.run(
                    "MATCH (c:Component)<-[:DESCRIBES]-() RETURN count(DISTINCT c) AS cnt"
                ).single()["cnt"]
        except Exception:
            pass
        return stats

    def reset(self):
        """重置 GraphRAG 数据"""
        try:
            driver = self._get_driver()
            with driver.session() as session:
                session.run("MATCH ()-[r:DESCRIBES]->() DELETE r")
                session.run("MATCH (vc:VectorChunk) DELETE vc")
            logger.info("GraphRAG data reset")
        except Exception as e:
            logger.error(f"Reset failed: {e}")


# ============================================================
# LangChain Tool 封装
# ============================================================

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        return fn


@tool
def search_with_graph_rag(query: str, mpn: str = None, refdes: str = None) -> str:
    """
    True GraphRAG 联合检索工具。

    结合 Neo4j 图谱结构和向量语义进行检索。
    如果提供了 refdes，优先从图谱中的 Component 节点出发检索关联文档。

    Args:
        query: 查询内容
        mpn: 器件型号
        refdes: 器件位号（优先级更高）

    Returns:
        检索结果文本
    """
    bridge = GraphRAGBridge()
    try:
        results = bridge.graph_rag_query(query, mpn=mpn, refdes=refdes)
        if not results:
            target = refdes or mpn or "unknown"
            return f"未找到 {target} 的相关信息。"

        lines = [f"GraphRAG 检索结果 ({len(results)} 条):"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n--- 结果 {i} (置信度: {r.confidence:.0%}) ---")
            lines.append(f"类型: {r.chunk_type} | 来源: {r.source}")
            if r.graph_path:
                lines.append(f"图谱: {r.graph_path}")
            lines.append(f"内容:\n{r.content[:500]}")
        return "\n".join(lines)
    finally:
        bridge.close()


@tool
def get_graph_rag_status() -> str:
    """获取 GraphRAG 系统状态"""
    bridge = GraphRAGBridge()
    try:
        stats = bridge.get_stats()
        return f"""GraphRAG 状态:
  - VectorChunk 节点: {stats['vector_chunks']}
  - [:DESCRIBES] 关系: {stats['describes_relations']}
  - 已关联 Component: {stats['linked_components']}
"""
    finally:
        bridge.close()


def get_graph_rag_tools():
    return [search_with_graph_rag, get_graph_rag_status]


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("GraphRAG Bridge Self-test (Neo4j Native Vector)")
    print("=" * 60)

    bridge = GraphRAGBridge()

    # 测试 1: 索引
    print("\n[1/4] Indexing test chunks...")
    test_chunks = [
        VectorChunk(
            chunk_id="test_tps5430_001",
            mpn="TPS5430",
            content="TPS5430 3A Step-Down Swift Converter. "
                    "Input Voltage: 5.5V to 36V. Output Voltage: Adjustable down to 1.22V. "
                    "Switching Frequency: 500kHz fixed. Pin 1 (VIN): Input supply voltage.",
            chunk_type="spec", page=1, source="TPS5430.pdf"
        ),
        VectorChunk(
            chunk_id="test_tps5430_002",
            mpn="TPS5430",
            content="Decoupling Capacitor Selection. Input capacitor: 10uF ceramic, X5R/X7R. "
                    "Place input capacitor within 2mm of VIN pin. Use multiple vias to ground plane.",
            chunk_type="application", page=12, source="TPS5430.pdf"
        ),
    ]
    for chunk in test_chunks:
        success = bridge.index_datasheet_chunk(chunk)
        print(f"  {'✅' if success else '❌'} {chunk.chunk_id}")

    # 测试 2: 向量检索
    print("\n[2/4] Vector search (mpn=TPS5430)...")
    results = bridge.graph_rag_query("input voltage range", mpn="TPS5430")
    if results:
        print(f"  ✅ Found {len(results)} results")
        for r in results:
            print(f"     [{r.chunk_type}] {r.content[:60]}...")
    else:
        print("  ⚠️  No results")

    # 测试 3: 图遍历检索
    print("\n[3/4] Graph traversal (refdes=U50001)...")
    try:
        driver = bridge._get_driver()
        with driver.session() as session:
            rec = session.run("MATCH (c:Component {RefDes: 'U50001'}) RETURN c.RefDes").single()
            if rec:
                results = bridge.graph_rag_query("voltage", refdes="U50001")
                if results:
                    print(f"  ✅ Graph traversal found {len(results)} results")
                else:
                    print("  ⚠️  Component exists but no DESCRIBES link (check model name matching)")
            else:
                print("  ⚠️  U50001 not in graph")
    except Exception as e:
        print(f"  ⚠️  {e}")

    # 测试 4: 统计
    print("\n[4/4] Stats...")
    stats = bridge.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    bridge.close()
    print("\n✅ GraphRAG Bridge test completed")


if __name__ == "__main__":
    _run_tests()
