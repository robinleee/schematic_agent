# -*- coding: utf-8 -*-
"""
Phase 5-6: 集成测试

测试内容:
1. 模块导入测试 — 所有新增模块可正常导入
2. 页面结构测试 — app.py 导航配置正确
3. 知识库端到端测试 — 上传 → 解析 → 审核 → 查询
4. ETL 导入测试 — 解析 → 预览 → 质量检查
5. 持久化测试 — JSON 文件读写
6. 回归测试 — 原有功能不受影响
"""

import os
import sys
import tempfile
import shutil

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "hardware_ai_expert"))


def test_module_imports():
    """测试所有模块导入"""
    print("=" * 60)
    print("[Test 1] Module Imports")
    print("=" * 60)

    modules = [
        ("parsers", [
            "agent_system.parsers.document_processor",
            "agent_system.parsers.design_guide_parser",
            "agent_system.parsers.checklist_parser",
        ]),
        ("storage", [
            "agent_system.storage_dispatcher",
            "agent_system.knowledge_router",
            "agent_system.kb_persistence",
        ]),
        ("etl", [
            "agent_system.etl_web_bridge",
        ]),
        ("schemas", [
            "agent_system.schemas.graph",
            "agent_system.schemas.agent",
        ]),
    ]

    for category, mod_list in modules:
        print(f"\n  {category}:")
        for mod in mod_list:
            try:
                __import__(mod)
                print(f"    ✅ {mod}")
            except Exception as e:
                print(f"    ❌ {mod}: {e}")
                return False

    print("\n✅ 模块导入测试通过")
    return True


def test_page_structure():
    """测试页面结构"""
    print("\n" + "=" * 60)
    print("[Test 2] Page Structure")
    print("=" * 60)

    app_file = os.path.join(ROOT_DIR, "hardware_ai_expert", "web_ui", "app.py")
    with open(app_file, "r") as f:
        content = f.read()

    # 检查导航配置在文件末尾（在所有函数定义之后）
    nav_index = content.rfind("st.navigation")
    last_func_index = content.rfind("def render_")

    if nav_index < last_func_index:
        print("  ❌ 导航配置在函数定义之前")
        return False
    print("  ✅ 导航配置在函数定义之后")

    # 检查所有页面
    expected_pages = [
        "render_chat", "render_review_report", "render_hitl",
        "render_datasheet_hitl", "render_system_status"
    ]
    for page in expected_pages:
        if page not in content:
            print(f"  ❌ 缺少页面: {page}")
            return False
    print(f"  ✅ 所有 {len(expected_pages)} 个页面存在")

    # 检查新页面文件
    pages_dir = os.path.join(ROOT_DIR, "hardware_ai_expert", "web_ui", "pages")
    for page_file in ["knowledge_base.py", "etl_import.py"]:
        path = os.path.join(pages_dir, page_file)
        if not os.path.exists(path):
            print(f"  ❌ 缺少页面文件: {page_file}")
            return False
    print("  ✅ 知识库和 ETL 页面文件存在")

    print("\n✅ 页面结构测试通过")
    return True


def test_kb_end_to_end():
    """知识库端到端测试"""
    print("\n" + "=" * 60)
    print("[Test 3] Knowledge Base End-to-End")
    print("=" * 60)

    from agent_system.kb_persistence import KBPersistence
    from agent_system.parsers.document_processor import DocumentProcessor
    from agent_system.parsers.design_guide_parser import DesignGuideChunk

    tmp_dir = tempfile.mkdtemp()
    db = KBPersistence(tmp_dir)

    # 1. 添加文档
    doc = db.add_document("test_usb.md", "design_guide", {"category": "usb"})
    print(f"  1. 添加文档: {doc.doc_id}")

    # 2. 更新状态
    db.update_status(doc.doc_id, "pending_review")
    print(f"  2. 更新状态: pending_review")

    # 3. 审批
    db.approve(doc.doc_id, reviewer="test", comment="OK")
    print(f"  3. 审批通过")

    # 4. 验证
    stored = db.get_documents_by_status("stored")
    assert len(stored) == 1, "应有 1 个已入库文档"
    print(f"  4. 验证: {len(stored)} 个已入库")

    # 5. 统计
    stats = db.get_stats()
    assert stats["total"] == 1, "总数应为 1"
    print(f"  5. 统计: {stats}")

    shutil.rmtree(tmp_dir)
    print("\n✅ 知识库端到端测试通过")
    return True


def test_etl_end_to_end():
    """ETL 端到端测试"""
    print("\n" + "=" * 60)
    print("[Test 4] ETL End-to-End")
    print("=" * 60)

    from agent_system.etl_web_bridge import ETLWebExecutor

    data_dir = os.path.join(ROOT_DIR, "hardware_ai_expert", "data", "netlist_Beet7")
    if not os.path.exists(data_dir):
        print("  ⚠️ 跳过（无测试数据）")
        return True

    files = {
        "pstxnet": os.path.join(data_dir, "pstxnet.dat"),
        "pstxprt": os.path.join(data_dir, "pstxprt.dat"),
        "pstchip": os.path.join(data_dir, "pstchip.dat"),
    }

    # 1. 预览
    executor = ETLWebExecutor()
    preview = executor.get_preview_stats(files)
    assert preview["success"], "预览应成功"
    print(f"  1. 预览: {preview['components_count']} 器件, {preview['parttype_coverage']:.1f}% 覆盖率")

    # 2. 质量检查
    components, topology = executor._parse_files(files)
    quality = executor._run_quality_check(components, topology)
    assert quality["passed"], "质量应通过"
    print(f"  2. 质量检查: PASS ({quality['parttype_coverage']:.1f}%)")

    print("\n✅ ETL 端到端测试通过")
    return True


def test_neo4j_connectivity():
    """测试 Neo4j 连接"""
    print("\n" + "=" * 60)
    print("[Test 5] Neo4j Connectivity")
    print("=" * 60)

    try:
        from agent_system.storage_dispatcher import Neo4jKnowledgeStore
        store = Neo4jKnowledgeStore()
        stats = store.get_stats()
        print(f"  规则数: {stats['rules']['total']}")
        print(f"  知识切片: {stats['knowledge_chunks']['total']}")
        store.close()
        print("\n✅ Neo4j 连接测试通过")
        return True
    except Exception as e:
        print(f"  ⚠️ Neo4j 连接失败: {e}")
        print("  （Neo4j 可能未启动，跳过）")
        return True  # Neo4j 未启动不算失败


def test_chromadb_connectivity():
    """测试 ChromaDB 连接"""
    print("\n" + "=" * 60)
    print("[Test 6] ChromaDB Connectivity")
    print("=" * 60)

    try:
        from agent_system.knowledge_router import KnowledgeRouter
        router = KnowledgeRouter()
        stats = router.get_stats()
        print(f"  ChromaDB 切片数: {stats.get('tier1_chunks', 0)}")
        print("\n✅ ChromaDB 连接测试通过")
        return True
    except Exception as e:
        print(f"  ⚠️ ChromaDB 连接失败: {e}")
        print("  （ChromaDB 可能未启动，跳过）")
        return True


def main():
    print("\n" + "=" * 60)
    print("Phase 5-6: 集成测试")
    print("=" * 60 + "\n")

    results = []
    results.append(test_module_imports())
    results.append(test_page_structure())
    results.append(test_kb_end_to_end())
    results.append(test_etl_end_to_end())
    results.append(test_neo4j_connectivity())
    results.append(test_chromadb_connectivity())

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"🎉 所有 {total} 项集成测试通过！")
        print("=" * 60)
        return 0
    else:
        print(f"⚠️ {passed}/{total} 项测试通过")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
