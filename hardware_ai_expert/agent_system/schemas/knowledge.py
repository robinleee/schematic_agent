"""
知识库数据模型

定义知识提取和向量存储相关的数据模型。
对应 Schemas_Design.md Section 6
"""

from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================
# 知识提取模型
# ============================================

class ExtractedKnowledge(BaseModel):
    """从 Design Guide / Datasheet 提取的知识条目"""
    id: str = Field(description="知识条目唯一标识")
    source_type: Literal["design_guide", "datasheet", "expert_note"] = Field(
        default="design_guide",
        description="知识来源类型"
    )
    source_id: str = Field(description="来源文档 ID")
    source_page: Optional[int] = Field(None, description="来源页码")
    title: str = Field(description="知识标题")
    content: str = Field(description="知识内容文本")
    category: Literal["i2c", "power", "pcie", "spi", "gpio", "thermal", "signal_integrity", "general"] = Field(
        default="general",
        description="知识分类"
    )
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    confidence: float = Field(ge=0.0, le=1.0, default=0.8, description="提取置信度")
    verified: bool = Field(default=False, description="是否已人工验证")


class KnowledgeChunk(BaseModel):
    """向量库中的知识切片"""
    chunk_id: str = Field(description="切片唯一标识")
    mpn: str = Field(description="关联的器件型号")
    source_id: str = Field(description="来源文档 ID")
    page: int = Field(default=0, description="来源页码")
    content: str = Field(description="切片内容")
    chunk_type: Literal["specification", "pinout", "application_note", "general"] = Field(
        default="general",
        description="切片类型"
    )
    content_hash: str = Field(default="", description="内容哈希")
    indexed_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_cypher_properties(self) -> dict:
        """转换为 Cypher 属性字典"""
        return {
            "ChunkId": self.chunk_id,
            "MPN": self.mpn,
            "SourceId": self.source_id,
            "Page": self.page,
            "Content": self.content[:2000],  # 截断避免超长
            "ChunkType": self.chunk_type,
            "ContentHash": self.content_hash,
            "IndexedAt": self.indexed_at,
        }


# ============================================
# Design Guide 模型
# ============================================

class DesignGuide(BaseModel):
    """设计指南模型

    对应 Neo4j: (:DesignGuide)
    """
    guide_id: str = Field(description="指南 ID")
    title: str = Field(description="指南标题")
    version: str = Field(default="1.0.0")
    category: Literal["i2c", "power", "pcie", "spi", "gpio", "thermal", "signal_integrity", "general"] = Field(
        default="general",
        description="指南分类"
    )
    summary: Optional[str] = Field(None, description="摘要")
    rule_count: int = Field(default=0, description="包含规则数量")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_cypher_properties(self) -> dict:
        """转换为 Cypher 属性字典"""
        return {
            "GuideId": self.guide_id,
            "Title": self.title,
            "Version": self.version,
            "Category": self.category,
            "Summary": self.summary,
            "RuleCount": self.rule_count,
            "CreatedAt": self.created_at,
        }


class DatasheetConfig(BaseModel):
    """Datasheet 配置"""
    mpn: str = Field(description="器件型号")
    title: Optional[str] = Field(None, description="文档标题")
    manufacturer: Optional[str] = Field(None, description="制造商")
    revision: Optional[str] = Field(None, description="文档版本")
    total_pages: int = Field(default=0, description="总页数")
    indexed_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    indexed_by: str = Field(default="system", description="入库人")


# ============================================
# 知识库相关 Neo4j 约束
# ============================================

KNOWLEDGE_CONSTRAINTS = [
    "CREATE CONSTRAINT knowledge_chunk_id IF NOT EXISTS FOR (k:KnowledgeChunk) REQUIRE k.ChunkId IS UNIQUE",
    "CREATE CONSTRAINT design_guide_id IF NOT EXISTS FOR (d:DesignGuide) REQUIRE d.GuideId IS UNIQUE",
]

KNOWLEDGE_INDEXES = [
    "CREATE INDEX knowledge_mpn IF NOT EXISTS FOR (k:KnowledgeChunk) ON (k.MPN)",
    "CREATE INDEX knowledge_type IF NOT EXISTS FOR (k:KnowledgeChunk) ON (k.ChunkType)",
    "CREATE INDEX design_guide_category IF NOT EXISTS FOR (d:DesignGuide) ON (d.Category)",
]


__all__ = [
    "ExtractedKnowledge",
    "KnowledgeChunk",
    "DesignGuide",
    "DatasheetConfig",
    "KNOWLEDGE_CONSTRAINTS",
    "KNOWLEDGE_INDEXES",
]
