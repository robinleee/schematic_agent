"""
HITL 审批面板 — 白名单管理 + 违规审批

独立页面，从 app.py 多页面导航进入。
"""

from __future__ import annotations

import os
import streamlit as st

from dotenv import load_dotenv

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from agent_system.hitl_workflow import HITLManager, PendingReview
from agent_system.review_engine.whitelist import WhitelistManager
from agent_system.schemas import WhitelistEntry


# ============================================================
# Neo4j 驱动（会话级单例）
# ============================================================

def _get_neo4j_driver():
    """获取或创建 Neo4j 驱动"""
    if "hitl_neo4j_driver" not in st.session_state:
        if GraphDatabase is None:
            st.error("neo4j 驱动未安装")
            return None
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "SecretPassword123")
        st.session_state.hitl_neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
    return st.session_state.hitl_neo4j_driver


def _get_hitl_manager() -> HITLManager:
    """获取或创建 HITLManager"""
    if "hitl_manager" not in st.session_state:
        manager = HITLManager()
        # 从 Neo4j 加载已有 pending reviews
        try:
            driver = _get_neo4j_driver()
            if driver:
                with driver.session() as session:
                    results = list(session.run("""
                        MATCH (pr:PendingReview)
                        RETURN pr.review_id AS review_id,
                               pr.rule_id AS rule_id,
                               pr.rule_name AS rule_name,
                               pr.refdes AS refdes,
                               pr.net_name AS net_name,
                               pr.description AS description,
                               pr.severity AS severity,
                               pr.expected AS expected,
                               pr.actual AS actual,
                               pr.suggested_fix AS suggested_fix,
                               pr.status AS status,
                               pr.reviewer AS reviewer,
                               pr.review_comment AS review_comment,
                               pr.source AS source,
                               pr.created_at AS created_at
                    """))
                for r in results:
                    pr = PendingReview(
                        review_id=r["review_id"] or "",
                        rule_id=r["rule_id"] or "",
                        rule_name=r["rule_name"] or "",
                        refdes=r["refdes"] or "",
                        net_name=r["net_name"] or "",
                        description=r["description"] or "",
                        severity=r["severity"] or "WARNING",
                        expected=r["expected"] or "",
                        actual=r["actual"] or "",
                        suggested_fix=r["suggested_fix"] or "",
                        status=r["status"] or "pending",
                        reviewer=r["reviewer"] or "",
                        review_comment=r["review_comment"] or "",
                        source=r["source"] or "agent",
                        created_at=str(r["created_at"]) if r["created_at"] else "",
                    )
                    manager._pending.append(pr)
        except Exception as e:
            st.warning(f"加载审批记录失败: {e}")
        st.session_state.hitl_manager = manager
    return st.session_state.hitl_manager


def _get_whitelist_manager() -> WhitelistManager:
    """获取或创建 WhitelistManager"""
    if "hitl_wl_manager" not in st.session_state:
        driver = _get_neo4j_driver()
        if driver is None:
            return None
        wl = WhitelistManager(driver)
        try:
            wl.load()
        except Exception as e:
            st.warning(f"加载白名单失败: {e}")
        st.session_state.hitl_wl_manager = wl
    return st.session_state.hitl_wl_manager


# ============================================================
# 页面主体
# ============================================================

# set_page_config removed — in st.navigation mode, only main app sets page config

# 主题 CSS（与主 app.py 暗色主题一致）
st.markdown("""
<style>
:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-card: #1c2333;
    --bg-input: #0d1117;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent: #58a6ff;
    --success: #3fb950;
    --warning: #d29922;
    --error: #f85149;
    --border: #30363d;
}
.stApp { background: var(--bg-primary); color: var(--text-primary); }
.main-header { font-size:1.5rem; font-weight:700; margin-bottom:0.25rem; }
.header-line { height:2px; background:linear-gradient(90deg,var(--accent),var(--success)); border-radius:1px; margin-bottom:1rem; }
.section-label { font-size:1.05rem; font-weight:600; color:var(--accent); margin:1rem 0 0.5rem; }
.wl-card { background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.violation-card { background:var(--bg-card); border-left:3px solid var(--warning); border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.violation-card.ERROR { border-left-color: var(--error); }
.violation-card.WARNING { border-left-color: var(--warning); }
.violation-card.INFO { border-left-color: var(--accent); }
.severity-badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:600; }
.severity-badge.ERROR { background:rgba(248,81,73,0.15); color:var(--error); }
.severity-badge.WARNING { background:rgba(210,153,34,0.15); color:var(--warning); }
.severity-badge.INFO { background:rgba(88,166,255,0.15); color:var(--accent); }
.dash-card { background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:12px; text-align:center; }
.dash-card .value { font-size:1.8rem; font-weight:700; }
.dash-card .label { font-size:0.8rem; color:var(--text-secondary); }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='main-header'>✅ HITL 审批面板</div>", unsafe_allow_html=True)
st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)

hitl = _get_hitl_manager()
wl = _get_whitelist_manager()

# ============================================================
# 统计卡片
# ============================================================

stats = hitl.get_stats()
wl_count = wl.count() if wl else 0

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--warning)'>{stats['pending']}</div><div class='label'>待审批</div></div>", unsafe_allow_html=True)
with c2:
    st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--success)'>{stats['approved']}</div><div class='label'>已批准</div></div>", unsafe_allow_html=True)
with c3:
    st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--error)'>{stats['rejected']}</div><div class='label'>已拒绝</div></div>", unsafe_allow_html=True)
with c4:
    st.markdown(f"<div class='dash-card'><div class='value'>{stats['persisted']}</div><div class='label'>已落盘</div></div>", unsafe_allow_html=True)
with c5:
    st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--accent)'>{wl_count}</div><div class='label'>白名单</div></div>", unsafe_allow_html=True)

st.markdown("---")

# ============================================================
# Tab 布局
# ============================================================

tab_wl, tab_pending, tab_done = st.tabs(["📋 白名单管理", "⏳ 待审批违规", "✅ 审批历史"])

# ============================================================
# Tab 1: 白名单管理
# ============================================================

with tab_wl:
    st.markdown("<div class='section-label'>当前白名单</div>", unsafe_allow_html=True)

    if wl is None:
        st.error("Neo4j 驱动不可用，无法管理白名单")
    else:
        # --- 添加白名单表单 ---
        with st.expander("➕ 添加白名单条目", expanded=False):
            with st.form("add_whitelist_form"):
                a_rule = st.text_input("规则 ID (rule_id)", placeholder="例: R001_decoupling_cap")
                a_refdes = st.text_input("组件名 (refdes)", placeholder="例: C100")
                a_reason = st.text_input("豁免原因", placeholder="可选")
                a_submitted = st.form_submit_button("添加", use_container_width=True)
                if a_submitted:
                    if not a_rule or not a_refdes:
                        st.error("规则 ID 和组件名不能为空")
                    else:
                        entry = WhitelistEntry(
                            rule_id=a_rule.strip(),
                            refdes=a_refdes.strip(),
                            status="IGNORE",
                            reason=a_reason.strip(),
                            added_by="engineer",
                        )
                        if wl.add(entry):
                            st.success(f"已添加: {a_rule} / {a_refdes}")
                            st.rerun()
                        else:
                            st.error("添加失败")

        # --- 白名单列表 ---
        all_wl = wl.list_all()
        if not all_wl:
            st.info("白名单为空")
        else:
            for entry in all_wl:
                with st.container():
                    col_info, col_del = st.columns([5, 1])
                    with col_info:
                        st.markdown(f"""
                        <div class='wl-card'>
                            <div style='display:flex;align-items:center;gap:8px;'>
                                <code style='color:var(--accent)'>{entry.rule_id}</code>
                                <span style='color:var(--text-muted)'>/</span>
                                <code>{entry.refdes}</code>
                                <span style='color:var(--text-secondary);font-size:0.8rem;margin-left:auto;'>{entry.added_by} · {entry.added_at[:19] if entry.added_at else ""}</span>
                            </div>
                            {f'<div style="font-size:0.85rem;color:var(--text-secondary);margin-top:4px;">{entry.reason}</div>' if entry.reason else ""}
                        </div>
                        """, unsafe_allow_html=True)
                    with col_del:
                        if st.button("🗑️", key=f"del_wl_{entry.rule_id}_{entry.refdes}", help="删除此白名单条目"):
                            if wl.remove(entry.rule_id, entry.refdes):
                                st.success("已删除")
                                st.rerun()
                            else:
                                st.error("删除失败")

# ============================================================
# Tab 2: 待审批违规
# ============================================================

with tab_pending:
    pending_list = hitl.get_pending_list("pending")

    # 筛选
    if pending_list:
        all_rule_names = sorted(set(pr.rule_name for pr in pending_list))
        all_severities = sorted(set(pr.severity for pr in pending_list))

        fcol1, fcol2 = st.columns(2)
        with fcol1:
            filter_rule = st.selectbox("规则类型", ["全部"] + all_rule_names, key="filter_rule")
        with fcol2:
            filter_sev = st.selectbox("严重程度", ["全部"] + all_severities, key="filter_sev")

        filtered = pending_list
        if filter_rule != "全部":
            filtered = [pr for pr in filtered if pr.rule_name == filter_rule]
        if filter_sev != "全部":
            filtered = [pr for pr in filtered if pr.severity == filter_sev]

        st.markdown(f"<div class='section-label'>共 {len(filtered)} 条待审批违规</div>", unsafe_allow_html=True)
    else:
        filtered = []

    if not pending_list:
        st.info("没有待审批违规项")
    elif not filtered:
        st.info("筛选后无匹配项")
    else:
        for pr in filtered:
            sev_class = pr.severity if pr.severity in ("ERROR", "WARNING", "INFO") else "WARNING"
            with st.container():
                st.markdown(f"""
                <div class='violation-card {sev_class}'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:6px;'>
                        <span class='severity-badge {pr.severity}'>{pr.severity}</span>
                        <strong>{pr.rule_name}</strong>
                        <span style='color:var(--text-muted);font-size:0.8rem;'>({pr.rule_id})</span>
                    </div>
                    <div style='display:grid;grid-template-columns:80px 1fr;gap:2px 12px;font-size:0.85rem;color:var(--text-secondary);'>
                        <span>器件</span><code>{pr.refdes}</code>
                        <span>网络</span><code>{pr.net_name}</code>
                        <span>描述</span><span style='color:var(--text-primary)'>{pr.description}</span>
                        {f"<span>期望</span><code>{pr.expected}</code>" if pr.expected else ""}
                        {f"<span>实际</span><code>{pr.actual}</code>" if pr.actual else ""}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                bcol1, bcol2, bcol3 = st.columns(3)
                with bcol1:
                    if st.button("✅ 审批通过", key=f"approve_{pr.review_id}", use_container_width=True):
                        hitl.approve(pr.review_id, reviewer="engineer", comment="确认问题")
                        # 同时加入白名单
                        if wl:
                            wl.add(WhitelistEntry(
                                rule_id=pr.rule_id,
                                refdes=pr.refdes,
                                status="IGNORE",
                                reason=pr.description[:200] if pr.description else "",
                                added_by="engineer",
                            ))
                        st.success("已审批通过并加入白名单")
                        st.rerun()
                with bcol2:
                    if st.button("🚫 忽略", key=f"reject_{pr.review_id}", use_container_width=True):
                        hitl.reject(pr.review_id, reviewer="engineer", comment="忽略")
                        st.warning("已忽略")
                        st.rerun()
                with bcol3:
                    if st.button("📋 加入白名单", key=f"to_wl_{pr.review_id}", use_container_width=True, help="仅加入白名单，不改变审批状态"):
                        if wl:
                            wl.add(WhitelistEntry(
                                rule_id=pr.rule_id,
                                refdes=pr.refdes,
                                status="IGNORE",
                                reason=pr.description[:200] if pr.description else "",
                                added_by="engineer",
                            ))
                            st.success("已加入白名单")
                            st.rerun()
                        else:
                            st.error("白名单管理器不可用")
                st.markdown("---")

# ============================================================
# Tab 3: 审批历史
# ============================================================

with tab_done:
    approved_list = hitl.get_pending_list("approved")
    rejected_list = hitl.get_pending_list("rejected")
    persisted_list = hitl.get_pending_list("persisted")

    hcol1, hcol2 = st.columns(2)

    with hcol1:
        st.markdown("<div class='section-label'>✅ 已批准</div>", unsafe_allow_html=True)
        if not approved_list:
            st.info("无")
        else:
            for pr in approved_list:
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--success);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='severity-badge' style='background:rgba(63,185,80,0.15);color:var(--success);'>已批准</span>
                        <strong>{pr.rule_name}</strong>
                        <code>{pr.refdes}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 意见: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    with hcol2:
        st.markdown("<div class='section-label'>❌ 已拒绝/忽略</div>", unsafe_allow_html=True)
        if not rejected_list:
            st.info("无")
        else:
            for pr in rejected_list:
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--error);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='severity-badge' style='background:rgba(248,81,73,0.15);color:var(--error);'>已拒绝</span>
                        <strong>{pr.rule_name}</strong>
                        <code>{pr.refdes}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 理由: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    # 落盘按钮
    if approved_list:
        st.markdown("---")
        if st.button("💾 将已批准项落盘为规则", type="primary", use_container_width=True):
            result = hitl.save_approved_rules()
            if result.get("saved", 0) > 0:
                st.success(f"已保存 {result['saved']} 条规则到 custom_rules.yaml")
                st.rerun()
            else:
                st.warning(result.get("message", "没有可保存的规则"))
