"""GraphRAG 数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class VectorChunk:
    """向量块 — 对应 Neo4j VectorChunk 节点"""
    id: str
    text: str
    embedding: list[float] = field(default_factory=list)
    source: str = ""  # PDF filename or MPN
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractedEntity:
    """抽取的实体"""
    entity_type: str  # Component / Spec / Pin / Application
    name: str
    properties: dict = field(default_factory=dict)


@dataclass
class ExtractedRelation:
    """抽取的关系"""
    source: str
    source_type: str
    target: str
    target_type: str
    relation_type: str  # HAS_SPEC / HAS_PIN / RECOMMENDS


@dataclass
class Community:
    """社区"""
    id: int
    member_ids: list[str] = field(default_factory=list)
    summary: str = ""
    member_count: int = 0


@dataclass
class RetrievalResult:
    """检索结果"""
    text: str
    score: float
    source: str = ""  # chunk_id / community_id / node_id
    retrieval_type: str = "local"  # local / global / graph
    metadata: dict = field(default_factory=dict)


@dataclass
class GraphRAGConfig:
    """GraphRAG 配置"""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "SecretPassword123"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:26b"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
