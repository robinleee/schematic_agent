# -*- coding: utf-8 -*-
"""
知识库管理页面

5 个 Tab:
  1. 文档上传 — 上传文件并解析
  2. 文档列表 — 查看所有文档及状态
  3. 知识审核 — 审批待入库的知识
  4. 查询测试 — 测试 RAG 检索效果
  5. 统计面板 — 知识库统计信息
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import streamlit as st

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from agent_system.kb_persistence import get_persistence, DocumentRecord
from agent_system.parsers.document_processor import DocumentProcessor
from agent_system.parsers.checklist_parser import ChecklistParser
from agent_system.storage_dispatcher import StorageDispatcher, StorageResult
from agent_system.knowledge_router import KnowledgeRouter
from agent_system.storage_dispatcher import Neo4jKnowledgeStore
from agent_system.datasheet_processor import DatasheetPipeline


# ============================================================
# 页面配置
# ============================================================

# Page config removed - set in app.py

# ============================================================
# CSS 样式 — uses theme variables from app.py
# ============================================================

st.markdown("""
<style>
    .kb-header {
        font-size: 1.75rem;
        font-weight: 700;
        background: var(--gradient-hero, linear-gradient(135deg, #1a237e 0%, #00bcd4 100%));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .doc-card {
        background-color: var(--bg-card, #f8f9fa);
        padding: 15px;
        border-radius: var(--radius-md, 10px);
        border: 1px solid var(--border-color, #dee2e6);
        margin-bottom: 10px;
        box-shadow: var(--shadow, 0 2px 8px rgba(0,0,0,0.3));
        transition: all 0.25s ease;
    }
    .doc-card:hover {
        border-color: var(--accent-cyan, #00bcd4);
        box-shadow: var(--shadow-hover, 0 4px 16px rgba(0,0,0,0.4));
        transform: translateY(-1px);
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-uploaded {
        background-color: var(--info-bg, rgba(88,166,255,0.12));
        color: var(--info, #58a6ff);
        border: 1px solid var(--info, #58a6ff);
    }
    .status-processing {
        background-color: var(--warning-bg, rgba(210,153,34,0.12));
        color: var(--warning, #d29922);
        border: 1px solid var(--warning, #d29922);
    }
    .status-pending_review {
        background-color: var(--warning-bg, rgba(210,153,34,0.12));
        color: var(--warning, #d29922);
        border: 1px solid var(--warning, #d29922);
    }
    .status-stored {
        background-color: var(--success-bg, rgba(46,160,67,0.12));
        color: var(--success, #2ea043);
        border: 1px solid var(--success, #2ea043);
    }
    .status-rejected {
        background-color: var(--error-bg, rgba(248,81,73,0.12));
        color: var(--error, #f85149);
        border: 1px solid var(--error, #f85149);
    }
    .result-item {
        background-color: var(--bg-card, #1c2333);
        padding: 10px;
        border-radius: var(--radius-sm, 6px);
        margin: 5px 0;
        border: 1px solid var(--border-color, #30363d);
    }
    .header-line {
        height: 3px;
        background: var(--gradient-hero, linear-gradient(135deg, #1a237e 0%, #00bcd4 100%));
        border-radius: 2px;
        margin-bottom: 16px;
    }
    .section-label {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--accent-cyan, #00bcd4);
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Session State 初始化
# ============================================================

if "kb_persistence" not in st.session_state:
    st.session_state.kb_persistence = get_persistence()

if "kb_dispatcher" not in st.session_state:
    st.session_state.kb_dispatcher = StorageDispatcher()

if "kb_router" not in st.session_state:
    st.session_state.kb_router = KnowledgeRouter()

# ============================================================
# 辅助函数
# ============================================================

def get_status_badge(status: str) -> str:
    """获取状态徽章 HTML"""
    status_map = {
        "uploaded": ("已上传", "status-uploaded"),
        "processing": ("处理中", "status-processing"),
        "pending_review": ("待审核", "status-pending_review"),
        "stored": ("已入库", "status-stored"),
        "rejected": ("已拒绝", "status-rejected"),
    }
    label, css_class = status_map.get(status, (status, "status-uploaded"))
    return f'<span class="status-badge {css_class}">{label}</span>'


def format_datetime(iso_str: str) -> str:
    """格式化 ISO 时间字符串"""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return iso_str[:16]


# ============================================================
# Tab 1: 文档上传
# ============================================================

def render_upload():
    """文档上传 Tab"""
    st.markdown("### 📤 上传新文档")
    st.markdown("支持 PDF、Markdown、TXT、CSV、Excel 格式")

    col1, col2 = st.columns([2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "选择文件",
            type=["pdf", "md", "txt", "csv", "xlsx"],
            help="上传设计指南、Checklist、Datasheet 或经验文档"
        )

    with col2:
        doc_type = st.selectbox(
            "文档类型",
            options=[
                ("design_guide", "📖 设计指南"),
                ("checklist", "✅ 审查清单"),
                ("datasheet", "📄 Datasheet"),
                ("expert_note", "📝 经验文档"),
            ],
            format_func=lambda x: x[1],
        )[0]

        category = st.text_input(
            "分类标签",
            value="general",
            help="如: usb, i2c, power, signal_integrity"
        )

    source_id = st.text_input(
        "来源标识（可选）",
        value="",
        placeholder="如: usb3_design_guide_v1.0",
        help="用于追溯和查询，建议填写"
    )

    project = st.text_input(
        "项目标识（可选）",
        value="",
        placeholder="如: board_a",
        help="关联的具体项目"
    )

    if uploaded_file is not None:
        st.markdown("---")
        st.markdown("#### 文件信息")
        st.markdown(f"- **文件名**: `{uploaded_file.name}`")
        st.markdown(f"- **类型**: {doc_type}")
        st.markdown(f"- **大小**: {uploaded_file.size / 1024:.1f} KB")

        if st.button("🚀 开始处理", type="primary", use_container_width=True):
            with st.spinner("正在解析文档..."):
                _process_uploaded_file(uploaded_file, doc_type, source_id, category, project)


def _process_uploaded_file(uploaded_file, doc_type: str, source_id: str, category: str, project: str):
    """处理上传的文件"""
    persistence = st.session_state.kb_persistence

    # 1. 保存到临时文件
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        # 2. 创建文档记录
        metadata = {
            "source_id": source_id or uploaded_file.name,
            "category": category,
            "project": project,
        }
        doc = persistence.add_document(uploaded_file.name, doc_type, metadata)

        # 3. 解析文档
        persistence.update_status(doc.doc_id, "processing")

        processor = DocumentProcessor()
        result = processor.process(tmp_path, doc_type)

        if result.is_success():
            # 4. 更新结果摘要
            summary = {
                "chunks": len(result.chunks),
                "rules": len(result.rules),
                "parameters": len(result.parameters),
                "doc_title": result.metadata.get("title", ""),
            }
            persistence.update_result(doc.doc_id, summary)
            persistence.update_status(doc.doc_id, "pending_review")

            st.success(f"✅ 解析完成！提取了 {summary['chunks']} 个切片 / {summary['rules']} 条规则")

            # 5. 展示预览
            with st.expander("查看提取结果预览"):
                if result.chunks:
                    st.markdown("**切片预览**:")
                    for i, chunk in enumerate(result.chunks[:3]):
                        st.markdown(f"- `{chunk.category}`: {chunk.title}")
                    if len(result.chunks) > 3:
                        st.caption(f"... 还有 {len(result.chunks) - 3} 个切片")

                if result.rules:
                    st.markdown("**规则预览**:")
                    for i, rule in enumerate(result.rules[:3]):
                        st.markdown(f"- `{rule.rule_id}`: {rule.name}")
                    if len(result.rules) > 3:
                        st.caption(f"... 还有 {len(result.rules) - 3} 条规则")

        else:
            persistence.update_status(doc.doc_id, "rejected", error_message=result.error)
            st.error(f"❌ 解析失败: {result.error}")

    except Exception as e:
        persistence.update_status(doc.doc_id, "rejected", error_message=str(e))
        st.error(f"❌ 处理异常: {e}")

    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ============================================================
# Tab 2: 文档列表
# ============================================================

def render_list():
    """文档列表 Tab"""
    st.markdown("### 📋 文档列表")

    persistence = st.session_state.kb_persistence
    docs = persistence.get_all_documents()

    # 筛选
    col1, col2, col3 = st.columns(3)
    with col1:
        filter_type = st.selectbox(
            "文档类型",
            options=["全部", "design_guide", "checklist", "datasheet", "expert_note"],
            format_func=lambda x: {
                "全部": "全部类型",
                "design_guide": "📖 设计指南",
                "checklist": "✅ 审查清单",
                "datasheet": "📄 Datasheet",
                "expert_note": "📝 经验文档",
            }.get(x, x),
        )

    with col2:
        filter_status = st.selectbox(
            "状态",
            options=["全部", "uploaded", "processing", "pending_review", "stored", "rejected"],
            format_func=lambda x: {
                "全部": "全部状态",
                "uploaded": "已上传",
                "processing": "处理中",
                "pending_review": "待审核",
                "stored": "已入库",
                "rejected": "已拒绝",
            }.get(x, x),
        )

    with col3:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    # 过滤文档
    filtered = docs
    if filter_type != "全部":
        filtered = [d for d in filtered if d.doc_type == filter_type]
    if filter_status != "全部":
        filtered = [d for d in filtered if d.status == filter_status]

    # 显示文档
    if not filtered:
        st.info("暂无文档")
        return

    st.markdown(f"共 **{len(filtered)}** 个文档")

    for doc in filtered:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

            with col1:
                st.markdown(f"**{doc.filename}**")
                st.caption(f"ID: `{doc.doc_id}`")
                if doc.metadata.get("source_id"):
                    st.caption(f"来源: {doc.metadata['source_id']}")

            with col2:
                st.markdown(get_status_badge(doc.status), unsafe_allow_html=True)
                st.caption(f"类型: {doc.doc_type}")

            with col3:
                st.caption(f"上传: {format_datetime(doc.uploaded_at)}")
                if doc.result_summary:
                    summary_parts = []
                    if doc.result_summary.get("chunks"):
                        summary_parts.append(f"{doc.result_summary['chunks']} 切片")
                    if doc.result_summary.get("rules"):
                        summary_parts.append(f"{doc.result_summary['rules']} 规则")
                    if summary_parts:
                        st.caption(" | ".join(summary_parts))

            with col4:
                if doc.status == "pending_review":
                    if st.button("✅ 批准", key=f"approve_{doc.doc_id}"):
                        _approve_document(doc.doc_id)
                        st.rerun()
                    if st.button("❌ 拒绝", key=f"reject_{doc.doc_id}"):
                        _reject_document(doc.doc_id)
                        st.rerun()
                elif doc.status == "stored":
                    st.markdown("🟢 已入库")
                elif doc.status == "rejected":
                    st.markdown("🔴 已拒绝")
                    if doc.error_message:
                        st.caption(f"原因: {doc.error_message[:50]}")

            st.markdown("---")


def _approve_document(doc_id: str):
    """批准文档入库"""
    persistence = st.session_state.kb_persistence
    dispatcher = st.session_state.kb_dispatcher

    doc = persistence.get_document(doc_id)
    if not doc:
        st.error("文档不存在")
        return

    # TODO: 这里需要重新解析并存储
    # 由于 ProcessingResult 没有在持久化中保存完整对象，
    # 实际场景中需要在审批时重新解析或从缓存中获取

    persistence.approve(doc_id, reviewer="web_user", comment="审核通过")
    st.success(f"文档 {doc_id} 已批准入库")


def _reject_document(doc_id: str):
    """拒绝文档"""
    persistence = st.session_state.kb_persistence
    persistence.reject(doc_id, reviewer="web_user", comment="审核不通过")
    st.warning(f"文档 {doc_id} 已拒绝")


# ============================================================
# Tab 3: 知识审核
# ============================================================

def render_review():
    """知识审核 Tab"""
    st.markdown("### ✅ 知识审核")
    st.markdown("审批待入库的知识，确保质量")

    persistence = st.session_state.kb_persistence
    pending = persistence.get_pending_review()

    if not pending:
        st.info("🎉 没有待审核的知识")
        return

    st.markdown(f"待审核: **{len(pending)}** 个文档")

    for doc in pending:
        with st.expander(f"📄 {doc.filename} ({doc.doc_type})", expanded=True):
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**文档 ID**: `{doc.doc_id}`")
                st.markdown(f"**类型**: {doc.doc_type}")
                st.markdown(f"**上传时间**: {format_datetime(doc.uploaded_at)}")

                if doc.result_summary:
                    st.markdown("**提取结果**:")
                    if doc.result_summary.get("chunks"):
                        st.markdown(f"- 切片数: {doc.result_summary['chunks']}")
                    if doc.result_summary.get("rules"):
                        st.markdown(f"- 规则数: {doc.result_summary['rules']}")
                    if doc.result_summary.get("parameters"):
                        st.markdown(f"- 参数数: {doc.result_summary['parameters']}")

                if doc.metadata:
                    st.markdown("**元数据**:")
                    for k, v in doc.metadata.items():
                        if v:
                            st.markdown(f"- {k}: `{v}`")

            with col2:
                st.markdown("#### 审批操作")

                review_comment = st.text_area(
                    "审批意见",
                    value="",
                    placeholder="输入审批意见（可选）",
                    key=f"comment_{doc.doc_id}",
                )

                if st.button("✅ 批准入库", type="primary", key=f"review_approve_{doc.doc_id}", use_container_width=True):
                    persistence.approve(doc.doc_id, reviewer="web_user", comment=review_comment)
                    st.success("✅ 已批准")
                    st.rerun()

                if st.button("❌ 拒绝", key=f"review_reject_{doc.doc_id}", use_container_width=True):
                    persistence.reject(doc.doc_id, reviewer="web_user", comment=review_comment)
                    st.warning("❌ 已拒绝")
                    st.rerun()


# ============================================================
# Tab 4: 查询测试
# ============================================================

def render_query():
    """查询测试 Tab"""
    st.markdown("### 🔍 查询测试")
    st.markdown("测试知识库 RAG 检索效果")

    router = st.session_state.kb_router

    # 查询输入
    query = st.text_area(
        "查询内容",
        value="USB3.0 差分对的阻抗要求是多少？",
        placeholder="输入您想查询的硬件设计问题",
        height=100,
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        n_results = st.slider("返回数量", 1, 10, 3)
    with col2:
        mpn_filter = st.text_input(
            "MPN 过滤（可选）",
            value="",
            placeholder="输入 MPN 进行精确匹配",
        )

    if st.button("🔍 执行查询", type="primary"):
        with st.spinner("正在检索..."):
            try:
                results = router.search(mpn_filter or "general", query, n=n_results)

                if results and results[0].status == "success":
                    st.success(f"找到 {len(results)} 条结果")

                    for i, r in enumerate(results, 1):
                        with st.container():
                            st.markdown(f"**结果 {i}** (置信度: {r.confidence:.2f})")
                            st.markdown(f"```\n{r.content[:500]}\n```")
                            if r.source:
                                st.caption(f"来源: {r.source}")
                            st.markdown("---")
                else:
                    st.info("未找到相关结果，知识库可能为空或查询不匹配")

            except Exception as e:
                st.error(f"查询失败: {e}")


# ============================================================
# Tab 5: 统计面板
# ============================================================

def render_stats():
    """统计面板 Tab"""
    st.markdown("### 📊 知识库统计")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📚 文档统计")
        persistence = st.session_state.kb_persistence
        stats = persistence.get_stats()

        # 文档总数和状态分布
        st.metric("总文档数", stats["total"])

        if stats["by_status"]:
            st.markdown("**状态分布**:")
            for status, count in sorted(stats["by_status"].items()):
                st.markdown(f"- {status}: {count}")

        if stats["by_type"]:
            st.markdown("**类型分布**:")
            type_names = {
                "design_guide": "📖 设计指南",
                "checklist": "✅ 审查清单",
                "datasheet": "📄 Datasheet",
                "expert_note": "📝 经验文档",
            }
            for doc_type, count in sorted(stats["by_type"].items()):
                st.markdown(f"- {type_names.get(doc_type, doc_type)}: {count}")

    with col2:
        st.markdown("#### 🗄️ 存储统计")

        # ChromaDB 统计
        try:
            router = st.session_state.kb_router
            kb_stats = router.get_stats()
            st.metric("ChromaDB 切片数", kb_stats.get("tier1_chunks", 0))
        except Exception as e:
            st.caption(f"ChromaDB: 无法获取统计 ({e})")

        # Neo4j 统计
        try:
            neo4j_store = Neo4jKnowledgeStore()
            neo4j_stats = neo4j_store.get_stats()

            col_n1, col_n2 = st.columns(2)
            with col_n1:
                st.metric("规则总数", neo4j_stats["rules"]["total"])
            with col_n2:
                st.metric("知识切片", neo4j_stats["knowledge_chunks"]["total"])

            if neo4j_stats["rules"]["total"] > 0:
                st.markdown("**规则分布**:")
                st.markdown(f"- 启用: {neo4j_stats['rules']['enabled']}")
                st.markdown(f"- ERROR: {neo4j_stats['rules']['errors']}")
                st.markdown(f"- WARNING: {neo4j_stats['rules']['warnings']}")

            neo4j_store.close()
        except Exception as e:
            st.caption(f"Neo4j: 无法获取统计 ({e})")

    # 最近活动
    st.markdown("---")
    st.markdown("#### 🕐 最近活动")

    recent_docs = persistence.get_all_documents()[:5]
    if recent_docs:
        for doc in recent_docs:
            st.markdown(
                f"- `{format_datetime(doc.uploaded_at)}` "
                f"[{doc.doc_type}] {doc.filename} "
                f"— {get_status_badge(doc.status)}",
                unsafe_allow_html=True
            )
    else:
        st.info("暂无活动记录")


# ============================================================
# Tab 6: Datasheet Upload
# ============================================================

def render_datasheet_upload():
    """Datasheet upload tab with multi-file support and semantic processing"""
    st.markdown("### 📤 Datasheet Upload")
    st.markdown("Upload component datasheets (PDF) for semantic indexing and AMR derating")

    uploaded_files = st.file_uploader(
        "Select PDF datasheets",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload one or more component datasheets in PDF format",
    )

    col1, col2 = st.columns(2)
    with col1:
        component_hint = st.text_input(
            "Component type hint (optional)",
            value="",
            placeholder="e.g. capacitor, resistor, IC, PMIC",
            help="Helps the parser focus on relevant parameters",
        )
    with col2:
        mpn_hint = st.text_input(
            "MPN hint (optional)",
            value="",
            placeholder="e.g. GRM21BR71H104KA01",
            help="Part number to associate with the datasheet",
        )

    if uploaded_files:
        st.markdown(f"**{len(uploaded_files)} file(s) selected**")
        for f in uploaded_files:
            size_kb = f.size / 1024
            st.markdown(f"- `{f.name}` ({size_kb:.1f} KB)")

        if st.button("🚀 Process & Index", type="primary", use_container_width=True):
            _process_datasheets(uploaded_files, component_hint, mpn_hint)


def _process_datasheets(uploaded_files, component_hint: str, mpn_hint: str):
    """Process and index uploaded datasheets"""
    pipeline = DatasheetPipeline()
    total = len(uploaded_files)

    progress_bar = st.progress(0)
    status_text = st.empty()

    results = []
    for i, uploaded_file in enumerate(uploaded_files):
        pct = int((i / total) * 100)
        progress_bar.progress(pct)
        status_text.text(f"Processing {i+1}/{total}: {uploaded_file.name}")

        # Save to temp file
        suffix = os.path.splitext(uploaded_file.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/dev/shm") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            result = pipeline.process_pdf(
                pdf_path=tmp_path,
                filename=uploaded_file.name,
                component_hint=component_hint or None,
                mpn_hint=mpn_hint or None,
            )
            results.append({
                "filename": uploaded_file.name,
                "status": "success" if result["success"] else "error",
                "chunks": result.get("chunks_indexed", 0),
                "mpn": result.get("mpn", ""),
                "error": result.get("error", ""),
            })
        except Exception as e:
            results.append({
                "filename": uploaded_file.name,
                "status": "error",
                "chunks": 0,
                "mpn": "",
                "error": str(e),
            })
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    progress_bar.progress(100)
    status_text.text("Processing complete!")

    # Display results
    st.markdown("---")
    st.markdown("### Results")

    success_count = sum(1 for r in results if r["status"] == "success")
    st.metric("Processed", f"{success_count}/{total}")

    for r in results:
        if r["status"] == "success":
            st.success(f"✅ **{r['filename']}** — {r['chunks']} chunks indexed (MPN: {r['mpn']})")
        else:
            st.error(f"❌ **{r['filename']}** — {r['error']}")


# ============================================================
# 主页面
# ============================================================

def main():
    st.markdown("<div class='kb-header'>📚 知识库管理</div>", unsafe_allow_html=True)
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown("<span style='color:var(--text-secondary);font-size:0.9rem;'>管理硬件设计知识：上传文档、审核知识、查询检索</span>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📤 文档上传",
        "📋 文档列表",
        "✅ 知识审核",
        "🔍 查询测试",
        "📊 统计面板",
        "📄 Datasheet Upload",
    ])

    with tab1:
        render_upload()

    with tab2:
        render_list()

    with tab3:
        render_review()

    with tab4:
        render_query()

    with tab5:
        render_stats()

    with tab6:
        render_datasheet_upload()


if __name__ == "__main__":
    main()
