"""
Hardware AI Expert System - Streamlit Web UI

功能模块：
  1. 聊天界面：与 Agent 对话，支持审查/诊断/查询
  2. 审查报告：可视化 Review Engine 输出
  3. HITL 审批：工程师审批违规项
  4. 系统状态：监控 Neo4j/Ollama 状态
"""

import os
import sys
import json
import logging
from datetime import datetime

import streamlit as st

# 将项目根目录加入路径
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from agent_system.agent_core import HardwareAgent
from agent_system.hitl_workflow import HITLManager, PendingReview
from agent_system.datasheet_hitl import DatasheetHITLManager
from agent_system.datasheet_parser import DatasheetParser
from agent_system.graph_rag_bridge import GraphRAGBridge
from agent_system.graph_tools import (
    get_graph_summary,
    get_power_domain,
    get_i2c_devices,
)

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="硬件 AI 专家系统",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CSS 样式
# ============================================================

st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .violation-error { color: #ff4b4b; font-weight: bold; }
    .violation-warning { color: #ffa421; font-weight: bold; }
    .violation-info { color: #21c354; }
    .chat-user { background-color: #e8f4f8; padding: 10px; border-radius: 10px; margin: 5px 0; }
    .chat-assistant { background-color: #f0f0f0; padding: 10px; border-radius: 10px; margin: 5px 0; }
    .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; }
    .status-online { color: #21c354; font-weight: bold; }
    .status-offline { color: #ff4b4b; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Session State 初始化
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    st.session_state.agent = HardwareAgent()

if "review_results" not in st.session_state:
    st.session_state.review_results = None

if "hitl_manager" not in st.session_state:
    st.session_state.hitl_manager = HITLManager()

if "datasheet_hitl" not in st.session_state:
    st.session_state.datasheet_hitl = DatasheetHITLManager()

# ============================================================
# 侧边栏
# ============================================================

with st.sidebar:
    st.markdown("<div class='main-header'>🔧 硬件 AI 专家系统</div>", unsafe_allow_html=True)
    st.markdown("---")

    # 导航
    page = st.radio("导航", [
        "💬 智能对话",
        "📋 审查报告",
        "✅ HITL 审批",
        "📄 Datasheet 审批",
        "📊 系统状态",
    ])

    st.markdown("---")

    # 快速操作
    st.markdown("### 快速操作")
    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.rerun()

    if st.button("🔍 系统概览"):
        try:
            summary = get_graph_summary.invoke({})
            st.session_state.graph_summary = summary
            st.success("已加载系统概览")
        except Exception as e:
            st.error(f"加载失败: {e}")

# ============================================================
# 页面 1: 智能对话
# ============================================================

def render_chat():
    st.markdown("<div class='main-header'>💬 智能对话</div>", unsafe_allow_html=True)
    st.markdown("与硬件 AI 专家对话，支持：审查、诊断、查询")

    # 显示历史消息
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 输入框
    user_input = st.chat_input("输入您的问题...")

    if user_input:
        # 添加用户消息
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # 调用 Agent
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                try:
                    result = st.session_state.agent.review(user_input)

                    # 格式化输出
                    report = result.get("report", "")
                    review_report = result.get("review_report", "")
                    violations = result.get("violations", [])

                    if review_report:
                        response = review_report
                    elif report:
                        response = report
                    elif violations:
                        lines = ["### 审查发现", ""]
                        for v in violations[:10]:  # 最多显示 10 条
                            severity_emoji = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🟢"}.get(v.get("severity", ""), "⚪")
                            lines.append(f"{severity_emoji} **{v.get('rule_name', 'Unknown')}**")
                            lines.append(f"   - 器件: `{v.get('refdes', 'N/A')}`")
                            lines.append(f"   - 问题: {v.get('description', '')}")
                            lines.append(f"   - 期望: {v.get('expected', '')}")
                            lines.append("")
                        if len(violations) > 10:
                            lines.append(f"*... 还有 {len(violations) - 10} 条违规项，请在审查报告页面查看完整列表*")
                        response = "\n".join(lines)
                    else:
                        response = "✅ 未发现问题，设计看起来合规。"

                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})

                    # 保存审查结果供其他页面使用
                    if violations:
                        st.session_state.review_results = result

                except Exception as e:
                    error_msg = f"❌ 处理失败: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

# ============================================================
# 页面 2: 审查报告
# ============================================================

def render_review_report():
    st.markdown("<div class='main-header'>📋 审查报告</div>", unsafe_allow_html=True)

    if not st.session_state.review_results:
        st.info("暂无审查结果。请在对话页面执行审查任务，或点击下方的'运行全板审查'。")

        if st.button("🔍 运行全板审查"):
            with st.spinner("正在审查，这可能需要几分钟..."):
                try:
                    result = st.session_state.agent.review("执行完整原理图审查")
                    st.session_state.review_results = result
                    st.success("审查完成！")
                    st.rerun()
                except Exception as e:
                    st.error(f"审查失败: {e}")
        return

    result = st.session_state.review_results
    violations = result.get("violations", [])

    # 统计卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总违规数", len(violations))
    with col2:
        error_count = sum(1 for v in violations if v.get("severity") == "ERROR")
        st.metric("ERROR", error_count, delta=None)
    with col3:
        warn_count = sum(1 for v in violations if v.get("severity") == "WARNING")
        st.metric("WARNING", warn_count, delta=None)
    with col4:
        st.metric("工具调用", result.get("tool_call_count", 0))

    st.markdown("---")

    # 违规列表
    if not violations:
        st.success("🎉 未发现违规项！设计完全合规。")
        return

    # 筛选
    severity_filter = st.multiselect(
        "筛选严重级别",
        ["ERROR", "WARNING", "INFO"],
        default=["ERROR", "WARNING"],
    )

    filtered = [v for v in violations if v.get("severity", "") in severity_filter]

    st.markdown(f"显示 {len(filtered)} / {len(violations)} 条违规项")

    for i, v in enumerate(filtered, 1):
        severity = v.get("severity", "INFO")
        color_class = {
            "ERROR": "violation-error",
            "WARNING": "violation-warning",
            "INFO": "violation-info",
        }.get(severity, "")

        with st.expander(f"{i}. [{severity}] {v.get('rule_name', 'Unknown')} - {v.get('refdes', 'N/A')}"):
            st.markdown(f"**规则 ID**: `{v.get('rule_id', 'N/A')}`")
            st.markdown(f"**器件位号**: `{v.get('refdes', 'N/A')}`")
            st.markdown(f"**网络**: `{v.get('net_name', 'N/A')}`")
            st.markdown(f"**描述**: {v.get('description', '')}")
            st.markdown(f"**期望**: <span style='color:green'>{v.get('expected', '')}</span>", unsafe_allow_html=True)
            st.markdown(f"**实际**: <span style='color:red'>{v.get('actual', '')}</span>", unsafe_allow_html=True)

            # 添加到 HITL
            if st.button(f"📝 加入 HITL 审批", key=f"hitl_{i}"):
                pr = PendingReview(
                    review_id="",
                    rule_id=v.get("rule_id", ""),
                    rule_name=v.get("rule_name", ""),
                    refdes=v.get("refdes", ""),
                    net_name=v.get("net_name", ""),
                    description=v.get("description", ""),
                    severity=severity,
                    expected=v.get("expected", ""),
                    actual=v.get("actual", ""),
                )
                st.session_state.hitl_manager.add_pending(pr)
                st.success(f"已添加 {v.get('refdes', '')} 到 HITL 审批队列")

    # 导出按钮
    st.markdown("---")
    if st.button("📥 导出报告为 Markdown"):
        report_md = _generate_markdown_report(result)
        st.download_button(
            label="下载报告",
            data=report_md,
            file_name=f"review_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown",
        )

# ============================================================
# 页面 3: HITL 审批
# ============================================================

def render_hitl():
    st.markdown("<div class='main-header'>✅ HITL 审批</div>", unsafe_allow_html=True)
    st.markdown("工程师审批 Agent 发现的违规项，批准后自动落盘为规则。")

    manager = st.session_state.hitl_manager

    # 统计
    stats = manager.get_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("待审批", stats["pending"])
    with col2:
        st.metric("已批准", stats["approved"])
    with col3:
        st.metric("已拒绝", stats["rejected"])
    with col4:
        st.metric("已落盘", stats["persisted"])

    st.markdown("---")

    # 审批操作
    tab1, tab2, tab3 = st.tabs(["⏳ 待审批", "✅ 已批准", "❌ 已拒绝"])

    with tab1:
        pending = manager.get_pending_list("pending")
        if not pending:
            st.info("没有待审批项")
        else:
            for pr in pending:
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{pr.rule_name}** ({pr.rule_id})")
                        st.markdown(f"器件: `{pr.refdes}` | 网络: `{pr.net_name}`")
                        st.markdown(f"描述: {pr.description}")
                        st.markdown(f"严重程度: `{pr.severity}`")
                    with col2:
                        if st.button("✅ 批准", key=f"approve_{pr.review_id}"):
                            manager.approve(pr.review_id, reviewer="engineer", comment="确认问题")
                            st.success("已批准")
                            st.rerun()
                        if st.button("❌ 拒绝", key=f"reject_{pr.review_id}"):
                            manager.reject(pr.review_id, reviewer="engineer", comment="误报")
                            st.warning("已拒绝")
                            st.rerun()
                    st.markdown("---")

    with tab2:
        approved = manager.get_pending_list("approved")
        if not approved:
            st.info("没有已批准项")
        else:
            for pr in approved:
                st.markdown(f"✅ **{pr.rule_name}** - `{pr.refdes}`")
                st.caption(f"审批人: {pr.reviewer} | 意见: {pr.review_comment}")

            if st.button("💾 落盘为规则"):
                result = manager.save_approved_rules()
                if result.get("saved", 0) > 0:
                    st.success(f"已保存 {result['saved']} 条规则到 custom_rules.yaml")
                else:
                    st.warning(result.get("message", "没有可保存的规则"))

    with tab3:
        rejected = manager.get_pending_list("rejected")
        if not rejected:
            st.info("没有已拒绝项")
        else:
            for pr in rejected:
                st.markdown(f"❌ **{pr.rule_name}** - `{pr.refdes}`")
                st.caption(f"审批人: {pr.reviewer} | 理由: {pr.review_comment}")

# ============================================================
# 页面 4: 系统状态
# ============================================================

def render_system_status():
    st.markdown("<div class='main-header'>📊 系统状态</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Neo4j 数据库")
        try:
            from agent_system.graph_tools import _run_cypher
            result = _run_cypher("MATCH (n) RETURN count(n) AS cnt")
            node_count = result[0]["cnt"] if result else 0

            result = _run_cypher("MATCH ()-[r]->() RETURN count(r) AS cnt")
            rel_count = result[0]["cnt"] if result else 0

            result = _run_cypher("MATCH (c:Component) RETURN count(c) AS cnt")
            comp_count = result[0]["cnt"] if result else 0

            result = _run_cypher("MATCH (n:Net) RETURN count(n) AS cnt")
            net_count = result[0]["cnt"] if result else 0

            st.markdown(f"<span class='status-online'>● 在线</span>", unsafe_allow_html=True)
            st.metric("总节点数", node_count)
            st.metric("关系数", rel_count)
            st.metric("Component 节点", comp_count)
            st.metric("Net 节点", net_count)

        except Exception as e:
            st.markdown(f"<span class='status-offline'>● 离线</span>", unsafe_allow_html=True)
            st.error(f"连接失败: {e}")

    with col2:
        st.markdown("### Ollama LLM")
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]

            st.markdown(f"<span class='status-online'>● 在线</span>", unsafe_allow_html=True)
            st.metric("可用模型", len(models))
            for m in models:
                st.markdown(f"- `{m}`")

        except Exception as e:
            st.markdown(f"<span class='status-offline'>● 离线</span>", unsafe_allow_html=True)
            st.error(f"连接失败: {e}")

    st.markdown("---")

    # GraphRAG 状态
    st.markdown("### GraphRAG 状态")
    try:
        bridge = GraphRAGBridge()
        stats = bridge.get_stats()
        bridge.close()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("VectorChunk 节点", stats["vector_chunks"])
        with col2:
            st.metric("DESCRIBES 关系", stats["describes_relations"])
        with col3:
            st.metric("关联 Component", stats["linked_components"])
    except Exception as e:
        st.warning(f"GraphRAG 状态获取失败: {e}")

    st.markdown("---")

    # 快速查询
    st.markdown("### 快速图谱查询")
    query_type = st.selectbox("查询类型", [
        "电源域概览",
        "I2C 设备列表",
        "图结构摘要",
    ])

    if st.button("执行查询"):
        with st.spinner("查询中..."):
            try:
                if query_type == "电源域概览":
                    result = get_power_domain.invoke({})
                    st.text(result)
                elif query_type == "I2C 设备列表":
                    result = get_i2c_devices.invoke({})
                    st.text(result)
                elif query_type == "图结构摘要":
                    result = get_graph_summary.invoke({})
                    st.text(result)
            except Exception as e:
                st.error(f"查询失败: {e}")

# ============================================================
# 页面 5: Datasheet 审批
# ============================================================

def render_datasheet_hitl():
    st.markdown("<div class='main-header'>📄 Datasheet 审批</div>", unsafe_allow_html=True)
    st.markdown("从 Datasheet PDF 提取参数，工程师审批后落盘到 AMR 数据源。")

    manager = st.session_state.datasheet_hitl

    # 统计
    stats = manager.get_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("待审批", stats["pending"])
    with col2:
        st.metric("已批准", stats["approved"])
    with col3:
        st.metric("已拒绝", stats["rejected"])
    with col4:
        st.metric("总计", stats["total"])

    st.markdown("---")

    # 上传 PDF 并解析
    st.markdown("### 上传 Datasheet PDF")
    uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

    if uploaded_file is not None:
        col1, col2 = st.columns(2)
        with col1:
            component_hint = st.text_input("器件类型提示", "capacitor", help="如 capacitor, resistor, buck_converter")
        with col2:
            mpn_override = st.text_input("MPN 覆盖（可选）", "", help="如果文件名不是 MPN，在此输入")

        if st.button("🔍 解析 PDF"):
            with st.spinner("正在解析 PDF..."):
                try:
                    # 保存上传的文件
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    # 解析
                    parser = DatasheetParser(use_llm=False)  # Web UI 中先用 Regex，避免 LLM 超时
                    result = parser.parse_pdf(tmp_path, component_hint)

                    if mpn_override:
                        result.mpn = mpn_override

                    # 添加到 HITL
                    review_ids = manager.add_extracted_component(result)

                    st.success(f"解析完成！提取了 {len(result.parameters)} 个参数，已添加到审批队列")

                    # 显示提取结果
                    st.markdown("#### 提取的参数")
                    for p in result.parameters:
                        st.markdown(f"- **{p.name}**: {p.value} {p.unit} (`{p.param_type.value}`)")

                    # 清理临时文件
                    os.unlink(tmp_path)

                except Exception as e:
                    st.error(f"解析失败: {e}")

    st.markdown("---")

    # 审批操作
    tab1, tab2, tab3 = st.tabs(["⏳ 待审批", "✅ 已批准", "❌ 已拒绝"])

    with tab1:
        pending = manager.get_pending_list()
        if not pending:
            st.info("没有待审批的参数")
        else:
            for pr in pending:
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{pr.param_name}** (`{pr.param_type}`)")
                        st.markdown(f"MPN: `{pr.mpn}` | 值: **{pr.value} {pr.unit}**")
                        if pr.source_text:
                            st.caption(f"原文: {pr.source_text[:100]}")
                        if pr.confidence < 1.0:
                            st.caption(f"置信度: {pr.confidence:.0%}")
                    with col2:
                        if st.button("✅ 批准", key=f"ds_approve_{pr.review_id}"):
                            manager.approve(pr.review_id, reviewer="web_user", comment="确认")
                            st.success("已批准")
                            st.rerun()
                        if st.button("❌ 拒绝", key=f"ds_reject_{pr.review_id}"):
                            manager.reject(pr.review_id, reviewer="web_user", comment="误报")
                            st.warning("已拒绝")
                            st.rerun()
                        # 修改按钮
                        new_val = st.number_input("修改值", value=float(pr.value), key=f"ds_mod_val_{pr.review_id}")
                        new_unit = st.text_input("修改单位", value=pr.unit, key=f"ds_mod_unit_{pr.review_id}")
                        if st.button("✏️ 修改并批准", key=f"ds_modify_{pr.review_id}"):
                            manager.modify(pr.review_id, new_value=new_val, new_unit=new_unit,
                                          reviewer="web_user", comment="修正数值")
                            st.success("已修改并批准")
                            st.rerun()
                    st.markdown("---")

    with tab2:
        approved = manager.get_approved_list()
        if not approved:
            st.info("没有已批准的参数")
        else:
            for pr in approved:
                st.markdown(f"✅ **{pr.param_name}** = {pr.value} {pr.unit} (`{pr.mpn}`)")
                st.caption(f"审批人: {pr.reviewer} | 意见: {pr.review_comment}")

            if st.button("💾 落盘到 AMR 数据源"):
                result = manager.save_approved_to_amr()
                if result.get("saved", 0) > 0:
                    st.success(f"已保存 {result['saved']} 条参数到 amr_data.yaml")
                else:
                    st.warning(result.get("message", "没有可保存的参数"))

    with tab3:
        rejected = manager.get_rejected_list()
        if not rejected:
            st.info("没有已拒绝的参数")
        else:
            for pr in rejected:
                st.markdown(f"❌ **{pr.param_name}** = {pr.value} {pr.unit} (`{pr.mpn}`)")
                st.caption(f"审批人: {pr.reviewer} | 理由: {pr.review_comment}")

# ============================================================
# 辅助函数
# ============================================================

def _generate_markdown_report(result: dict) -> str:
    """生成 Markdown 格式的审查报告"""
    lines = [
        "# 硬件原理图审查报告",
        f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"任务类型: {result.get('task_type', 'N/A')}",
        f"工具调用次数: {result.get('tool_call_count', 0)}",
        "\n---\n",
    ]

    violations = result.get("violations", [])
    lines.append(f"## 违规项汇总 (共 {len(violations)} 项)\n")

    for v in violations:
        lines.append(f"### {v.get('rule_name', 'Unknown')}")
        lines.append(f"- **规则 ID**: `{v.get('rule_id', 'N/A')}`")
        lines.append(f"- **严重级别**: {v.get('severity', 'N/A')}")
        lines.append(f"- **器件**: `{v.get('refdes', 'N/A')}`")
        lines.append(f"- **网络**: `{v.get('net_name', 'N/A')}`")
        lines.append(f"- **描述**: {v.get('description', '')}")
        lines.append(f"- **期望**: {v.get('expected', '')}")
        lines.append(f"- **实际**: {v.get('actual', '')}")
        lines.append("")

    lines.append("---\n")
    lines.append("*报告由硬件 AI 专家系统自动生成*")

    return "\n".join(lines)

# ============================================================
# 主路由
# ============================================================

if page == "💬 智能对话":
    render_chat()
elif page == "📋 审查报告":
    render_review_report()
elif page == "✅ HITL 审批":
    render_hitl()
elif page == "📄 Datasheet 审批":
    render_datasheet_hitl()
elif page == "📊 系统状态":
    render_system_status()
