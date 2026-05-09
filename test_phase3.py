# -*- coding: utf-8 -*-
"""
Phase 3 测试脚本

验证内容:
1. Neo4jKnowledgeStore - 规则/知识切片存储
2. StorageDispatcher - 文档分发存储
3. Neo4j Schema 约束
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "hardware_ai_expert"))

from agent_system.parsers.checklist_parser import ChecklistRule, Severity
from agent_system.parsers.design_guide_parser import DesignGuideChunk
from agent_system.parsers.document_processor import ProcessingResult
from agent_system.storage_dispatcher import (
    Neo4jKnowledgeStore, StorageDispatcher, store_document
)


def test_neo4j_connection():
    """测试 Neo4j 连接"""
    print("=" * 60)
    print("[Test 1] Neo4j Connection")
    print("=" * 60)
    
    store = Neo4jKnowledgeStore()
    stats = store.get_stats()
    print(f"  当前规则数: {stats['rules']['total']}")
    print(f"  当前知识切片: {stats['knowledge_chunks']['total']}")
    print("✅ Neo4j 连接正常\n")
    store.close()


def test_store_rules():
    """测试规则存储"""
    print("=" * 60)
    print("[Test 2] Store Rules")
    print("=" * 60)
    
    store = Neo4jKnowledgeStore()
    
    # 先清理测试数据
    with store.driver.session() as session:
        session.run("MATCH (r:ReviewRule) WHERE r.RuleId STARTS WITH 'TEST_' DELETE r")
    
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
    
    count = store.store_rules(rules)
    print(f"  存储规则数: {count}")
    assert count == 2, "应存储 2 条规则"
    
    # 验证查询
    i2c_rules = store.get_rules_by_category("i2c")
    print(f"  i2c 规则: {len(i2c_rules)}")
    assert len(i2c_rules) >= 1, "应有 i2c 规则"
    
    all_rules = store.get_all_rules()
    print(f"  总规则: {len(all_rules)}")
    
    store.close()
    print("✅ 规则存储测试通过\n")


def test_store_knowledge_chunks():
    """测试知识切片存储"""
    print("=" * 60)
    print("[Test 3] Store Knowledge Chunks")
    print("=" * 60)
    
    store = Neo4jKnowledgeStore()
    
    # 先清理测试数据
    with store.driver.session() as session:
        session.run("MATCH (k:KnowledgeChunk) WHERE k.SourceId = 'test_guide' DELETE k")
    
    chunks = [
        DesignGuideChunk(
            content="USB3.0差分对应控制阻抗90Ω±10%",
            title="USB3差分对",
            category="signal_integrity",
        ),
        DesignGuideChunk(
            content="I2C上拉电阻推荐4.7KΩ",
            title="I2C上拉",
            category="i2c",
        ),
    ]
    
    count = store.store_knowledge_chunks("test_guide", chunks)
    print(f"  存储切片数: {count}")
    assert count == 2, "应存储 2 个切片"
    
    # 验证统计
    stats = store.get_stats()
    print(f"  知识切片总数: {stats['knowledge_chunks']['total']}")
    
    store.close()
    print("✅ 知识切片存储测试通过\n")


def test_storage_dispatcher():
    """测试存储分发器"""
    print("=" * 60)
    print("[Test 4] StorageDispatcher")
    print("=" * 60)
    
    dispatcher = StorageDispatcher()
    
    # 1. 未审批不应存储
    result = ProcessingResult(
        doc_type="checklist",
        source_file="test.csv",
        rules=[],
    )
    storage = dispatcher.store(result, approved=False)
    assert storage.status == "pending_approval", "未审批应返回 pending"
    print("  ✅ 未审批状态正确")
    
    # 2. Checklist 存储
    result = ProcessingResult(
        doc_type="checklist",
        source_file="test.csv",
        metadata={"source_id": "test"},
        rules=[
            ChecklistRule(
                rule_id="TEST_DISPATCH_001",
                name="测试规则",
                category="power",
                check_item="测试检查项",
                severity=Severity.INFO,
                source_checklist="test",
            ),
        ],
    )
    storage = dispatcher.store(result, approved=True)
    print(f"  Checklist 存储: {'✅' if storage.is_success() else '❌'}")
    print(f"    Neo4j: {storage.neo4j_count}")
    
    # 3. Design Guide 存储
    result = ProcessingResult(
        doc_type="design_guide",
        source_file="test.md",
        metadata={"source_id": "test_design_guide", "category": "i2c"},
        chunks=[
            DesignGuideChunk(content="I2C test content", title="Test", category="i2c"),
        ],
    )
    storage = dispatcher.store(result, approved=True)
    print(f"  DesignGuide 存储: {'✅' if storage.is_success() else '❌'}")
    print(f"    ChromaDB: {storage.chroma_count}")
    print(f"    Neo4j: {storage.neo4j_count}")
    
    # 4. 全局统计
    stats = dispatcher.get_stats()
    print(f"\n  全局统计:")
    print(f"    Neo4j Rules: {stats['neo4j']['rules']}")
    print(f"    ChromaDB Chunks: {stats['chroma']['tier1_chunks']}")
    
    print("✅ StorageDispatcher 测试通过\n")


def test_schema_constraints():
    """测试 Schema 约束"""
    print("=" * 60)
    print("[Test 5] Schema Constraints")
    print("=" * 60)
    
    store = Neo4jKnowledgeStore()
    
    with store.driver.session() as session:
        # 检查 ReviewRule 约束
        result = session.run("""
            SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties
            WHERE 'ReviewRule' IN labelsOrTypes
            RETURN name, properties
        """)
        constraints = list(result)
        print(f"  ReviewRule 约束: {len(constraints)}")
        for c in constraints:
            print(f"    - {c['name']}: {c['properties']}")
        
        # 检查 KnowledgeChunk 约束
        result = session.run("""
            SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties
            WHERE 'KnowledgeChunk' IN labelsOrTypes
            RETURN name, properties
        """)
        constraints = list(result)
        print(f"  KnowledgeChunk 约束: {len(constraints)}")
        
        # 检查索引
        result = session.run("""
            SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties
            WHERE labelsOrTypes IN [['ReviewRule'], ['KnowledgeChunk']]
            RETURN name, labelsOrTypes, properties
        """)
        indexes = list(result)
        print(f"  相关索引: {len(indexes)}")
        for idx in indexes:
            print(f"    - {idx['name']}: {idx['labelsOrTypes']} {idx['properties']}")
    
    store.close()
    print("✅ Schema 约束测试通过\n")


def cleanup_test_data():
    """清理测试数据"""
    print("=" * 60)
    print("Cleanup Test Data")
    print("=" * 60)
    
    store = Neo4jKnowledgeStore()
    
    with store.driver.session() as session:
        # 删除测试规则
        result = session.run("""
            MATCH (r:ReviewRule) WHERE r.RuleId STARTS WITH 'TEST_' OR r.RuleId STARTS WITH 'TEST_DISPATCH_'
            DELETE r
            RETURN count(r) as deleted
        """)
        deleted = result.single()["deleted"]
        print(f"  删除测试规则: {deleted}")
        
        # 删除测试知识切片
        result = session.run("""
            MATCH (k:KnowledgeChunk) WHERE k.SourceId STARTS WITH 'test'
            DELETE k
            RETURN count(k) as deleted
        """)
        deleted = result.single()["deleted"]
        print(f"  删除测试知识切片: {deleted}")
    
    store.close()
    print("✅ 清理完成\n")


def main():
    print("\n" + "=" * 60)
    print("Phase 3 测试开始")
    print("=" * 60 + "\n")
    
    try:
        test_neo4j_connection()
        test_store_rules()
        test_store_knowledge_chunks()
        test_storage_dispatcher()
        test_schema_constraints()
        cleanup_test_data()
        
        print("=" * 60)
        print("🎉 所有 Phase 3 测试通过！")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
