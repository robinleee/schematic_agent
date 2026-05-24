"""GraphRAG 管道主入口

提供统一接口：
  - build_index(pdf_dir): PDF → chunks → 向量索引 → 实体抽取 → 社区检测
  - query(question, mode): 三级检索（local/global/graph/auto）
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from agent_system.graph_rag.schemas import (
    VectorChunk, RetrievalResult, GraphRAGConfig,
)
from agent_system.graph_rag.indexers.vector_indexer import Neo4jVectorIndexer
from agent_system.graph_rag.indexers.entity_extractor import HardwareEntityExtractor
from agent_system.graph_rag.indexers.community_detector import CommunityDetector
from agent_system.graph_rag.retrievers.local_retriever import LocalRetriever
from agent_system.graph_rag.retrievers.global_retriever import GlobalRetriever
from agent_system.graph_rag.retrievers.graph_retriever import GraphRetriever

logger = logging.getLogger(__name__)


class GraphRAGPipeline:
    """True GraphRAG 管道"""

    def __init__(self, driver=None, config: Optional[GraphRAGConfig] = None,
                 llm_client=None):
        self.config = config or GraphRAGConfig()
        self._driver = driver
        self._llm = llm_client

        # 延迟初始化组件
        self._vector_indexer = None
        self._entity_extractor = None
        self._community_detector = None
        self._local_retriever = None
        self._global_retriever = None
        self._graph_retriever = None

    # --------------------------------------------------------
    # 延迟初始化
    # --------------------------------------------------------

    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self.config.neo4j_uri,
                auth=(self.config.neo4j_user, self.config.neo4j_password),
            )
        return self._driver

    @property
    def vector_indexer(self) -> Neo4jVectorIndexer:
        if self._vector_indexer is None:
            self._vector_indexer = Neo4jVectorIndexer(self.driver, self.config)
        return self._vector_indexer

    @property
    def entity_extractor(self) -> HardwareEntityExtractor:
        if self._entity_extractor is None:
            self._entity_extractor = HardwareEntityExtractor(self._llm, self.config)
        return self._entity_extractor

    @property
    def community_detector(self) -> CommunityDetector:
        if self._community_detector is None:
            self._community_detector = CommunityDetector(self.driver, self._llm, self.config)
        return self._community_detector

    @property
    def local_retriever(self) -> LocalRetriever:
        if self._local_retriever is None:
            self._local_retriever = LocalRetriever(self.vector_indexer, self.config)
        return self._local_retriever

    @property
    def global_retriever(self) -> GlobalRetriever:
        if self._global_retriever is None:
            self._global_retriever = GlobalRetriever(self.driver, self.vector_indexer, self.config)
        return self._global_retriever

    @property
    def graph_retriever(self) -> GraphRetriever:
        if self._graph_retriever is None:
            self._graph_retriever = GraphRetriever(self.driver, self.config)
        return self._graph_retriever

    # --------------------------------------------------------
    # 索引构建
    # --------------------------------------------------------

    def build_index(self, pdf_dir: str = None, texts: list[dict] = None) -> dict:
        """
        构建 GraphRAG 索引

        支持两种输入：
        1. pdf_dir: PDF 目录路径，自动解析
        2. texts: 预处理好的文本列表 [{"text": ..., "source": ...}]

        Returns:
            构建统计信息
        """
        stats = {
            "chunks_indexed": 0,
            "entities_extracted": 0,
            "relations_extracted": 0,
            "communities_detected": 0,
            "errors": [],
        }

        # Step 1: 准备文本 chunks
        chunks = []

        if pdf_dir and os.path.isdir(pdf_dir):
            chunks = self._load_pdfs(pdf_dir)
        elif texts:
            chunks = [
                VectorChunk(
                    id=str(uuid.uuid4()),
                    text=t["text"],
                    source=t.get("source", ""),
                    chunk_index=i,
                )
                for i, t in enumerate(texts)
            ]
        else:
            # 尝试从 ChromaDB 迁移
            chunks = self._migrate_from_chromadb()

        if not chunks:
            logger.warning("没有可索引的文本")
            return stats

        # Step 2: 向量索引
        try:
            self.vector_indexer.create_index()
            self.vector_indexer.index_chunks(chunks)
            stats["chunks_indexed"] = len(chunks)
            # 等待索引生效
            import time
            time.sleep(2)
        except Exception as e:
            stats["errors"].append(f"向量索引失败: {e}")
            logger.error(f"向量索引失败: {e}")

        # Step 3: 实体抽取（仅对前 20 个 chunks，避免耗时）
        try:
            all_entities = []
            all_relations = []
            for chunk in chunks[:20]:
                entities, relations = self.entity_extractor.extract(chunk.text)
                all_entities.extend(entities)
                all_relations.extend(relations)

            if all_entities:
                self.entity_extractor.write_to_neo4j(all_entities, all_relations, self.driver)

            stats["entities_extracted"] = len(all_entities)
            stats["relations_extracted"] = len(all_relations)
        except Exception as e:
            stats["errors"].append(f"实体抽取失败: {e}")
            logger.warning(f"实体抽取失败: {e}")

        # Step 4: 社区检测
        try:
            communities = self.community_detector.detect_communities()
            if communities:
                communities = self.community_detector.generate_summaries(communities)
                self.community_detector.write_communities(communities)
            stats["communities_detected"] = len(communities)
        except Exception as e:
            stats["errors"].append(f"社区检测失败: {e}")
            logger.warning(f"社区检测失败: {e}")

        logger.info(f"GraphRAG 索引构建完成: {stats}")
        return stats

    # --------------------------------------------------------
    # 查询
    # --------------------------------------------------------

    def query(self, question: str, mode: str = "auto", top_k: int = 5) -> list[RetrievalResult]:
        """
        查询 GraphRAG

        Args:
            question: 查询文本
            mode: 检索模式
                - "local": 向量相似度检索
                - "global": 社区报告检索
                - "graph": 图遍历检索
                - "auto": 自动选择（默认）
            top_k: 返回结果数

        Returns:
            检索结果列表
        """
        if mode == "auto":
            mode = self._infer_mode(question)

        if mode == "local":
            return self.local_retriever.retrieve(question, top_k)
        elif mode == "global":
            return self.global_retriever.retrieve(question, top_k)
        elif mode == "graph":
            return self.graph_retriever.retrieve(question, top_k)
        else:
            # 融合检索
            return self._hybrid_retrieve(question, top_k)

    def _infer_mode(self, question: str) -> str:
        """根据问题推断最佳检索模式"""
        q = question.lower()

        # 具体器件/型号查询 → graph
        import re
        if re.search(r'\b[URLCJFD]\d{3,}\b', question.upper()):
            return "graph"
        if re.search(r'\b[A-Z]{2,4}\d', question.upper()):
            return "graph"

        # 宏观问题 → global
        macro_keywords = ["架构", "整体", "系统", "所有", "architecture", "overview", "整体架构"]
        if any(kw in q for kw in macro_keywords):
            return "global"

        # 默认 → local
        return "local"

    def _hybrid_retrieve(self, question: str, top_k: int) -> list[RetrievalResult]:
        """融合检索：合并三种模式的结果"""
        results = []
        seen = set()

        # 每种模式取 top_k//2 + 1
        per_mode = max(top_k // 2, 2)

        for retriever in [self.local_retriever, self.graph_retriever, self.global_retriever]:
            try:
                mode_results = retriever.retrieve(question, per_mode)
                for r in mode_results:
                    if r.source not in seen:
                        seen.add(r.source)
                        results.append(r)
            except Exception:
                continue

        # 按分数排序
        results.sort(key=lambda x: -x.score)
        return results[:top_k]

    # --------------------------------------------------------
    # 数据加载
    # --------------------------------------------------------

    def _load_pdfs(self, pdf_dir: str) -> list[VectorChunk]:
        """从 PDF 目录加载文本"""
        chunks = []
        pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]

        if not pdf_files:
            logger.warning(f"目录 {pdf_dir} 中没有 PDF 文件")
            return []

        for pdf_file in pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_file)
            try:
                # 使用现有的 datasheet_parser
                from agent_system.datasheet_parser import DatasheetParser
                parser = DatasheetParser()
                sections = parser.parse_pdf(pdf_path)

                chunk_idx = 0
                for section in sections:
                    text = section.get("content", "") if isinstance(section, dict) else str(section)
                    if not text or len(text.strip()) < 20:
                        continue

                    # 分割长文本
                    sub_chunks = self._split_text(text, self.config.chunk_size, self.config.chunk_overlap)
                    for sub_text in sub_chunks:
                        chunks.append(VectorChunk(
                            id=str(uuid.uuid4()),
                            text=sub_text,
                            source=pdf_file,
                            chunk_index=chunk_idx,
                        ))
                        chunk_idx += 1

            except ImportError:
                # 降级：简单文本提取
                chunks.extend(self._simple_pdf_extract(pdf_path))
            except Exception as e:
                logger.warning(f"解析 PDF {pdf_file} 失败: {e}")

        logger.info(f"从 {len(pdf_files)} 个 PDF 加载了 {len(chunks)} 个 chunks")
        return chunks

    def _simple_pdf_extract(self, pdf_path: str) -> list[VectorChunk]:
        """简单 PDF 文本提取（降级方案）"""
        chunks = []
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            doc.close()

            sub_chunks = self._split_text(full_text, self.config.chunk_size, self.config.chunk_overlap)
            for i, text in enumerate(sub_chunks):
                chunks.append(VectorChunk(
                    id=str(uuid.uuid4()),
                    text=text,
                    source=os.path.basename(pdf_path),
                    chunk_index=i,
                ))
        except ImportError:
            logger.warning("PyMuPDF 未安装，无法提取 PDF")
        except Exception as e:
            logger.warning(f"PDF 提取失败: {e}")

        return chunks

    def _migrate_from_chromadb(self) -> list[VectorChunk]:
        """从现有 ChromaDB 迁移数据到 Neo4j 向量索引"""
        chunks = []

        try:
            import chromadb
            client = chromadb.HttpClient(host="localhost", port=8000)
            collection = client.get_collection("hardware_knowledge")

            results = collection.get(include=["documents", "metadatas"])

            for i, (doc, meta) in enumerate(zip(results["documents"], results["metadatas"])):
                chunks.append(VectorChunk(
                    id=str(uuid.uuid4()),
                    text=doc,
                    source=meta.get("source", "") if meta else "",
                    chunk_index=i,
                    metadata=meta or {},
                ))

            logger.info(f"从 ChromaDB 迁移了 {len(chunks)} 个 chunks")
        except Exception as e:
            logger.warning(f"ChromaDB 迁移失败: {e}")

        return chunks

    @staticmethod
    def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        """文本分割"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # 在句号/换行处断开
            if end < len(text):
                for sep in ["。", ".", "\n\n", "\n"]:
                    pos = text.rfind(sep, start + chunk_size // 2, end)
                    if pos > 0:
                        end = pos + 1
                        break

            chunks.append(text[start:end].strip())
            start = end - overlap

        return [c for c in chunks if c]
