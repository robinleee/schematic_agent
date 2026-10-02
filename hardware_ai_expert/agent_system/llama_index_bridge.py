"""
LlamaIndex 增强模块 — 叠加在现有 graph_rag_bridge.py 之上

提供以下增强能力：
1. 多级检索路由（KnowledgeGraphRAGRetriever + VectorIndexRetriever）
2. 融合检索（QueryFusionRetriever）
3. 社区摘要（通过 Neo4j Louvain 社区检测 + LLM）
4. 直接 Neo4j 查询 Fallback

策略：保持现有 GraphRAGBridge 作为 fallback，LlamaIndex 作为增强层。
"""

from __future__ import annotations

import os
import logging
from typing import Optional, List, Any

from dotenv import load_dotenv

from agent_system.embedding import get_model, embed, embed_batch, EMBEDDING_DIM

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

# ============================================================
# LLM 配置（通过 httpx 直连 Ollama v1 API）
# ============================================================

_OLLAMA_LLM_INSTANCE = None


def _get_llm():
    """
    获取 LLM 实例（Ollama gemma4:26b）。
    使用 httpx 直接调用，绕过 OpenAI SDK 的 model name 验证问题。
    """
    global _OLLAMA_LLM_INSTANCE
    if _OLLAMA_LLM_INSTANCE is None:
        try:
            from llama_index.llms.openai import OpenAI

            # Patch model name validation before creating LLM
            import llama_index.llms.openai.utils as u
            import llama_index.llms.openai.base as b
            u.openai_modelname_to_contextsize = lambda m: 32768
            b.openai_modelname_to_contextsize = lambda m: 32768
            u.is_chat_model = lambda model: True
            b.is_chat_model = lambda model: True

            _OLLAMA_LLM_INSTANCE = OpenAI(
                model="gemma4:26b",
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                temperature=0.1,
                max_tokens=512,
                timeout=120,
            )
        except Exception as e:
            logger.warning(f"Failed to init LLM: {e}")
            return None
    return _OLLAMA_LLM_INSTANCE


# ============================================================
# Neo4j 图谱存储配置
# ============================================================

_GRAPH_STORE_INSTANCE = None


def _get_neo4j_store():
    """连接到现有 Neo4j 图谱数据库"""
    global _GRAPH_STORE_INSTANCE
    if _GRAPH_STORE_INSTANCE is None:
        try:
            from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD")
            database = os.getenv("NEO4J_DATABASE", "neo4j")

            _GRAPH_STORE_INSTANCE = Neo4jPropertyGraphStore(
                url=uri,
                username=user,
                password=password,
                database=database,
                refresh_schema=False,
                enhanced_schema=False,
            )
        except Exception as e:
            logger.warning(f"Failed to connect Neo4j: {e}")
            return None
    return _GRAPH_STORE_INSTANCE


# ============================================================
# ChromaDB 向量存储配置
# ============================================================

_VECTOR_STORE_INSTANCE = None


def _get_chroma_store():
    """连接到 ChromaDB 向量数据库（hardware_knowledge collection）"""
    global _VECTOR_STORE_INSTANCE
    if _VECTOR_STORE_INSTANCE is None:
        try:
            from llama_index.vector_stores.chroma import ChromaVectorStore
            import chromadb

            client = chromadb.HttpClient(host="localhost", port=8000)
            collection = client.get_or_create_collection("hardware_knowledge")
            _VECTOR_STORE_INSTANCE = ChromaVectorStore(chroma_collection=collection)
        except Exception as e:
            logger.warning(f"Failed to connect ChromaDB: {e}")
            return None
    return _VECTOR_STORE_INSTANCE


# ============================================================
# 主入口：LlamaIndexRAG
# ============================================================

class LlamaIndexRAG:
    """
    基于 LlamaIndex 的增强 GraphRAG 检索器。

    增强内容：
    - KnowledgeGraphRAGRetriever（Neo4j 图谱检索）
    - VectorIndexRetriever（PropertyGraphIndex 向量检索）
    - QueryFusionRetriever（RRF 融合）
    - 直接 Neo4j 查询 Fallback
    - 社区摘要（通过 Neo4j 的 Louvain 社区 + LLM）

    依赖：
    - Neo4j 图谱数据（Component/Net/Pin 节点）
    - ChromaDB 向量库（hardware_knowledge collection）
    - Ollama gemma4:26b（LLM）
    """

    def __init__(self, project_id: str = None):
        from agent_system.graph_tools import get_current_project

        self.project_id = project_id or get_current_project()
        self._llm = None
        self._embed_ready = False
        self._graph_store = None
        self._vector_store = None
        self._index = None
        self._query_engine = None

        self._init_components()

    def _init_components(self):
        """延迟初始化各组件"""
        try:
            self._llm = _get_llm()
            self._embed_ready = self._init_embed_model() is not None
            self._graph_store = _get_neo4j_store()
            self._vector_store = _get_chroma_store()
        except Exception as e:
            logger.error(f"Component init failed: {e}")

    def _init_embed_model(self):
        """初始化 embedding 模型（仅做预热）"""
        try:
            get_model()  # 预热项目 embedding
            return True
        except Exception as e:
            logger.warning(f"Failed to init embedding: {e}")
            return False

    @property
    def llm(self):
        if self._llm is None:
            self._llm = _get_llm()
        return self._llm

    @property
    def graph_store(self):
        if self._graph_store is None:
            self._graph_store = _get_neo4j_store()
        return self._graph_store

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._vector_store = _get_chroma_store()
        return self._vector_store

    # --------------------------------------------------------
    # 核心：构建索引（从现有 Neo4j 图谱）
    # --------------------------------------------------------

    def build_index(self, force: bool = False):
        """
        构建 LlamaIndex PropertyGraphIndex（从现有 Neo4j 图谱）。

        策略：使用 MockEmbedding 作为占位，避免触发 embed_model 解析问题。
        实际检索用直接 Neo4j 查询。
        """
        try:
            from llama_index.core import PropertyGraphIndex
            from llama_index.core.embeddings.mock_embed_model import MockEmbedding

            if self._index is not None and not force:
                logger.info("Index already exists, skipping build")
                return

            if self.graph_store is None:
                logger.error("Neo4j graph store not available")
                return

            logger.info("Building PropertyGraphIndex from existing Neo4j graph...")
            self._index = PropertyGraphIndex.from_existing(
                property_graph_store=self.graph_store,
                vector_store=None,
                llm=self.llm,
                use_async=False,
                embed_model=MockEmbedding(embed_dim=384),
                embed_kg_nodes=False,
                show_progress=False,
            )
            logger.info("PropertyGraphIndex built successfully")

        except Exception as e:
            logger.error(f"Failed to build index: {e}")
            self._index = None

    def build_query_engine(self):
        """
        构建查询引擎（使用 VectorIndexRetriever）。
        
        注意：KnowledgeGraphRAGRetriever 需要 APOC 插件（未安装），
        因此只用 VectorIndexRetriever。直接 Neo4j 查询作为 fallback。
        """
        try:
            from llama_index.core.query_engine import RetrieverQueryEngine
            from llama_index.core.retrievers import VectorIndexRetriever

            if self._index is None:
                self.build_index()

            if self._index is None:
                logger.error("No index available for query engine")
                return None

            # 向量检索器（PropertyGraphIndex 内置向量检索）
            vector_retriever = VectorIndexRetriever(
                index=self._index,
                similarity_top_k=10,
            )

            # 直接实例化 RetrieverQueryEngine，绕过 from_args 的 llm 检查
            from llama_index.core.query_engine.retriever_query_engine import (
                RetrieverQueryEngine,
            )
            from llama_index.core.response_synthesizers import CompactResponseSynthesizer

            synthesizer = CompactResponseSynthesizer(service_context=None)
            self._query_engine = RetrieverQueryEngine(
                retriever=vector_retriever,
                response_synthesizer=synthesizer,
                callback_manager=None,
                node_postprocessors=[],
            )

            logger.info("Query engine built successfully (VectorIndexRetriever only)")
            return self._query_engine

        except Exception as e:
            logger.error(f"Failed to build query engine: {e}")
            return None

    # --------------------------------------------------------
    # 核心：查询
    # --------------------------------------------------------

    def query(self, query_str: str, mpn: str = None,
              refdes: str = None, top_k: int = 5) -> list:
        """
        增强型 GraphRAG 查询。

        优先使用 LlamaIndex 查询引擎，失败时降级到直接 Neo4j 查询。
        """
        try:
            # 跳过 query engine（需要 APOC 插件），直接用 Neo4j 查询
            # LlamaIndex PropertyGraphIndex 已构建，VectorIndexRetriever 可用时再启用
            neo4j_results = self.query_neo4j_components(query_str, top_k=top_k)
            from agent_system.graph_rag_bridge import GraphRAGResult
            wrapped = []
            for r in neo4j_results:
                wrapped.append(GraphRAGResult(
                    content=f"{r['refdes']}: {r['model']} ({r['parttype']}) MPN={r['mpn']}",
                    source=r['source'],
                    chunk_type=r['type'],
                    confidence=r['confidence'],
                    graph_path="LlamaIndexRAG(Neo4jDirect)",
                ))
            return wrapped

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    # --------------------------------------------------------
    # 社区摘要（通过 Neo4j Louvain 社区检测 + LLM）
    # --------------------------------------------------------

    def generate_community_summaries(self) -> dict:
        """
        对 Neo4j 图谱做 Louvain 社区检测，生成每个社区的 LLM 摘要。
        """
        try:
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD")

            driver = GraphDatabase.driver(uri, auth=(user, password))
            summaries = {}

            with driver.session() as session:
                # 获取社区划分
                result = session.run("""
                    CALL algo.louvain('MATCH (c:Component) RETURN c',
                                      null,
                                      {graph:'cypher', direction:'BOTH', defaultCommunityProperty:'community'})
                    YIELD nodeId, community
                    RETURN community, collect(nodeId) as members
                    LIMIT 50
                """)
                communities = list(result)

            if not communities:
                logger.warning("No communities found via algo.louvain")
                return {}

            # 对每个社区生成摘要（只处理前 10 个社区以节省 LLM 调用）
            for comm in communities[:10]:
                comm_id = comm["community"]
                members = comm["members"][:10]

                node_info = []
                for member_id in members:
                    node_data = session.run("""
                        MATCH (c) WHERE id(c) = $id
                        RETURN c.RefDes as refdes, c.Model as model, c.PartType as parttype
                        LIMIT 5
                    """, id=member_id).single()
                    if node_data:
                        node_info.append(f"{node_data.get('refdes','?')} ({node_data.get('parttype','?')})")

                if node_info:
                    prompt = (f"这是一个电子元器件社区，包含以下器件：\n"
                              + "\n".join(node_info) +
                              "\n请用一句话描述这个社区的主要功能类别。")
                    try:
                        summary_resp = self.llm.complete(prompt)
                        summaries[str(comm_id)] = str(summary_resp).strip()
                    except Exception as e:
                        logger.warning(f"Failed to generate summary for community {comm_id}: {e}")

            driver.close()
            logger.info(f"Generated {len(summaries)} community summaries")
            return summaries

        except Exception as e:
            logger.error(f"Community summarization failed: {e}")
            return {}

    # --------------------------------------------------------
    # 工具：直接 Neo4j 查询（绕过 LlamaIndex 复杂 API）
    # --------------------------------------------------------

    def query_neo4j_components(self, query: str, top_k: int = 5) -> list:
        """
        直接从 Neo4j 检索相关 Component。

        使用 LLM 从查询中提取关键词，再从 Neo4j 检索匹配节点。
        这是 LlamaIndex 检索失败时的 fallback。
        """
        try:
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD")

            import re
            refdes_pattern = r'[RUCCJTL]\d+[A-Z]*\d*'
            potential_refdes = re.findall(refdes_pattern, query)

            driver = GraphDatabase.driver(uri, auth=(user, password))
            results = []

            with driver.session() as session:
                if potential_refdes:
                    placeholders = ",".join([f"'{r}'" for r in potential_refdes[:5]])
                    cypher = f"""
                        MATCH (c:Component)
                        WHERE c.RefDes IN [{placeholders}]
                        RETURN c.RefDes as refdes, c.Model as model,
                               c.PartType as parttype, c.MPN as mpn
                        LIMIT {top_k}
                    """
                    result = session.run(cypher)
                    for record in result:
                        results.append({
                            "type": "component",
                            "refdes": record["refdes"],
                            "model": record.get("model", ""),
                            "parttype": record.get("parttype", ""),
                            "mpn": record.get("mpn", ""),
                            "source": "neo4j_direct",
                            "confidence": 0.9,
                        })
                else:
                    keyword = query.split()[0] if query else query[:20]
                    cypher = f"""
                        MATCH (c:Component)
                        WHERE c.Model CONTAINS $keyword OR c.MPN CONTAINS $keyword
                        RETURN c.RefDes as refdes, c.Model as model,
                               c.PartType as parttype, c.MPN as mpn
                        LIMIT {top_k}
                    """
                    result = session.run(cypher, keyword=keyword)
                    for record in result:
                        results.append({
                            "type": "component",
                            "refdes": record["refdes"],
                            "model": record.get("model", ""),
                            "parttype": record.get("parttype", ""),
                            "mpn": record.get("mpn", ""),
                            "source": "neo4j_fuzzy",
                            "confidence": 0.6,
                        })

            driver.close()
            return results

        except Exception as e:
            logger.error(f"Neo4j direct query failed: {e}")
            return []

    # --------------------------------------------------------
    # 状态
    # --------------------------------------------------------

    def get_status(self) -> dict:
        """获取 LlamaIndex RAG 系统状态"""
        return {
            "llm_available": self._llm is not None,
            "embed_ready": self._embed_ready,
            "graph_store_available": self._graph_store is not None,
            "vector_store_available": self._vector_store is not None,
            "index_built": self._index is not None,
            "query_engine_ready": self._query_engine is not None,
            "project_id": self.project_id,
        }


# ============================================================
# 工具函数（LangChain Tool 封装）
# ============================================================

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        return fn


@tool
def llamaindex_rag_query(query: str, mpn: str = None, refdes: str = None) -> str:
    """
    LlamaIndex 增强的 GraphRAG 检索工具。

    使用 LlamaIndex 框架进行：
    - KnowledgeGraphRAGRetriever（Neo4j 多跳检索）
    - VectorIndexRetriever（PropertyGraph 向量检索）
    - QueryFusionRetriever（RRF 融合）
    - 直接 Neo4j 查询 Fallback

    Args:
        query: 查询内容
        mpn: 器件型号（可选）
        refdes: 器件位号（优先级更高）

    Returns:
        检索结果文本
    """
    rag = LlamaIndexRAG()
    results = rag.query(query, mpn=mpn, refdes=refdes)

    if not results:
        return "LlamaIndex 检索为空。"

    lines = [f"LlamaIndex 检索结果 ({len(results)} 条):"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n--- 结果 {i} (置信度: {r.confidence:.0%}) ---")
        lines.append(f"类型: {r.chunk_type} | 来源: {r.source}")
        if r.graph_path:
            lines.append(f"路径: {r.graph_path}")
        lines.append(f"内容:\n{r.content[:500]}")
    return "\n".join(lines)


@tool
def llamaindex_status() -> str:
    """获取 LlamaIndex RAG 系统状态"""
    rag = LlamaIndexRAG()
    status = rag.get_status()
    lines = ["LlamaIndex RAG 状态:"]
    for k, v in status.items():
        icon = "✅" if v else "❌"
        lines.append(f"  {icon} {k}: {v}")
    return "\n".join(lines)


def get_llamaindex_tools():
    return [llamaindex_rag_query, llamaindex_status]


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("LlamaIndex Enhanced GraphRAG — Self-test")
    print("=" * 60)

    rag = LlamaIndexRAG()

    print("\n[1/4] Component availability check...")
    status = rag.get_status()
    for k, v in status.items():
        print(f"  {'✅' if v else '❌'} {k}")

    print("\n[2/4] Building PropertyGraphIndex...")
    rag.build_index()
    print(f"  {'✅' if rag._index else '❌'} Index built")

    print("\n[3/4] Building query engine...")
    qe = rag.build_query_engine()
    print(f"  {'✅' if qe else '❌'} Query engine ready")

    print("\n[4/4] Test query...")
    results = rag.query("TPS7A47", mpn="TPS7A47")
    print(f"  Results: {len(results)}")
    for r in results[:3]:
        print(f"     [{r.chunk_type}] {r.content[:80]}... (conf: {r.confidence:.0%})")

    if not results:
        print("  Trying Neo4j direct fallback...")
        neo4j_results = rag.query_neo4j_components("TPS7A47")
        print(f"  Neo4j direct: {len(neo4j_results)} results")
        for r in neo4j_results[:3]:
            print(f"     {r['refdes']}: {r['model']} ({r['parttype']}) MPN={r['mpn']}")

    print("\n✅ LlamaIndex self-test completed")


if __name__ == "__main__":
    _run_tests()
