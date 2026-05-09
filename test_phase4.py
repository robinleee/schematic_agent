# -*- coding: utf-8 -*-
"""
Phase 4 测试脚本

验证内容:
1. KBPersistence - JSON 持久化
2. Streamlit 多页面结构
3. 知识库管理页面导入
"""

import os
import sys
import tempfile
import shutil

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "hardware_ai_expert"))


def test_persistence():
    """测试持久化模块"""
    print("=" * 60)
    print("[Test 1] KBPersistence")
    print("=" * 60)

    from agent_system.kb_persistence import KBPersistence

    tmp_dir = tempfile.mkdtemp()
    db = KBPersistence(tmp_dir)

    # 添加文档
    doc1 = db.add_document("test_guide.md", "design_guide", {"category": "usb"})
    doc2 = db.add_document("test_checklist.csv", "checklist", {"project": "board_a"})
    print(f"  添加 2 个文档: {doc1.doc_id}, {doc2.doc_id}")

    # 更新状态
    db.update_status(doc1.doc_id, "pending_review")
    print(f"  更新状态: {doc1.doc_id} → pending_review")

    # 查询
    assert len(db.get_all_documents()) == 2, "应有 2 个文档"
    assert len(db.get_pending_review()) == 1, "应有 1 个待审核"
    print(f"  查询验证通过")

    # 审批
    db.approve(doc1.doc_id, reviewer="test_user", comment="OK")
    approved = db.get_documents_by_status("stored")
    assert len(approved) == 1, "应有 1 个已入库"
    print(f"  审批验证通过")

    # 统计
    stats = db.get_stats()
    assert stats["total"] == 2, "总数应为 2"
    print(f"  统计: {stats}")

    # 持久化验证
    db2 = KBPersistence(tmp_dir)
    assert len(db2.get_all_documents()) == 2, "持久化后应仍有 2 个文档"
    print(f"  持久化验证通过")

    shutil.rmtree(tmp_dir)
    print("✅ 持久化测试通过\n")


def test_multipage_structure():
    """测试多页面结构"""
    print("=" * 60)
    print("[Test 2] Multi-page Structure")
    print("=" * 60)

    # 检查页面文件是否存在
    kb_page = os.path.join(ROOT_DIR, "hardware_ai_expert", "web_ui", "pages", "knowledge_base.py")
    assert os.path.exists(kb_page), f"知识库页面不存在: {kb_page}"
    print(f"  ✅ 知识库页面存在")

    # 检查 app.py 是否使用 st.navigation
    app_file = os.path.join(ROOT_DIR, "hardware_ai_expert", "web_ui", "app.py")
    with open(app_file, "r") as f:
        content = f.read()

    assert "st.navigation" in content, "app.py 应使用 st.navigation"
    print(f"  ✅ app.py 使用 st.navigation")

    assert "knowledge_base" in content, "app.py 应包含 knowledge_base 页面"
    print(f"  ✅ app.py 包含知识库页面")

    # 检查旧的路由代码是否已移除
    assert 'if page == "💬 智能对话"' not in content, "应移除旧的 radio 路由"
    print(f"  ✅ 旧路由已移除")

    print("✅ 多页面结构测试通过\n")


def test_kb_page_import():
    """测试知识库页面模块导入"""
    print("=" * 60)
    print("[Test 3] KB Page Module Import")
    print("=" * 60)

    # 测试导入（不运行 Streamlit）
    try:
        # 只导入非 Streamlit 依赖的部分
        from agent_system.kb_persistence import get_persistence, KBPersistence
        from agent_system.parsers.document_processor import DocumentProcessor
        from agent_system.storage_dispatcher import StorageDispatcher
        from agent_system.knowledge_router import KnowledgeRouter
        print(f"  ✅ 所有依赖模块导入成功")
    except ImportError as e:
        print(f"  ❌ 导入失败: {e}")
        raise

    print("✅ KB 页面模块导入测试通过\n")


def main():
    print("\n" + "=" * 60)
    print("Phase 4 测试开始")
    print("=" * 60 + "\n")

    try:
        test_persistence()
        test_multipage_structure()
        test_kb_page_import()

        print("=" * 60)
        print("🎉 所有 Phase 4 测试通过！")
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
