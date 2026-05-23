# -*- coding: utf-8 -*-
"""
ETL 数据导入页面

将 Cadence 网表/BOM 导入 Neo4j 图谱：
  1. 文件上传 — pstxnet.dat + pstxprt.dat + pstchip.dat + BOM
  2. 解析预览 — Component/Net/PartType 统计
  3. 质量检查 — PartType 覆盖率、核心网络识别率
  4. 入库执行 — 加载到 Neo4j
"""

from __future__ import annotations

import os
import sys
import tempfile

import streamlit as st

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from agent_system.etl_web_bridge import ETLWebExecutor, ETLResult


# ============================================================
# 页面配置
# ============================================================

# Page config removed - set in app.py

# ============================================================
# CSS 样式 — uses theme variables from app.py
# ============================================================

st.markdown("""
<style>
    .etl-header {
        font-size: 1.75rem;
        font-weight: 700;
        background: var(--gradient-hero, linear-gradient(135deg, #1a237e 0%, #00bcd4 100%));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .file-card {
        background-color: var(--bg-card, #f8f9fa);
        padding: 15px;
        border-radius: var(--radius-md, 10px);
        border: 1px solid var(--border-color, #dee2e6);
        margin-bottom: 10px;
        transition: all 0.25s ease;
    }
    .file-card:hover {
        border-color: var(--accent-cyan, #00bcd4);
        box-shadow: var(--shadow-hover, 0 4px 12px rgba(0,0,0,0.12));
    }
    .stat-card {
        background-color: var(--bg-card, #1c2333);
        padding: 15px;
        border-radius: var(--radius-md, 10px);
        border: 1px solid var(--border-color, #30363d);
        text-align: center;
        box-shadow: var(--shadow, 0 2px 8px rgba(0,0,0,0.3));
        transition: all 0.25s ease;
    }
    .stat-card:hover {
        box-shadow: var(--shadow-hover, 0 4px 16px rgba(0,0,0,0.4));
        transform: translateY(-2px);
        border-color: var(--accent-cyan, #00bcd4);
    }
    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: var(--accent-cyan, #00bcd4);
        line-height: 1.2;
    }
    .stat-label {
        font-size: 0.85rem;
        color: var(--text-secondary, #8b949e);
        margin-top: 4px;
    }
    .quality-pass { color: var(--success, #2ea043); font-weight: bold; }
    .quality-fail { color: var(--error, #f85149); font-weight: bold; }
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
# 辅助函数
# ============================================================

def save_uploaded_file(uploaded_file) -> str:
    """保存上传的文件到临时路径"""
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


# ============================================================
# Tab 1: 文件上传
# ============================================================

def render_upload():
    """文件上传 Tab"""
    st.markdown("### 📤 上传网表文件")
    st.markdown("上传 Cadence Allegro 导出的网表文件和 BOM")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 必需文件")

        pstxnet = st.file_uploader(
            "pstxnet.dat — 网络连接关系",
            type=["dat"],
            help="Cadence pstxnet.dat 文件，包含所有网络的连接关系"
        )

        pstxprt = st.file_uploader(
            "pstxprt.dat — 器件映射",
            type=["dat"],
            help="Cadence pstxprt.dat 文件，包含位号到模型名的映射"
        )

        pstchip = st.file_uploader(
            "pstchip.dat — 芯片属性",
            type=["dat"],
            help="Cadence pstchip.dat 文件，包含芯片引脚的电气属性"
        )

    with col2:
        st.markdown("#### 可选文件")

        bom = st.file_uploader(
            "BOM.csv / BOM.xlsx — 物料清单",
            type=["csv", "xlsx"],
            help="物料清单，用于 PartType 标准化和 MPN 信息"
        )

        st.markdown("---")
        st.markdown("#### 项目信息")
        project_name = st.text_input(
            "项目名称",
            value="",
            placeholder="如: Beet7_V1",
            help="用于标识本次导入的数据"
        )

    # 保存文件到 session state
    if pstxnet and pstxprt and pstchip:
        if st.button("📁 保存文件并预览", type="primary", use_container_width=True):
            with st.spinner("正在保存文件..."):
                files = {
                    "pstxnet": save_uploaded_file(pstxnet),
                    "pstxprt": save_uploaded_file(pstxprt),
                    "pstchip": save_uploaded_file(pstchip),
                }
                if bom:
                    files["bom"] = save_uploaded_file(bom)

                st.session_state.etl_files = files
                st.session_state.etl_project = project_name
                st.success("✅ 文件已保存，请切换到「解析预览」查看")
    else:
        st.info("👆 请上传所有必需文件（pstxnet.dat + pstxprt.dat + pstchip.dat）")


# ============================================================
# Tab 2: 解析预览
# ============================================================

def render_preview():
    """解析预览 Tab"""
    st.markdown("### 🔍 解析预览")

    if "etl_files" not in st.session_state or not st.session_state.etl_files:
        st.warning("⚠️ 请先上传文件")
        return

    files = st.session_state.etl_files
    project = st.session_state.get("etl_project", "")

    # 显示已上传文件
    st.markdown("#### 已上传文件")
    for key, path in files.items():
        size = os.path.getsize(path) / 1024
        st.markdown(f"- `{key}`: {os.path.basename(path)} ({size:.1f} KB)")

    if st.button("🚀 开始解析", type="primary"):
        with st.spinner("正在解析网表..."):
            executor = ETLWebExecutor()
            preview = executor.get_preview_stats(files)

            if preview.get("success"):
                st.session_state.etl_preview = preview
                st.success("✅ 解析完成")
            else:
                st.error(f"❌ 解析失败: {preview.get('error')}")
                return

    # 显示预览结果
    if "etl_preview" in st.session_state:
        preview = st.session_state.etl_preview

        st.markdown("---")
        st.markdown("#### 解析统计")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown("<div class='stat-card'>"
                       f"<div class='stat-number'>{preview['components_count']}</div>"
                       f"<div class='stat-label'>器件数</div></div>",
                       unsafe_allow_html=True)
        with col2:
            st.markdown("<div class='stat-card'>"
                       f"<div class='stat-number'>{preview['topology_count']}</div>"
                       f"<div class='stat-label'>拓扑连接</div></div>",
                       unsafe_allow_html=True)
        with col3:
            st.markdown("<div class='stat-card'>"
                       f"<div class='stat-number'>{preview['unique_nets']}</div>"
                       f"<div class='stat-label'>网络数</div></div>",
                       unsafe_allow_html=True)
        with col4:
            coverage = preview['parttype_coverage']
            color = "#21c354" if coverage >= 90 else "#ff4b4b"
            st.markdown("<div class='stat-card'>"
                       f"<div class='stat-number' style='color: {color};'>{coverage:.1f}%</div>"
                       f"<div class='stat-label'>PartType 覆盖率</div></div>",
                       unsafe_allow_html=True)

        # PartType 分布
        st.markdown("#### PartType 分布（前 15）")
        parttype_dist = preview.get("parttype_distribution", {})
        if parttype_dist:
            import pandas as pd
            df = pd.DataFrame([
                {"PartType": k, "数量": v}
                for k, v in parttype_dist.items()
            ])
            st.bar_chart(df.set_index("PartType"))

        # 网络统计
        st.markdown("#### 网络统计")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("电源网络", preview.get("power_nets_count", 0))
        with col2:
            st.metric("地网络", preview.get("ground_nets_count", 0))

        # 示例网络
        top_nets = preview.get("top_nets", [])
        if top_nets:
            st.caption(f"示例网络: {', '.join(top_nets[:5])}")


# ============================================================
# Tab 3: 质量检查
# ============================================================

def render_quality():
    """质量检查 Tab"""
    st.markdown("### ⚠️ 质量检查")

    if "etl_files" not in st.session_state or not st.session_state.etl_files:
        st.warning("⚠️ 请先上传文件")
        return

    if "etl_preview" not in st.session_state:
        st.info("💡 请先执行「解析预览」")
        return

    files = st.session_state.etl_files
    preview = st.session_state.etl_preview

    # 执行质量检查
    if st.button("🔍 执行质量检查", type="primary"):
        with st.spinner("正在检查数据质量..."):
            executor = ETLWebExecutor()
            result = executor.run(files, skip_quality=False)

            st.session_state.etl_quality = result

            if result.quality_passed:
                st.success("✅ 质量检查通过")
            else:
                st.error("❌ 质量检查未通过")

    # 显示质量结果
    if "etl_quality" in st.session_state:
        result = st.session_state.etl_quality

        if result.details:
            details = result.details

            st.markdown("---")
            st.markdown("#### 检查项")

            # PartType 覆盖率
            coverage = result.parttype_coverage
            col1, col2 = st.columns([1, 3])
            with col1:
                if coverage >= 90:
                    st.markdown("<span class='quality-pass'>✅ PASS</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span class='quality-fail'>❌ FAIL</span>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"**PartType 覆盖率**: {coverage:.1f}% (阈值: 90%)")

            # 核心网络
            st.markdown("---")
            st.markdown("#### 质量阈值说明")
            st.markdown("""
            - **PartType 覆盖率 ≥ 90%**: 确保大部分器件都有正确的类型分类
            - **核心网络识别率 = 100%**: VCC/GND/3V3 等关键电源网络必须被识别
            """)

            if not result.quality_passed:
                st.warning("⚠️ 质量检查未通过，建议检查 BOM 文件或调整 PartType 标准化规则")

                skip = st.checkbox("跳过质量检查（不推荐）")
                if skip:
                    st.session_state.etl_skip_quality = True
                    st.info("已设置跳过质量检查，可在「入库执行」中继续")


# ============================================================
# Tab 4: 入库执行
# ============================================================

def render_load():
    """入库执行 Tab"""
    st.markdown("### 🚀 入库执行")

    if "etl_files" not in st.session_state or not st.session_state.etl_files:
        st.warning("⚠️ 请先上传文件")
        return

    files = st.session_state.etl_files
    project = st.session_state.get("etl_project", "")
    skip_quality = st.session_state.get("etl_skip_quality", False)

    # 显示准备信息
    st.markdown("#### 准备入库")
    st.markdown(f"- **项目名称**: {project or '未命名'}")
    st.markdown(f"- **文件数**: {len(files)}")
    st.markdown(f"- **跳过质量检查**: {'是' if skip_quality else '否'}")

    # 确认 Neo4j 连接
    col1, col2 = st.columns(2)
    with col1:
        neo4j_uri = st.text_input("Neo4j URI", value="bolt://localhost:7687")
    with col2:
        neo4j_user = st.text_input("Neo4j 用户", value="neo4j")
        neo4j_password = st.text_input("Neo4j 密码", value="SecretPassword123", type="password")

    # 执行入库
    if st.button("🚀 开始入库", type="primary"):
        with st.spinner("正在入库到 Neo4j..."):
            executor = ETLWebExecutor(
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
            )
            result = executor.run(files, project_name=project, skip_quality=skip_quality)

            st.session_state.etl_result = result

            if result.success:
                st.balloons()
                st.success("🎉 ETL 入库完成！")
            else:
                st.error(f"❌ 入库失败: {result.message}")

    # 显示结果
    if "etl_result" in st.session_state:
        result = st.session_state.etl_result

        st.markdown("---")
        st.markdown("#### 入库报告")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("器件数", result.components_count)
        with col2:
            st.metric("拓扑连接", result.topology_count)
        with col3:
            st.metric("PartType 覆盖率", f"{result.parttype_coverage:.1f}%")

        if result.details:
            with st.expander("查看详情"):
                st.json(result.details)


# ============================================================
# 主页面
# ============================================================

def main():
    st.markdown("<div class='etl-header'>🔧 ETL 数据导入</div>", unsafe_allow_html=True)
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown("<span style='color:var(--text-secondary);font-size:0.9rem;'>将 Cadence 网表导入 Neo4j 图谱，建立原理图数据底座</span>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📤 文件上传",
        "🔍 解析预览",
        "⚠️ 质量检查",
        "🚀 入库执行",
    ])

    with tab1:
        render_upload()

    with tab2:
        render_preview()

    with tab3:
        render_quality()

    with tab4:
        render_load()


