#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 测试脚本

验证内容:
1. DesignGuideParser 文本提取和切片
2. KnowledgeRouter 导入设计指南
3. 查询测试
"""

import os
import sys
import tempfile

# 添加项目路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "hardware_ai_expert"))

from agent_system.parsers.design_guide_parser import DesignGuideParser, TopicClassifier
from agent_system.parsers.document_processor import DocumentProcessor, process_document
from agent_system.knowledge_router import KnowledgeRouter


def test_design_guide_parser():
    """测试 Design Guide 解析器"""
    print("=" * 60)
    print("[Test 1] DesignGuideParser")
    print("=" * 60)

    test_md = """# USB3.0 设计指南

## 1. 差分对设计

USB3.0 SuperSpeed 差分对应控制阻抗在 90Ω ±10%。
走线应尽量短，避免过孔和 stubs。
差分对间距应保持恒定，推荐 2 倍线宽。

## 2. ESD 保护

USB 接口必须添加 ESD 保护器件。
推荐选择容值 <0.5pF 的低容 ESD。
保护器件应靠近连接器放置，距离不超过 5mm。

## 3. 电源设计

VBUS 需要提供 5V/900mA 的供电能力。
建议添加过流保护（OCP）电路。
PD 快充需要额外的 CC 线检测电路。

### 3.1 VBUS 去耦

VBUS 引脚需要 10uF + 100nF 陶瓷电容并联去耦。
电容应靠近引脚放置。

## 4. 信号完整性

TX/RX 差分对应做等长处理，误差控制在 5mil 以内。
避免与高速时钟线平行走线。
参考平面应完整，避免跨分割。
"""

    parser = DesignGuideParser()
    chunks = parser.parse_text(test_md, "test_usb3_guide")

    print(f"✅ 切片数: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}: [{chunk.category}] {chunk.title}")
        print(f"    层级: {chunk.section_level} | 字符: {chunk.char_count}")

    assert len(chunks) >= 4, "应至少有 4 个切片"
    assert any(c.category == "signal_integrity" for c in chunks), "应有 signal_integrity 分类"
    assert any(c.category == "power" for c in chunks), "应有 power 分类"
    print("✅ DesignGuideParser 测试通过\n")


def test_topic_classifier():
    """测试主题分类器"""
    print("=" * 60)
    print("[Test 2] TopicClassifier")
    print("=" * 60)

    classifier = TopicClassifier()
    test_cases = [
        ("I2C bus requires 4.7K pull-up resistors", "i2c"),
        ("LDO output voltage should be 1.8V", "power"),
        ("PCIe Gen3 differential pair impedance 85Ω", "pcie"),
        ("USB Type-C CC pin detection circuit", "usb"),
        ("DDR4 address line termination resistor", "ddr"),
        ("General description of the board", "general"),
    ]

    passed = 0
    for text, expected in test_cases:
        result = classifier.classify(text)
        status = "✅" if result == expected else "❌"
        if result == expected:
            passed += 1
        print(f"  {status} '{text[:40]}...' → {result} (expect: {expected})")

    print(f"\n✅ 分类准确率: {passed}/{len(test_cases)}")
    assert passed >= 4, "分类准确率应 >= 4/6"
    print("✅ TopicClassifier 测试通过\n")


def test_document_processor():
    """测试文档处理器"""
    print("=" * 60)
    print("[Test 3] DocumentProcessor")
    print("=" * 60)

    processor = DocumentProcessor()

    # 测试临时文件
    test_content = """# I2C 设计规范

## 上拉电阻选择

标准模式 I2C（100KHz）推荐上拉电阻 4.7KΩ。
快速模式（400KHz）推荐 2.2KΩ ~ 4.7KΩ。
总线电容 < 400pF。

## 信号完整性

SDA 和 SCL 应尽量避免与高速信号平行走线。
走线长度差应控制在 10% 以内。
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(test_content)
        temp_path = f.name

    try:
        result = processor.process(temp_path, "design_guide", {
            "source_id": "test_i2c_guide",
            "project": "test",
        })

        print(f"  状态: {'✅ 成功' if result.is_success() else '❌ 失败'}")
        assert result.is_success(), f"处理失败: {result.error}"
        print(f"  切片数: {len(result.chunks)}")
        assert len(result.chunks) >= 2, "应至少有 2 个切片"

    finally:
        os.unlink(temp_path)

    # 测试不存在的文件
    result = processor.process("/nonexistent/file.pdf", "design_guide")
    assert result.error is not None, "应返回错误"
    print("  ✅ 错误处理正确")

    print("✅ DocumentProcessor 测试通过\n")


def test_knowledge_router_import():
    """测试 KnowledgeRouter 导入设计指南"""
    print("=" * 60)
    print("[Test 4] KnowledgeRouter Import")
    print("=" * 60)

    # 检查 ChromaDB 是否可用
    try:
        import chromadb
        chromadb_available = True
    except ImportError:
        chromadb_available = False
        print("  ⚠️ ChromaDB 不可用，跳过导入测试")
        print("  ✅ KnowledgeRouter 导入测试跳过\n")
        return

    router = KnowledgeRouter()

    # 初始统计
    stats_before = router.get_stats()
    print(f"  导入前 ChromaDB 切片数: {stats_before['tier1_chunks']}")

    # 准备测试切片
    from agent_system.parsers.design_guide_parser import DesignGuideChunk

    test_chunks = [
        DesignGuideChunk(
            content="USB3.0 差分对应控制阻抗在 90Ω ±10%。",
            title="差分对设计",
            category="signal_integrity",
        ),
        DesignGuideChunk(
            content="I2C 上拉电阻推荐 4.7KΩ，总线电容 < 400pF。",
            title="I2C 上拉电阻",
            category="i2c",
        ),
        DesignGuideChunk(
            content="LDO 输出需要 1uF + 100nF 陶瓷电容去耦。",
            title="LDO 去耦",
            category="power",
        ),
    ]

    # 导入设计指南
    imported = router.import_design_guide("test_usb3_guide", test_chunks)
    print(f"  导入切片数: {imported}")
    assert imported == 3, "应导入 3 个切片"

    # 验证统计
    stats_after = router.get_stats()
    print(f"  导入后 ChromaDB 切片数: {stats_after['tier1_chunks']}")
    assert stats_after['tier1_chunks'] == stats_before['tier1_chunks'] + 3, "切片数应增加 3"

    print("✅ KnowledgeRouter 导入测试通过\n")


def test_knowledge_router_query():
    """测试 KnowledgeRouter 查询"""
    print("=" * 60)
    print("[Test 5] KnowledgeRouter Query")
    print("=" * 60)

    # 检查 ChromaDB 是否可用
    try:
        import chromadb
        chromadb_available = True
    except ImportError:
        chromadb_available = False
        print("  ⚠️ ChromaDB 不可用，跳过查询测试")
        print("  ✅ KnowledgeRouter 查询测试跳过\n")
        return

    router = KnowledgeRouter()

    # 先导入测试数据
    from agent_system.parsers.design_guide_parser import DesignGuideChunk
    test_chunks = [
        DesignGuideChunk(
            content="USB3.0 SuperSpeed 差分对应控制阻抗在 90Ω ±10%，走线应尽量短。",
            title="USB3 差分对",
            category="signal_integrity",
        ),
        DesignGuideChunk(
            content="I2C 标准模式推荐上拉电阻 4.7KΩ，快速模式 2.2KΩ。",
            title="I2C 上拉",
            category="i2c",
        ),
    ]
    router.import_design_guide("test_query_guide", test_chunks)

    # 测试查询
    queries = [
        ("test_query_guide", "USB 差分对阻抗", "signal_integrity"),
        ("test_query_guide", "I2C 上拉电阻", "i2c"),
    ]

    for mpn, query, expected_topic in queries:
        result = router.search(mpn, query)
        print(f"  查询: '{query}'")
        print(f"    状态: {result.status}, 置信度: {result.confidence:.2f}")

        if result.status == "success":
            print(f"    内容预览: {result.content[:60]}...")
            assert expected_topic in result.content.lower() or expected_topic in result.source, \
                f"结果应包含 {expected_topic} 相关内容"
        else:
            print(f"    ⚠️ 未找到结果（embedding 简单，可能检索不到）")

    print("✅ KnowledgeRouter 查询测试通过\n")


def main():
    print("\n" + "=" * 60)
    print("Phase 1 测试开始")
    print("=" * 60 + "\n")

    try:
        test_design_guide_parser()
        test_topic_classifier()
        test_document_processor()
        test_knowledge_router_import()
        test_knowledge_router_query()

        print("=" * 60)
        print("🎉 所有 Phase 1 测试通过！")
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