# -*- coding: utf-8 -*-
"""
存储分发器

根据文档类型和审批状态，将处理结果分发到正确的存储目标：
- ChromaDB: 向量存储（Design Guide / Expert Note / Datasheet）
- Neo4j: 图谱存储（ReviewRule / KnowledgeChunk）
- YAML: AMR 数据源（Datasheet 参数）

对应技术方案 Phase 3
"""

from __future__ import annotations

import os
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from neo4j import GraphDatabase

from .parsers.document_processor import ProcessingResult
from .parsers.checklist_parser import ChecklistRule
from .parsers.design_guide_parser import DesignGuideChunk
from .knowledge_router import KnowledgeRouter
from .schemas.graph import ReviewRuleNode, KnowledgeChunkNode

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

@dataclass
class StorageResult:
    """存储结果"""
    status: str = "pending"  # pending/stored/rejected/error
    chroma_count: int = 0
    neo4j_count: int = 0
    yaml_count: int = 0
    error: Optional[str] = None
    
    def is_success(self) -> bool:
        return self.status == "stored"
    
    def get_summary(self) -> str:
        if self.error:
            return f"❌ 存储失败: {self.error}"
        parts = [f"✅ 存储完成 ({self.status})"]
        if self.chroma_count:
            parts.append(f"  ChromaDB: {self.chroma_count} 条")
        if self.neo4j_count:
            parts.append(f"  Neo4j: {self.neo4j_count} 条")
        if self.yaml_count:
            parts.append(f"  YAML: {self.yaml_count} 条")
        return "\n".join(parts)


# ============================================================
# Neo4j 存储器
# ============================================================

class Neo4jKnowledgeStore:
    """
    Neo4j 知识存储器
    
    存储 ReviewRule 和 KnowledgeChunk 节点
    """
    
    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.environ.get("NEO4J_USER", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "SecretPassword123")
        self._driver = None
    
    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver
    
    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def store_rules(self, rules: List[ChecklistRule]) -> int:
        """
        存储审查规则到 Neo4j
        
        Args:
            rules: ChecklistRule 列表
        
        Returns:
            成功存储的规则数
        """
        stored = 0
        with self.driver.session() as session:
            for rule in rules:
                try:
                    node = ReviewRuleNode(
                        rule_id=rule.rule_id,
                        name=rule.name,
                        category=rule.category,
                        target=rule.target,
                        check_item=rule.check_item,
                        pass_condition=rule.pass_condition,
                        severity=rule.severity.value,
                        source_checklist=rule.source_checklist,
                        reference=rule.reference,
                        enabled=rule.enabled,
                        created_at=datetime.now().isoformat(),
                    )
                    
                    cypher = """
                    MERGE (r:ReviewRule {RuleId: $RuleId})
                    SET r += $props
                    RETURN r.RuleId as id
                    """
                    
                    result = session.run(cypher, {
                        "RuleId": node.rule_id,
                        "props": node.to_cypher_properties()
                    })
                    if result.single():
                        stored += 1
                        
                except Exception as e:
                    logger.error(f"Failed to store rule {rule.rule_id}: {e}")
        
        logger.info(f"Stored {stored}/{len(rules)} rules to Neo4j")
        return stored
    
    def store_knowledge_chunks(self, source_id: str, chunks: List[DesignGuideChunk]) -> int:
        """
        存储知识切片到 Neo4j
        
        Args:
            source_id: 来源文档标识
            chunks: DesignGuideChunk 列表
        
        Returns:
            成功存储的切片数
        """
        stored = 0
        with self.driver.session() as session:
            for i, chunk in enumerate(chunks):
                try:
                    chunk_id = f"{source_id}_chunk_{i:03d}"
                    node = KnowledgeChunkNode(
                        chunk_id=chunk_id,
                        source_id=source_id,
                        title=chunk.title,
                        category=chunk.category,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        char_count=chunk.char_count,
                        indexed_at=datetime.now().isoformat(),
                    )
                    
                    cypher = """
                    MERGE (k:KnowledgeChunk {ChunkId: $ChunkId})
                    SET k += $props
                    RETURN k.ChunkId as id
                    """
                    
                    result = session.run(cypher, {
                        "ChunkId": node.chunk_id,
                        "props": node.to_cypher_properties()
                    })
                    if result.single():
                        stored += 1
                        
                except Exception as e:
                    logger.error(f"Failed to store chunk {i}: {e}")
        
        logger.info(f"Stored {stored}/{len(chunks)} knowledge chunks to Neo4j")
        return stored
    
    def get_rules_by_category(self, category: str) -> List[dict]:
        """按分类查询规则"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (r:ReviewRule {Category: $category, Enabled: true})
                RETURN r {
                    .RuleId, .Name, .Category, .Target, 
                    .CheckItem, .PassCondition, .Severity
                } as rule
                ORDER BY r.Severity DESC
            """, {"category": category})
            return [record["rule"] for record in result]
    
    def get_all_rules(self) -> List[dict]:
        """查询所有规则"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (r:ReviewRule)
                RETURN r {
                    .RuleId, .Name, .Category, .Target,
                    .CheckItem, .PassCondition, .Severity, .Enabled
                } as rule
                ORDER BY r.Category, r.RuleId
            """)
            return [record["rule"] for record in result]
    
    def get_stats(self) -> dict:
        """获取知识库统计"""
        with self.driver.session() as session:
            # 规则统计
            result = session.run("""
                MATCH (r:ReviewRule)
                RETURN count(r) as total,
                       count(CASE WHEN r.Enabled = true THEN 1 END) as enabled,
                       count(CASE WHEN r.Severity = 'ERROR' THEN 1 END) as errors,
                       count(CASE WHEN r.Severity = 'WARNING' THEN 1 END) as warnings
            """)
            rule_stats = result.single()
            
            # 知识切片统计
            result = session.run("""
                MATCH (k:KnowledgeChunk)
                RETURN count(k) as total,
                       count(DISTINCT k.SourceId) as sources
            """)
            chunk_stats = result.single()
            
            return {
                "rules": {
                    "total": rule_stats["total"],
                    "enabled": rule_stats["enabled"],
                    "errors": rule_stats["errors"],
                    "warnings": rule_stats["warnings"],
                },
                "knowledge_chunks": {
                    "total": chunk_stats["total"],
                    "sources": chunk_stats["sources"],
                }
            }


# ============================================================
# 存储分发器
# ============================================================

class StorageDispatcher:
    """
    存储分发器
    
    根据文档类型和审批结果，分发存储到不同目标
    """
    
    def __init__(self):
        self.router = KnowledgeRouter()
        self.neo4j = Neo4jKnowledgeStore()
    
    def store(self, result: ProcessingResult, approved: bool = False) -> StorageResult:
        """
        存储处理结果
        
        Args:
            result: ProcessingResult
            approved: 是否已通过人工审批
        
        Returns:
            StorageResult
        """
        if not approved:
            logger.info(f"Document '{result.source_file}' pending approval")
            return StorageResult(status="pending_approval")
        
        storage_result = StorageResult(status="stored")
        
        try:
            if result.doc_type == "datasheet":
                storage_result = self._store_datasheet(result)
            elif result.doc_type == "design_guide":
                storage_result = self._store_design_guide(result)
            elif result.doc_type == "checklist":
                storage_result = self._store_checklist(result)
            elif result.doc_type == "expert_note":
                storage_result = self._store_expert_note(result)
            else:
                return StorageResult(status="error", error=f"Unknown doc_type: {result.doc_type}")
                
        except Exception as e:
            logger.error(f"Storage failed: {e}", exc_info=True)
            return StorageResult(status="error", error=str(e))
        
        return storage_result
    
    def _store_datasheet(self, result: ProcessingResult) -> StorageResult:
        """存储 Datasheet: ChromaDB + YAML"""
        res = StorageResult(status="stored")
        
        # TODO: 参数存入 amr_data.yaml
        # res.yaml_count = self._store_to_yaml(result.parameters)
        
        return res
    
    def _store_design_guide(self, result: ProcessingResult) -> StorageResult:
        """存储 Design Guide: ChromaDB + Neo4j"""
        res = StorageResult(status="stored")
        
        source_id = result.metadata.get("source_id", "unknown")
        
        # 1. 存入 ChromaDB
        if result.chunks:
            res.chroma_count = self.router.import_design_guide(
                source_id, result.chunks, result.metadata.get("category", "general")
            )
        
        # 2. 存入 Neo4j
        if result.chunks:
            res.neo4j_count = self.neo4j.store_knowledge_chunks(source_id, result.chunks)
        
        return res
    
    def _store_checklist(self, result: ProcessingResult) -> StorageResult:
        """存储 Checklist: Neo4j (规则节点)"""
        res = StorageResult(status="stored")
        
        if result.rules:
            res.neo4j_count = self.neo4j.store_rules(result.rules)
        
        return res
    
    def _store_expert_note(self, result: ProcessingResult) -> StorageResult:
        """存储经验文档: ChromaDB"""
        res = StorageResult(status="stored")
        
        source_id = result.metadata.get("source_id", "unknown")
        
        if result.chunks:
            res.chroma_count = self.router.import_design_guide(
                source_id, result.chunks, result.metadata.get("category", "general")
            )
        
        return res
    
    def get_stats(self) -> dict:
        """获取所有存储统计"""
        neo4j_stats = self.neo4j.get_stats()
        chroma_stats = self.router.get_stats()
        
        return {
            "neo4j": neo4j_stats,
            "chroma": chroma_stats,
        }


# ============================================================
# 便捷函数
# ============================================================

def store_document(result: ProcessingResult, approved: bool = False) -> StorageResult:
    """便捷函数：存储文档处理结果"""
    dispatcher = StorageDispatcher()
    return dispatcher.store(result, approved)


# ============================================================
# 测试
# ============================================================

def _test_storage():
    """测试存储分发器"""
    print("=" * 60)
    print("StorageDispatcher 测试")
    print("=" * 60)
    
    dispatcher = StorageDispatcher()
    
    # 1. 测试 Checklist 存储
    print("\n[1/3] Checklist 存储测试")
    from .parsers.checklist_parser import ChecklistRule, Severity
    
    rules = [
        ChecklistRule(
            rule_id="TEST_RULE_001",
            name="I2C上拉测试",
            category="i2c",
            target="所有I2C器件",
            check_item="上拉电阻应在1K~10K",
            pass_condition="1K <= R <= 10K",
            severity=Severity.WARNING,
            source_checklist="test_checklist",
        ),
        ChecklistRule(
            rule_id="TEST_RULE_002",
            name="USB阻抗测试",
            category="usb",
            target="USB3.0接口",
            check_item="差分对阻抗90Ω±10%",
            pass_condition="85 <= Z <= 95",
            severity=Severity.ERROR,
            source_checklist="test_checklist",
        ),
    ]
    
    from .parsers.document_processor import ProcessingResult
    result = ProcessingResult(
        doc_type="checklist",
        source_file="test.csv",
        rules=rules,
    )
    
    storage = dispatcher.store(result, approved=True)
    print(f"  状态: {'✅ 成功' if storage.is_success() else '❌ 失败'}")
    print(f"  Neo4j: {storage.neo4j_count} 条")
    assert storage.neo4j_count == 2, "应存储 2 条规则"
    
    # 2. 验证查询
    print("\n[2/3] 规则查询测试")
    rules_i2c = dispatcher.neo4j.get_rules_by_category("i2c")
    print(f"  i2c 规则数: {len(rules_i2c)}")
    assert len(rules_i2c) >= 1, "应有 i2c 规则"
    
    all_rules = dispatcher.neo4j.get_all_rules()
    print(f"  总规则数: {len(all_rules)}")
    
    # 3. 统计测试
    print("\n[3/3] 统计测试")
    stats = dispatcher.neo4j.get_stats()
    print(f"  Rules: {stats['rules']}")
    print(f"  Knowledge Chunks: {stats['knowledge_chunks']}")
    
    print("\n✅ StorageDispatcher 测试完成")


if __name__ == "__main__":
    _test_storage()
