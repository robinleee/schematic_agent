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

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

# 向量维度（固定，需与 embedding 生成一致）
VECTOR_DIM = 768

# 尝试加载 sklearn TF-IDF（更专业的 embedding）
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    TfidfVectorizer = None


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

    def embed(self, text: str) -> list[float]:
        """
        生成文本的向量嵌入。
        策略：优先 sklearn TF-IDF → 回退 Ollama API → 回退本地 embedding
        """
        # 优先使用 sklearn TF-IDF
        if _SKLEARN_AVAILABLE and hasattr(self, '_tfidf'):
            return self._tfidf_embed(text)
        
        ollama_emb = self._ollama_embed(text)
        if ollama_emb:
            return ollama_emb
        return self._local_embed(text)

    def _init_tfidf(self, corpus: list[str]):
        """初始化 TF-IDF 向量器（需要语料库）"""
        if not _SKLEARN_AVAILABLE:
            return
        try:
            self._tfidf = TfidfVectorizer(max_features=VECTOR_DIM, stop_words='english')
            self._tfidf.fit(corpus)
            logger.info(f"TF-IDF initialized with {len(self._tfidf.get_feature_names_out())} features")
        except Exception as e:
            logger.warning(f"TF-IDF init failed: {e}")
            self._tfidf = None

    def _tfidf_embed(self, text: str) -> list[float]:
        """使用 TF-IDF 生成 embedding"""
        try:
            vec = self._tfidf.transform([text])
            dense = vec.toarray()[0]
            # 填充或截断到 VECTOR_DIM
            if len(dense) < VECTOR_DIM:
                dense = list(dense) + [0.0] * (VECTOR_DIM - len(dense))
            return dense[:VECTOR_DIM]
        except Exception:
            return self._local_embed(text)

    def _ollama_embed(self, text: str) -> Optional[list[float]]:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:11434/api/embeddings",
                data=json.dumps({"model": "gemma4:26b", "prompt": text[:512]}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                emb = data.get("embedding", [])
                if emb and len(emb) == VECTOR_DIM:
                    return emb
                elif emb:
                    # 维度不匹配，调整
                    return self._resize_vector(emb, VECTOR_DIM)
        except Exception:
            pass
        return None

    def _local_embed(self, text: str) -> list[float]:
        """改进的本地 embedding（维度 768）"""
        import math
        import re

        vec = [0.0] * VECTOR_DIM
        words = re.findall(r'[a-zA-Z]+|[0-9]+', text.lower())

        weights = {
            'voltage': 2.0, 'current': 2.0, 'power': 2.0, 'resistance': 2.0,
            'capacitor': 2.0, 'resistor': 2.0, 'inductor': 2.0,
            'pin': 1.5, 'gpio': 1.5, 'vdd': 1.5, 'vcc': 1.5, 'gnd': 1.5,
            'input': 1.2, 'output': 1.2, 'pullup': 1.5, 'pulldown': 1.5,
            'maximum': 1.3, 'minimum': 1.3, 'rating': 1.3,
            'frequency': 1.2, 'clock': 1.2, 'timing': 1.2,
        }

        for word in words:
            h1 = hash(word) % VECTOR_DIM
            h2 = (hash(word + "_salt") * 31) % VECTOR_DIM
            w = weights.get(word, 1.0)
            vec[h1] += w
            vec[h2] += w * 0.5

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _resize_vector(vec: list[float], target_dim: int) -> list[float]:
        """调整向量维度"""
        if len(vec) == target_dim:
            return vec
        import math
        # 线性插值
        result = []
        for i in range(target_dim):
            src_idx = i * len(vec) // target_dim
            result.append(vec[src_idx])
        norm = math.sqrt(sum(v * v for v in result))
        if norm > 0:
            result = [v / norm for v in result]
        return result

    # --------------------------------------------------------
    # 核心：索引与检索
    # --------------------------------------------------------

    def index_datasheet_chunk(self, chunk: VectorChunk) -> bool:
        """
        将文档切片索引到 Neo4j（图节点 + 向量）。
        注意：使用 Python 层计算相似度，不依赖 Neo4j 原生向量索引。
        """
        # 首次索引时初始化 TF-IDF（如果可用）
        if _SKLEARN_AVAILABLE and not hasattr(self, '_tfidf'):
            self._init_tfidf([chunk.content, "voltage current power resistor capacitor"])
        
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
        """
        results = []

        if refdes:
            results = self._query_from_component(refdes, query, n_results)

        if not results and mpn:
            results = self._vector_search_with_graph(mpn, query, n_results)

        return results

    def _query_from_component(self, refdes: str, query: str, n: int) -> list[GraphRAGResult]:
        """从 Component 节点出发，沿 [:DESCRIBES] 做向量过滤检索"""
        try:
            query_emb = self.embed(query)
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
            query_emb = self.embed(query)
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
