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
# Theme Management
# ============================================================

if "theme" not in st.session_state:
    st.session_state.theme = "dark"

# ============================================================
# CSS 样式 — Global Theme System
# ============================================================

def _get_theme_css(theme: str) -> str:
    """Generate CSS with theme-aware CSS variables."""
    if theme == "dark":
        colors = """
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-card: #1c2333;
            --bg-card-hover: #242d3d;
            --bg-input: #0d1117;
            --bg-sidebar: #0d1117;
            --border-color: #30363d;
            --border-accent: #1a237e;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent-primary: #1a237e;
            --accent-cyan: #00bcd4;
            --accent-cyan-dim: rgba(0,188,212,0.15);
            --success: #2ea043;
            --success-bg: rgba(46,160,67,0.12);
            --warning: #d29922;
            --warning-bg: rgba(210,153,34,0.12);
            --error: #f85149;
            --error-bg: rgba(248,81,73,0.12);
            --info: #58a6ff;
            --info-bg: rgba(88,166,255,0.12);
            --shadow: 0 2px 8px rgba(0,0,0,0.3);
            --shadow-hover: 0 4px 16px rgba(0,0,0,0.4);
            --gradient-hero: linear-gradient(135deg, #1a237e 0%, #00bcd4 100%);
        """
    else:
        colors = """
            --bg-primary: #ffffff;
            --bg-secondary: #f6f8fa;
            --bg-card: #ffffff;
            --bg-card-hover: #f3f4f6;
            --bg-input: #ffffff;
            --bg-sidebar: #f6f8fa;
            --border-color: #d0d7de;
            --border-accent: #1a237e;
            --text-primary: #1f2328;
            --text-secondary: #656d76;
            --text-muted: #8b949e;
            --accent-primary: #1a237e;
            --accent-cyan: #0097a7;
            --accent-cyan-dim: rgba(0,151,167,0.08);
            --success: #1a7f37;
            --success-bg: rgba(26,127,55,0.08);
            --warning: #9a6700;
            --warning-bg: rgba(154,103,0,0.08);
            --error: #cf222e;
            --error-bg: rgba(207,34,46,0.08);
            --info: #0969da;
            --info-bg: rgba(9,105,218,0.08);
            --shadow: 0 1px 4px rgba(0,0,0,0.08);
            --shadow-hover: 0 4px 12px rgba(0,0,0,0.12);
            --gradient-hero: linear-gradient(135deg, #1a237e 0%, #00bcd4 100%);
        """

    return f"""
    <style>
    :root {{
        {colors}
        --radius-sm: 6px;
        --radius-md: 10px;
        --radius-lg: 14px;
        --spacing-xs: 4px;
        --spacing-sm: 8px;
        --spacing-md: 16px;
        --spacing-lg: 24px;
        --spacing-xl: 32px;
        --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
        --transition-fast: 0.15s ease;
        --transition-normal: 0.25s ease;
    }}

    /* ---- Global Body ---- */
    .stApp {{
        background-color: var(--bg-primary) !important;
        color: var(--text-primary) !important;
        font-family: var(--font-sans) !important;
    }}

    /* ---- Sidebar ---- */
    [data-testid="stSidebar"] {{
        background-color: var(--bg-sidebar) !important;
        border-right: 1px solid var(--border-color) !important;
    }}
    [data-testid="stSidebar"] .stMarkdown {{ color: var(--text-primary) !important; }}

    /* ---- Navigation Items ---- */
    [data-testid="stSidebarNav"] button {{
        color: var(--text-secondary) !important;
        border-radius: var(--radius-sm) !important;
        transition: all var(--transition-fast) !important;
        margin: 2px 0 !important;
    }}
    [data-testid="stSidebarNav"] button:hover {{
        background-color: var(--accent-cyan-dim) !important;
        color: var(--accent-cyan) !important;
    }}
    [data-testid="stSidebarNav"] button[data-baseweb="button"][aria-checked="true"],
    [data-testid="stSidebarNav"] button:focus-within {{
        background-color: var(--accent-cyan-dim) !important;
        color: var(--accent-cyan) !important;
        border-left: 3px solid var(--accent-cyan) !important;
    }}

    /* ---- Main Header ---- */
    .main-header {{
        font-size: 1.75rem;
        font-weight: 700;
        background: var(--gradient-hero);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }}

    /* ---- Cards ---- */
    .metric-card {{
        background-color: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: var(--spacing-md);
        box-shadow: var(--shadow);
        transition: all var(--transition-normal);
    }}
    .metric-card:hover {{
        box-shadow: var(--shadow-hover);
        border-color: var(--accent-cyan);
        transform: translateY(-2px);
    }}

    .stat-card {{
        background-color: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: var(--spacing-md);
        text-align: center;
        box-shadow: var(--shadow);
        transition: all var(--transition-normal);
    }}
    .stat-card:hover {{
        box-shadow: var(--shadow-hover);
        transform: translateY(-2px);
    }}
    .stat-number {{
        font-size: 2rem;
        font-weight: 700;
        color: var(--accent-cyan);
        line-height: 1.2;
    }}
    .stat-label {{
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-top: var(--spacing-xs);
    }}

    /* ---- Status Indicators ---- */
    .status-online {{ color: var(--success); font-weight: 600; }}
    .status-offline {{ color: var(--error); font-weight: 600; }}
    .status-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
        animation: pulse-dot 2s infinite;
    }}
    .status-dot.online {{ background-color: var(--success); box-shadow: 0 0 6px var(--success); }}
    .status-dot.offline {{ background-color: var(--error); box-shadow: 0 0 6px var(--error); animation: none; }}
    @keyframes pulse-dot {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0.5; }}
    }}

    /* ---- Violation Severity ---- */
    .violation-error {{ color: var(--error); font-weight: 600; }}
    .violation-warning {{ color: var(--warning); font-weight: 600; }}
    .violation-info {{ color: var(--info); }}

    /* ---- Chat Messages ---- */
    .chat-user {{
        background: linear-gradient(135deg, rgba(26,35,126,0.15), rgba(0,188,212,0.08));
        border: 1px solid rgba(0,188,212,0.2);
        border-radius: var(--radius-md);
        padding: 12px 16px;
        margin: 8px 0;
    }}
    .chat-assistant {{
        background-color: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: 12px 16px;
        margin: 8px 0;
    }}

    /* ---- Streamlit Components Override ---- */
    /* Buttons */
    .stButton > button {{
        border-radius: var(--radius-sm) !important;
        transition: all var(--transition-fast) !important;
        border: 1px solid var(--border-color) !important;
        font-weight: 500 !important;
    }}
    .stButton > button:hover {{
        border-color: var(--accent-cyan) !important;
        box-shadow: 0 0 0 1px var(--accent-cyan) !important;
    }}
    .stButton > button[kind="primary"] {{
        background: var(--gradient-hero) !important;
        border: none !important;
        color: white !important;
    }}
    .stButton > button[kind="primary"]:hover {{
        opacity: 0.9;
        box-shadow: 0 0 12px rgba(0,188,212,0.3) !important;
    }}

    /* Inputs & Text Areas */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stNumberInput > div > div > input {{
        background-color: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border-color: var(--border-color) !important;
        border-radius: var(--radius-sm) !important;
        transition: border-color var(--transition-fast) !important;
    }}
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {{
        border-color: var(--accent-cyan) !important;
        box-shadow: 0 0 0 1px var(--accent-cyan) !important;
    }}

    /* Selectbox */
    .stSelectbox > div > div {{
        background-color: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        background-color: var(--bg-secondary) !important;
        border-radius: var(--radius-md) !important;
        padding: 4px !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: var(--radius-sm) !important;
        color: var(--text-secondary) !important;
        transition: all var(--transition-fast) !important;
        padding: 8px 16px !important;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        color: var(--text-primary) !important;
        background-color: var(--accent-cyan-dim) !important;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: var(--accent-cyan-dim) !important;
        color: var(--accent-cyan) !important;
        font-weight: 600 !important;
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: var(--radius-sm) !important;
        transition: all var(--transition-fast) !important;
    }}
    .streamlit-expanderHeader:hover {{
        border-color: var(--accent-cyan) !important;
    }}
    .streamlit-expanderContent {{
        border-left: 3px solid var(--accent-cyan) !important;
        padding-left: 16px !important;
        background-color: var(--bg-secondary) !important;
        border-radius: 0 0 var(--radius-sm) var(--radius-sm) !important;
    }}

    /* Metric */
    [data-testid="stMetricValue"] {{
        color: var(--accent-cyan) !important;
        font-weight: 700 !important;
        font-size: 1.75rem !important;
    }}
    [data-testid="stMetricLabel"] {{
        color: var(--text-secondary) !important;
        font-size: 0.85rem !important;
    }}
    [data-testid="stMetricDelta"] {{
        font-size: 0.8rem !important;
    }}

    /* Chat Input */
    [data-testid="stChatInput"] {{
        border-radius: var(--radius-md) !important;
    }}
    [data-testid="stChatInput"] textarea {{
        background-color: var(--bg-card) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: var(--radius-md) !important;
    }}

    /* File Uploader */
    [data-testid="stFileUploader"] {{
        border: 2px dashed var(--border-color) !important;
        border-radius: var(--radius-md) !important;
        background-color: var(--bg-card) !important;
        transition: border-color var(--transition-fast) !important;
    }}
    [data-testid="stFileUploader"]:hover {{
        border-color: var(--accent-cyan) !important;
    }}

    /* Slider */
    .stSlider > div > div > div > div {{
        background-color: var(--accent-cyan) !important;
    }}

    /* Checkbox */
    .stCheckbox {{
        color: var(--text-primary) !important;
    }}

    /* Spinner */
    .stSpinner {{
        color: var(--accent-cyan) !important;
    }}

    /* Success / Error / Warning / Info boxes */
    [data-testid="stSuccess"] {{
        background-color: var(--success-bg) !important;
        border-left: 4px solid var(--success) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }}
    [data-testid="stError"] {{
        background-color: var(--error-bg) !important;
        border-left: 4px solid var(--error) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }}
    [data-testid="stWarning"] {{
        background-color: var(--warning-bg) !important;
        border-left: 4px solid var(--warning) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }}
    [data-testid="stInfo"] {{
        background-color: var(--info-bg) !important;
        border-left: 4px solid var(--info) !important;
        color: var(--text-primary) !important;
        border-radius: var(--radius-sm) !important;
    }}

    /* Download Button */
    .stDownloadButton > button {{
        background: var(--gradient-hero) !important;
        border: none !important;
        color: white !important;
        border-radius: var(--radius-sm) !important;
    }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 8px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg-secondary); }}
    ::-webkit-scrollbar-thumb {{
        background: var(--border-color);
        border-radius: 4px;
    }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--text-muted); }}

    /* Divider */
    hr {{
        border-color: var(--border-color) !important;
    }}

    /* Caption */
    .stCaption {{
        color: var(--text-muted) !important;
    }}

    /* Headings */
    h3 {{
        color: var(--text-primary) !important;
        border-bottom: 1px solid var(--border-color);
        padding-bottom: 8px;
    }}

    /* Code blocks */
    code {{
        background-color: var(--bg-secondary) !important;
        color: var(--accent-cyan) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: 4px !important;
        padding: 2px 6px !important;
        font-family: var(--font-mono) !important;
        font-size: 0.85em !important;
    }}
    pre {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: var(--radius-sm) !important;
        font-family: var(--font-mono) !important;
    }}
    pre code {{
        border: none !important;
        padding: 0 !important;
        background: transparent !important;
    }}

    /* ---- Custom Violation Card ---- */
    .violation-card {{
        background-color: var(--bg-card);
        border-radius: var(--radius-md);
        padding: var(--spacing-md);
        margin-bottom: var(--spacing-sm);
        box-shadow: var(--shadow);
        border-left: 4px solid var(--border-color);
        transition: all var(--transition-normal);
    }}
    .violation-card:hover {{
        box-shadow: var(--shadow-hover);
        transform: translateY(-1px);
    }}
    .violation-card.severity-ERROR {{
        border-left-color: var(--error);
    }}
    .violation-card.severity-WARNING {{
        border-left-color: var(--warning);
    }}
    .violation-card.severity-INFO {{
        border-left-color: var(--info);
    }}

    /* ---- Severity Badge ---- */
    .severity-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .severity-badge.ERROR {{
        background-color: var(--error-bg);
        color: var(--error);
        border: 1px solid var(--error);
    }}
    .severity-badge.WARNING {{
        background-color: var(--warning-bg);
        color: var(--warning);
        border: 1px solid var(--warning);
    }}
    .severity-badge.INFO {{
        background-color: var(--info-bg);
        color: var(--info);
        border: 1px solid var(--info);
    }}

    /* ---- Status Badge (for HITL/Knowledge) ---- */
    .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }}
    .status-badge.pending {{
        background-color: var(--warning-bg);
        color: var(--warning);
    }}
    .status-badge.approved, .status-badge.stored {{
        background-color: var(--success-bg);
        color: var(--success);
    }}
    .status-badge.rejected {{
        background-color: var(--error-bg);
        color: var(--error);
    }}
    .status-badge.uploaded {{
        background-color: var(--info-bg);
        color: var(--info);
    }}
    .status-badge.processing {{
        background-color: var(--warning-bg);
        color: var(--warning);
    }}
    .status-badge.pending_review {{
        background-color: var(--warning-bg);
        color: var(--warning);
    }}

    /* ---- Filter Badge ---- */
    .filter-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--transition-fast);
        border: 1px solid var(--border-color);
        background-color: var(--bg-card);
        color: var(--text-secondary);
    }}
    .filter-badge.active {{
        border-color: var(--accent-cyan);
        background-color: var(--accent-cyan-dim);
        color: var(--accent-cyan);
    }}
    .filter-badge:hover {{
        border-color: var(--accent-cyan);
    }}

    /* ---- Dashboard Card Grid ---- */
    .dash-card {{
        background-color: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: var(--spacing-md);
        box-shadow: var(--shadow);
        transition: all var(--transition-normal);
        text-align: center;
    }}
    .dash-card:hover {{
        box-shadow: var(--shadow-hover);
        transform: translateY(-2px);
        border-color: var(--accent-cyan);
    }}
    .dash-card .value {{
        font-size: 2rem;
        font-weight: 700;
        color: var(--accent-cyan);
        line-height: 1.2;
    }}
    .dash-card .label {{
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-top: 4px;
    }}

    /* ---- Progress Bar ---- */
    .theme-progress {{
        height: 6px;
        border-radius: 3px;
        background-color: var(--bg-secondary);
        overflow: hidden;
        margin-top: 8px;
    }}
    .theme-progress .bar {{
        height: 100%;
        border-radius: 3px;
        transition: width var(--transition-normal);
    }}
    .theme-progress .bar.success {{ background-color: var(--success); }}
    .theme-progress .bar.warning {{ background-color: var(--warning); }}
    .theme-progress .bar.error {{ background-color: var(--error); }}
    .theme-progress .bar.info {{ background-color: var(--info); }}

    /* ---- Action Buttons ---- */
    .action-btn {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 16px;
        border-radius: var(--radius-sm);
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: all var(--transition-fast);
        border: 1px solid;
    }}
    .action-btn.approve {{
        background-color: var(--success-bg);
        color: var(--success);
        border-color: var(--success);
    }}
    .action-btn.approve:hover {{
        background-color: var(--success);
        color: white;
    }}
    .action-btn.reject {{
        background-color: var(--error-bg);
        color: var(--error);
        border-color: var(--error);
    }}
    .action-btn.reject:hover {{
        background-color: var(--error);
        color: white;
    }}
    .action-btn.modify {{
        background-color: var(--info-bg);
        color: var(--info);
        border-color: var(--info);
    }}
    .action-btn.modify:hover {{
        background-color: var(--info);
        color: white;
    }}

    /* ---- Typing Indicator ---- */
    .typing-indicator {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 8px 16px;
    }}
    .typing-indicator .dot {{
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background-color: var(--accent-cyan);
        animation: typing-bounce 1.4s infinite ease-in-out;
    }}
    .typing-indicator .dot:nth-child(1) {{ animation-delay: 0s; }}
    .typing-indicator .dot:nth-child(2) {{ animation-delay: 0.2s; }}
    .typing-indicator .dot:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes typing-bounce {{
        0%, 60%, 100% {{ transform: translateY(0); opacity: 0.4; }}
        30% {{ transform: translateY(-6px); opacity: 1; }}
    }}

    /* ---- Copy Button ---- */
    .copy-btn {{
        position: absolute;
        top: 6px;
        right: 6px;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.7rem;
        color: var(--text-muted);
        cursor: pointer;
        opacity: 0;
        transition: opacity var(--transition-fast);
    }}
    .copy-btn:hover {{
        color: var(--accent-cyan);
        border-color: var(--accent-cyan);
    }}
    .chat-msg-wrapper:hover .copy-btn {{
        opacity: 1;
    }}

    /* ---- Health Bar ---- */
    .health-bar {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 6px 0;
    }}
    .health-bar .label {{
        font-size: 0.8rem;
        color: var(--text-secondary);
        min-width: 80px;
    }}
    .health-bar .track {{
        flex: 1;
        height: 8px;
        background-color: var(--bg-secondary);
        border-radius: 4px;
        overflow: hidden;
    }}
    .health-bar .fill {{
        height: 100%;
        border-radius: 4px;
        transition: width 0.6s ease;
    }}

    /* ---- Quality pass/fail ---- */
    .quality-pass {{ color: var(--success); font-weight: bold; }}
    .quality-fail {{ color: var(--error); font-weight: bold; }}

    /* ---- Page Header Gradient Line ---- */
    .header-line {{
        height: 3px;
        background: var(--gradient-hero);
        border-radius: 2px;
        margin-bottom: var(--spacing-md);
    }}

    /* ---- Chart Container ---- */
    .chart-container {{
        background-color: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        padding: var(--spacing-md);
    }}

    /* ---- Section Label ---- */
    .section-label {{
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--accent-cyan);
        margin-bottom: var(--spacing-sm);
    }}
    </style>
    """


st.markdown(_get_theme_css(st.session_state.theme), unsafe_allow_html=True)

# ============================================================
# Session State 初始化
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    from agent_system.react_agent import ReActAgent
    st.session_state.agent = ReActAgent()

if "review_results" not in st.session_state:
    st.session_state.review_results = None

if "hitl_manager" not in st.session_state:
    st.session_state.hitl_manager = HITLManager()

if "datasheet_hitl" not in st.session_state:
    st.session_state.datasheet_hitl = DatasheetHITLManager()

# ============================================================
# 页面定义（用于 st.navigation）
# ============================================================

# 快速操作页面（在侧边栏显示）
def render_quick_actions():
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

def render_trace_timeline(trace: list):
    """优化后的 ReAct 推理链路展示：时间线布局 + 折叠面板 + 步骤图标 + 耗时 + 错误高亮"""
    if not trace:
        return

    # 步骤类型判定与图标映射
    def _step_info(step):
        action = step.get("action", "")
        thought = step.get("thought", "")
        obs = step.get("observation", "")
        is_error = any(kw in obs.lower() for kw in ["error", "失败", "异常", "exception", "traceback"])
        is_final = action == "final_answer"

        if is_final:
            icon, label, color = "✅", "结论", "var(--accent-green, #4caf50)"
        elif is_error:
            icon, label, color = "⚠️", "异常", "#ef5350"
        else:
            # 根据内容判断类型
            if thought and not action:
                icon, label, color = "💭", "思考", "var(--accent-cyan, #00bcd4)"
            elif action and not obs:
                icon, label, color = "🔧", "执行", "var(--accent-amber, #ffab40)"
            else:
                icon, label, color = "📋", "观察", "var(--text-secondary, #aaa)"

        # 摘要：动作名称 + 简短描述
        if is_final:
            summary = "得出最终结论"
        elif action and action != "final_answer":
            summary = f"{action}({', '.join(f'{k}={v}' for k, v in list(step.get('action_input', {}).items())[:2])})"
            if len(summary) > 50:
                summary = summary[:47] + "...)"
        elif thought:
            summary = thought[:50] + ("..." if len(thought) > 50 else "")
        else:
            summary = "—"

        # 耗时
        ts = step.get("timestamp", "")
        duration = ""
        return icon, label, color, summary, is_error, ts, duration

    # 计算每步耗时
    timestamps = [s.get("timestamp", "") for s in trace if s.get("timestamp")]
    durations = [""] * len(trace)
    if len(timestamps) == len(trace):
        from datetime import datetime as _dt
        try:
            parsed = [_dt.fromisoformat(t) for t in timestamps]
            for i in range(1, len(parsed)):
                delta = (parsed[i] - parsed[i - 1]).total_seconds()
                if delta < 1:
                    durations[i] = f"{delta * 1000:.0f}ms"
                else:
                    durations[i] = f"{delta:.1f}s"
        except Exception:
            pass

    # 渲染时间线
    st.markdown("""
    <style>
    .trace-timeline {{ position: relative; padding-left: 24px; }}
    .trace-timeline::before {{
        content: ''; position: absolute; left: 8px; top: 0; bottom: 0;
        width: 2px; background: var(--border-color, #333);
    }}
    .trace-step {{ position: relative; margin-bottom: 4px; }}
    .trace-step::before {{
        content: ''; position: absolute; left: -20px; top: 8px;
        width: 10px; height: 10px; border-radius: 50%;
        background: var(--accent-cyan, #00bcd4); border: 2px solid var(--bg-primary, #1a1a2e);
    }}
    .trace-step.step-error::before {{ background: #ef5350; }}
    .trace-step.step-final::before {{ background: var(--accent-green, #4caf50); }}
    </style>
    """, unsafe_allow_html=True)

    for idx, step in enumerate(trace):
        icon, label, color, summary, is_error, ts, _ = _step_info(step)
        duration = durations[idx] if idx < len(durations) else ""
        is_final = step.get("action") == "final_answer"

        step_css = "trace-step"
        if is_error:
            step_css += " step-error"
        elif is_final:
            step_css += " step-final"

        # 折叠面板标题
        title_parts = [f"{icon} Step {step.get('step_id', idx + 1)}: {summary}"]
        if duration:
            title_parts.append(f"⏱ {duration}")
        title = " ".join(title_parts)

        with st.expander(title):
            # Thought
            if step.get("thought"):
                st.markdown(f"<div style='color:var(--accent-cyan,#00bcd4);font-size:0.85rem;'><strong>💭 思考</strong></div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:0.85rem;margin:2px 0 8px 4px;'>{step['thought']}</div>", unsafe_allow_html=True)

            # Action
            if step.get("action") and step["action"] != "final_answer":
                st.markdown(f"<div style='color:var(--accent-amber,#ffab40);font-size:0.85rem;'><strong>🔧 执行</strong></div>", unsafe_allow_html=True)
                action_str = f"{step['action']}({json.dumps(step.get('action_input', {}), ensure_ascii=False)})"
                st.code(action_str, language="python")

            # Observation
            if step.get("observation"):
                obs_label = "⚠️ 异常结果" if is_error else "📋 观察结果"
                obs_color = "#ef5350" if is_error else "var(--text-secondary,#aaa)"
                st.markdown(f"<div style='color:{obs_color};font-size:0.85rem;'><strong>{obs_label}</strong></div>", unsafe_allow_html=True)
                obs_text = step["observation"]
                # 长文本用 code 块展示
                if len(obs_text) > 200:
                    st.code(obs_text[:1000], language=None)
                else:
                    st.markdown(f"<div style='font-size:0.8rem;white-space:pre-wrap;'>{obs_text}</div>", unsafe_allow_html=True)

            # Final answer
            if step.get("action") == "final_answer" and step.get("action_input", {}).get("final_answer"):
                st.markdown(f"<div style='color:var(--accent-green,#4caf50);font-size:0.85rem;'><strong>✅ 最终结论</strong></div>", unsafe_allow_html=True)
                st.markdown(step["action_input"]["final_answer"])


def render_chat():
    st.markdown("<div class='main-header'>💬 智能对话</div>", unsafe_allow_html=True)
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown("<span style='color:var(--text-secondary);font-size:0.9rem;'>与硬件 AI 专家对话，支持：审查、诊断、查询 &middot; ReAct 推理模式</span>", unsafe_allow_html=True)

    # 显示历史消息
    for msg in st.session_state.messages:
        role = msg["role"]
        if role == "user":
            with st.chat_message("user", avatar="🧑‍💻"):
                st.markdown(f"""
                <div class='chat-msg-wrapper' style='position:relative;'>
                    <div class='chat-user'>{msg['content']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            with st.chat_message("assistant", avatar="🤖"):
                # 主回复内容
                st.markdown(msg["content"], unsafe_allow_html=False)

                # 推理过程（优化后时间线展示）
                if msg.get("trace"):
                    render_trace_timeline(msg["trace"])

    # 输入框
    user_input = st.chat_input("输入您的问题...（审查/诊断/查询均可）")

    if user_input:
        # 添加用户消息
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(f"""
            <div class='chat-msg-wrapper' style='position:relative;'>
                <div class='chat-user'>{user_input}</div>
            </div>
            """, unsafe_allow_html=True)

        # 调用 ReAct Agent
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("🤔 思考中..."):
                try:
                    # 使用统一 ReAct Agent
                    result = st.session_state.agent.run(user_input)

                    # 格式化报告
                    report = result.get("report", "")
                    trace = result.get("execution_trace", [])
                    tool_count = result.get("tool_call_count", 0)
                    task_type = result.get("task_type", "")

                    # 任务类型标签
                    task_labels = {"review": "🔍 审查", "diagnosis": "🩺 诊断", "query": "🔎 查询"}
                    task_label = task_labels.get(task_type, "💬")

                    # 显示元信息
                    st.markdown(f"<span style='color:var(--text-muted);font-size:0.8rem;'>{task_label} · {tool_count} 次工具调用 · {len(trace)} 步推理</span>", unsafe_allow_html=True)

                    # 显示报告
                    if report:
                        st.markdown(report)
                    else:
                        st.warning("Agent 未生成报告")

                    # 推理过程（优化后时间线展示）
                    if trace:
                        render_trace_timeline(trace)

                    # 保存到 session
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": report or "无报告",
                        "trace": trace,
                    })

                    # 兼容：如果结果包含 violations，也保存到 review_results
                    violations = result.get("violations", [])
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
    st.markdown("📋 审查报告", unsafe_allow_html=False)

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

    # ============================================================
    # 统计摘要区 — st.metric
    # ============================================================
    error_count = sum(1 for v in violations if v.get("severity") == "ERROR")
    warn_count = sum(1 for v in violations if v.get("severity") == "WARNING")
    info_count = sum(1 for v in violations if v.get("severity") == "INFO")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总违规数", len(violations))
    col2.metric("🔴 CRITICAL", error_count)
    col3.metric("🟠 WARNING", warn_count)
    col4.metric("🔵 INFO", info_count)

    st.divider()

    if not violations:
        st.success("🎉 未发现违规项！设计完全合规。")
        return

    # ============================================================
    # 严重级别分布图
    # ============================================================
    import pandas as pd
    sev_df = pd.DataFrame({
        "级别": ["CRITICAL", "WARNING", "INFO"],
        "数量": [error_count, warn_count, info_count],
    })
    st.bar_chart(sev_df.set_index("级别"), use_container_width=True, height=250)

    # ============================================================
    # 筛选区 — st.selectbox
    # ============================================================
    filter_col1, filter_col2 = st.columns(2)

    # 收集所有规则类型
    all_rule_ids = sorted(set(v.get("rule_id", "Unknown") for v in violations))

    with filter_col1:
        selected_rule = st.selectbox(
            "按规则类型筛选",
            options=["全部"] + all_rule_ids,
            key="review_rule_filter",
        )

    with filter_col2:
        selected_severity = st.selectbox(
            "按严重程度筛选",
            options=["全部", "CRITICAL", "WARNING", "INFO"],
            key="review_severity_filter_select",
        )

    # 应用筛选
    filtered = violations
    if selected_rule != "全部":
        filtered = [v for v in filtered if v.get("rule_id") == selected_rule]
    if selected_severity != "全部":
        # Map CRITICAL -> ERROR for backward compat
        sev_map = {"CRITICAL": "ERROR", "WARNING": "WARNING", "INFO": "INFO"}
        filtered = [v for v in filtered if v.get("severity") == sev_map.get(selected_severity, selected_severity)]

    st.caption(f"显示 **{len(filtered)}** / {len(violations)} 条违规项")

    # ============================================================
    # 按规则类型分组展示
    # ============================================================
    from collections import OrderedDict
    grouped: dict[str, list] = OrderedDict()
    for v in filtered:
        rid = v.get("rule_id", "Unknown")
        grouped.setdefault(rid, []).append(v)

    # Severity display helpers
    SEVERITY_EMOJI = {"ERROR": "🔴", "WARNING": "🟠", "INFO": "🔵"}
    SEVERITY_LABEL = {"ERROR": "CRITICAL", "WARNING": "WARNING", "INFO": "INFO"}

    for rule_id, rule_violations in grouped.items():
        rule_name = rule_violations[0].get("rule_name", rule_id)
        # Count severities in this group
        e = sum(1 for v in rule_violations if v.get("severity") == "ERROR")
        w = sum(1 for v in rule_violations if v.get("severity") == "WARNING")
        inf = sum(1 for v in rule_violations if v.get("severity") == "INFO")
        parts = []
        if e: parts.append(f"🔴 {e}")
        if w: parts.append(f"🟠 {w}")
        if inf: parts.append(f"🔵 {inf}")
        header = f"**{rule_id}** — {rule_name}  ({', '.join(parts)})"

        with st.expander(header, expanded=False):
            for i, v in enumerate(rule_violations, 1):
                severity = v.get("severity", "INFO")
                emoji = SEVERITY_EMOJI.get(severity, "⚪")
                label = SEVERITY_LABEL.get(severity, severity)

                st.markdown(
                    f"{emoji} **{label}** | "
                    f"器件: `{v.get('refdes', 'N/A')}` | "
                    f"网络: `{v.get('net_name', 'N/A')}`"
                )
                st.markdown(f"- **描述:** {v.get('description', '')}")
                st.markdown(f"- **期望:** {v.get('expected', '')}  |  **实际:** {v.get('actual', '')}")

                # 加入 HITL 审批
                if st.button(f"📝 加入 HITL 审批", key=f"hitl_{rule_id}_{i}"):
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

                if i < len(rule_violations):
                    st.divider()

    # ============================================================
    # 规则违规统计图
    # ============================================================
    rule_counts = {}
    for v in violations:
        name = v.get("rule_id", "Unknown")
        rule_counts[name] = rule_counts.get(name, 0) + 1

    if len(rule_counts) > 1:
        st.divider()
        st.markdown("**规则违规统计**")
        rule_df = pd.DataFrame([
            {"规则": k, "次数": v}
            for k, v in sorted(rule_counts.items(), key=lambda x: -x[1])
        ])
        st.bar_chart(rule_df.set_index("规则"), use_container_width=True, height=250)

    # ============================================================
    # 导出按钮
    # ============================================================
    st.divider()
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
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown("<span style='color:var(--text-secondary);font-size:0.9rem;'>工程师审批 Agent 发现的违规项，批准后自动落盘为规则。</span>", unsafe_allow_html=True)

    manager = st.session_state.hitl_manager

    # 统计
    stats = manager.get_stats()
    hcol1, hcol2, hcol3, hcol4 = st.columns(4)
    with hcol1:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--warning)'>{stats['pending']}</div><div class='label'>待审批</div></div>", unsafe_allow_html=True)
    with hcol2:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--success)'>{stats['approved']}</div><div class='label'>已批准</div></div>", unsafe_allow_html=True)
    with hcol3:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--error)'>{stats['rejected']}</div><div class='label'>已拒绝</div></div>", unsafe_allow_html=True)
    with hcol4:
        st.markdown(f"<div class='dash-card'><div class='value'>{stats['persisted']}</div><div class='label'>已落盘</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    # 审批操作
    tab1, tab2, tab3 = st.tabs(["⏳ 待审批", "✅ 已批准", "❌ 已拒绝"])

    with tab1:
        pending = manager.get_pending_list("pending")
        if not pending:
            st.info("没有待审批项")
        else:
            for pr in pending:
                sev_class = {"ERROR": "severity-ERROR", "WARNING": "severity-WARNING", "INFO": "severity-INFO"}.get(pr.severity, "")
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
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    bcol1, bcol2 = st.columns(2)
                    with bcol1:
                        if st.button("✅ 批准", key=f"approve_{pr.review_id}", use_container_width=True):
                            manager.approve(pr.review_id, reviewer="engineer", comment="确认问题")
                            st.success("已批准")
                            st.rerun()
                    with bcol2:
                        if st.button("❌ 拒绝", key=f"reject_{pr.review_id}", use_container_width=True):
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
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--success);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='status-badge approved'>已批准</span>
                        <strong>{pr.rule_name}</strong>
                        <code>{pr.refdes}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 意见: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if st.button("💾 落盘为规则", type="primary"):
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
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--error);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='status-badge rejected'>已拒绝</span>
                        <strong>{pr.rule_name}</strong>
                        <code>{pr.refdes}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 理由: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

# ============================================================
# 页面 4: 系统状态
# ============================================================

def render_system_status():
    st.markdown("<div class='main-header'>📊 系统状态</div>", unsafe_allow_html=True)
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)

    # ---- Service Health Row ----
    st.markdown("<div class='section-label'>服务状态</div>", unsafe_allow_html=True)
    hcol1, hcol2, hcol3 = st.columns(3)

    # Neo4j health
    neo4j_online = False
    neo4j_data = {}
    try:
        from agent_system.graph_tools import _run_cypher
        neo4j_data["nodes"] = _run_cypher("MATCH (n) RETURN count(n) AS cnt")[0]["cnt"]
        neo4j_data["rels"] = _run_cypher("MATCH ()-[r]->() RETURN count(r) AS cnt")[0]["cnt"]
        neo4j_data["components"] = _run_cypher("MATCH (c:Component) RETURN count(c) AS cnt")[0]["cnt"]
        neo4j_data["nets"] = _run_cypher("MATCH (n:Net) RETURN count(n) AS cnt")[0]["cnt"]
        neo4j_online = True
    except Exception:
        pass

    # Ollama health
    ollama_online = False
    ollama_models = []
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            ollama_models = [m["name"] for m in data.get("models", [])]
            ollama_online = True
    except Exception:
        pass

    # ChromaDB health
    chroma_online = False
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8000/api/v1/heartbeat", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            chroma_online = resp.status == 200
    except Exception:
        pass

    with hcol1:
        dot = "online" if neo4j_online else "offline"
        label = "在线" if neo4j_online else "离线"
        st.markdown(f"""
        <div class='dash-card' style='text-align:left;'>
            <div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>
                <span class='status-dot {dot}'></span>
                <span style='font-weight:600;font-size:1.05rem;'>Neo4j</span>
                <span class='status-badge {"approved" if neo4j_online else "rejected"}' style='margin-left:auto;'>{label}</span>
            </div>
            <div style='color:var(--text-secondary);font-size:0.85rem;'>bolt://localhost:7687</div>
        </div>
        """, unsafe_allow_html=True)

    with hcol2:
        dot = "online" if ollama_online else "offline"
        label = "在线" if ollama_online else "离线"
        model_info = f"{len(ollama_models)} 模型" if ollama_online else "不可用"
        st.markdown(f"""
        <div class='dash-card' style='text-align:left;'>
            <div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>
                <span class='status-dot {dot}'></span>
                <span style='font-weight:600;font-size:1.05rem;'>Ollama</span>
                <span class='status-badge {"approved" if ollama_online else "rejected"}' style='margin-left:auto;'>{label}</span>
            </div>
            <div style='color:var(--text-secondary);font-size:0.85rem;'>localhost:11434 &middot; {model_info}</div>
        </div>
        """, unsafe_allow_html=True)

    with hcol3:
        dot = "online" if chroma_online else "offline"
        label = "在线" if chroma_online else "离线"
        st.markdown(f"""
        <div class='dash-card' style='text-align:left;'>
            <div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>
                <span class='status-dot {dot}'></span>
                <span style='font-weight:600;font-size:1.05rem;'>ChromaDB</span>
                <span class='status-badge {"approved" if chroma_online else "rejected"}' style='margin-left:auto;'>{label}</span>
            </div>
            <div style='color:var(--text-secondary);font-size:0.85rem;'>localhost:8000</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ---- Neo4j Stats Grid ----
    st.markdown("<div class='section-label'>Neo4j 图谱统计</div>", unsafe_allow_html=True)

    if neo4j_online:
        ncol1, ncol2, ncol3, ncol4 = st.columns(4)
        with ncol1:
            st.markdown(f"<div class='dash-card'><div class='value'>{neo4j_data['nodes']:,}</div><div class='label'>总节点数</div></div>", unsafe_allow_html=True)
        with ncol2:
            st.markdown(f"<div class='dash-card'><div class='value'>{neo4j_data['rels']:,}</div><div class='label'>关系数</div></div>", unsafe_allow_html=True)
        with ncol3:
            st.markdown(f"<div class='dash-card'><div class='value'>{neo4j_data['components']:,}</div><div class='label'>Component</div></div>", unsafe_allow_html=True)
        with ncol4:
            st.markdown(f"<div class='dash-card'><div class='value'>{neo4j_data['nets']:,}</div><div class='label'>Net</div></div>", unsafe_allow_html=True)

        # Component type distribution chart
        try:
            comp_dist = _run_cypher(
                "MATCH (c:Component) RETURN c.partType AS pt, count(c) AS cnt ORDER BY cnt DESC LIMIT 10"
            )
            if comp_dist:
                import pandas as pd
                df = pd.DataFrame([
                    {"PartType": r["pt"] or "Unknown", "数量": r["cnt"]}
                    for r in comp_dist
                ])
                st.markdown("<div class='section-label'>器件类型分布 (Top 10)</div>", unsafe_allow_html=True)
                st.bar_chart(df.set_index("PartType"), use_container_width=True)
        except Exception:
            pass
    else:
        st.error("Neo4j 离线，无法获取图谱统计")

    st.markdown("---")

    # ---- Ollama Models ----
    if ollama_online and ollama_models:
        st.markdown("<div class='section-label'>可用模型</div>", unsafe_allow_html=True)
        for m in ollama_models:
            st.markdown(f"<div class='dash-card' style='text-align:left;padding:10px 16px;margin-bottom:6px;'><code>{m}</code></div>", unsafe_allow_html=True)

    st.markdown("---")

    # ---- GraphRAG Status ----
    st.markdown("<div class='section-label'>GraphRAG 状态</div>", unsafe_allow_html=True)
    try:
        bridge = GraphRAGBridge()
        stats = bridge.get_stats()
        bridge.close()

        rcol1, rcol2, rcol3 = st.columns(3)
        with rcol1:
            st.markdown(f"<div class='dash-card'><div class='value'>{stats['vector_chunks']:,}</div><div class='label'>VectorChunk</div></div>", unsafe_allow_html=True)
        with rcol2:
            st.markdown(f"<div class='dash-card'><div class='value'>{stats['describes_relations']:,}</div><div class='label'>DESCRIBES 关系</div></div>", unsafe_allow_html=True)
        with rcol3:
            st.markdown(f"<div class='dash-card'><div class='value'>{stats['linked_components']:,}</div><div class='label'>关联 Component</div></div>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"GraphRAG 状态获取失败: {e}")

    st.markdown("---")

    # ---- Quick Graph Query ----
    st.markdown("<div class='section-label'>快速图谱查询</div>", unsafe_allow_html=True)
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
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown("<span style='color:var(--text-secondary);font-size:0.9rem;'>从 Datasheet PDF 提取参数，工程师审批后落盘到 AMR 数据源。</span>", unsafe_allow_html=True)

    manager = st.session_state.datasheet_hitl

    # 统计
    stats = manager.get_stats()
    dcol1, dcol2, dcol3, dcol4 = st.columns(4)
    with dcol1:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--warning)'>{stats['pending']}</div><div class='label'>待审批</div></div>", unsafe_allow_html=True)
    with dcol2:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--success)'>{stats['approved']}</div><div class='label'>已批准</div></div>", unsafe_allow_html=True)
    with dcol3:
        st.markdown(f"<div class='dash-card'><div class='value' style='color:var(--error)'>{stats['rejected']}</div><div class='label'>已拒绝</div></div>", unsafe_allow_html=True)
    with dcol4:
        st.markdown(f"<div class='dash-card'><div class='value'>{stats['total']}</div><div class='label'>总计</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    # 上传 PDF 并解析
    st.markdown("<div class='section-label'>上传 Datasheet PDF</div>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

    if uploaded_file is not None:
        col1, col2 = st.columns(2)
        with col1:
            component_hint = st.text_input("器件类型提示", "capacitor", help="如 capacitor, resistor, buck_converter")
        with col2:
            mpn_override = st.text_input("MPN 覆盖（可选）", "", help="如果文件名不是 MPN，在此输入")

        if st.button("🔍 解析 PDF", type="primary"):
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
                    for p in result.parameters:
                        st.markdown(f"""
                        <div class='dash-card' style='text-align:left;padding:10px 16px;margin-bottom:6px;'>
                            <strong>{p.name}</strong>: {p.value} {p.unit}
                            <code style='margin-left:8px;'>{p.param_type.value}</code>
                        </div>
                        """, unsafe_allow_html=True)

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
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--info);'>
                    <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>
                        <span class='status-badge pending'>待审批</span>
                        <strong>{pr.param_name}</strong>
                        <code>{pr.param_type}</code>
                    </div>
                    <div style='display:grid;grid-template-columns:80px 1fr;gap:2px 12px;font-size:0.85rem;color:var(--text-secondary);'>
                        <span>MPN</span><code>{pr.mpn}</code>
                        <span>值</span><strong style='color:var(--text-primary)'>{pr.value} {pr.unit}</strong>
                    </div>
                    {f'<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px;">原文: {pr.source_text[:100]}</div>' if pr.source_text else ''}
                    {f'<div style="font-size:0.8rem;color:var(--warning);margin-top:2px;">置信度: {pr.confidence:.0%}</div>' if pr.confidence < 1.0 else ''}
                </div>
                """, unsafe_allow_html=True)
                bcol1, bcol2, bcol3 = st.columns(3)
                with bcol1:
                    if st.button("✅ 批准", key=f"ds_approve_{pr.review_id}", use_container_width=True):
                        manager.approve(pr.review_id, reviewer="web_user", comment="确认")
                        st.success("已批准")
                        st.rerun()
                with bcol2:
                    if st.button("❌ 拒绝", key=f"ds_reject_{pr.review_id}", use_container_width=True):
                        manager.reject(pr.review_id, reviewer="web_user", comment="误报")
                        st.warning("已拒绝")
                        st.rerun()
                with bcol3:
                    new_val = st.number_input("修改值", value=float(pr.value), key=f"ds_mod_val_{pr.review_id}", label_visibility="collapsed")
                    new_unit = st.text_input("修改单位", value=pr.unit, key=f"ds_mod_unit_{pr.review_id}", label_visibility="collapsed")
                    if st.button("✏️ 修改并批准", key=f"ds_modify_{pr.review_id}", use_container_width=True):
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
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--success);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='status-badge approved'>已批准</span>
                        <strong>{pr.param_name}</strong> = {pr.value} {pr.unit}
                        <code>{pr.mpn}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 意见: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if st.button("💾 落盘到 AMR 数据源", type="primary"):
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
                st.markdown(f"""
                <div class='violation-card' style='border-left-color:var(--error);'>
                    <div style='display:flex;align-items:center;gap:8px;'>
                        <span class='status-badge rejected'>已拒绝</span>
                        <strong>{pr.param_name}</strong> = {pr.value} {pr.unit}
                        <code>{pr.mpn}</code>
                    </div>
                    <div style='font-size:0.8rem;color:var(--text-muted);margin-top:4px;'>
                        审批人: {pr.reviewer} | 理由: {pr.review_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)

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
# 多页面导航配置（必须在所有页面函数定义之后）
# ============================================================

pages = {
    "chat": st.Page(render_chat, title="智能对话", icon="💬"),
    "review": st.Page(render_review_report, title="审查报告", icon="📋"),
    "hitl": st.Page(render_hitl, title="HITL 审批", icon="✅"),
    "datasheet": st.Page(render_datasheet_hitl, title="Datasheet 审批", icon="📄"),
    "status": st.Page(render_system_status, title="系统状态", icon="📊"),
}

# 添加知识库管理页面（如果存在）
_kb_page_path = os.path.join(os.path.dirname(__file__), "pages", "knowledge_base.py")
if os.path.exists(_kb_page_path):
    pages["knowledge_base"] = st.Page("pages/knowledge_base.py", title="知识库管理", icon="📚")

# 添加 ETL 导入页面（如果存在）
_etl_page_path = os.path.join(os.path.dirname(__file__), "pages", "etl_import.py")
if os.path.exists(_etl_page_path):
    pages["etl_import"] = st.Page("pages/etl_import.py", title="ETL 导入", icon="🔧")

# 添加图谱可视化页面（如果存在）
_graph_viz_page_path = os.path.join(os.path.dirname(__file__), "pages", "graph_viz.py")
if os.path.exists(_graph_viz_page_path):
    pages["graph_viz"] = st.Page("pages/graph_viz.py", title="图谱可视化", icon="🔗")

# 添加 HITL 审批面板页面（如果存在）
_hitl_page_path = os.path.join(os.path.dirname(__file__), "pages", "hitl_review.py")
if os.path.exists(_hitl_page_path):
    pages["hitl_review"] = st.Page("pages/hitl_review.py", title="HITL 审批面板", icon="✅")

# 设置导航
pg = st.navigation(list(pages.values()), position="sidebar")

# 侧边栏额外内容
with st.sidebar:
    # Theme toggle
    st.markdown("---")
    theme_col1, theme_col2 = st.columns([1, 2])
    with theme_col1:
        theme_icon = "🌙" if st.session_state.theme == "dark" else "☀️"
        st.markdown(f"<div style='font-size:1.5rem;text-align:center;padding-top:4px;'>{theme_icon}</div>", unsafe_allow_html=True)
    with theme_col2:
        new_theme = st.selectbox(
            "主题",
            options=["dark", "light"],
            index=0 if st.session_state.theme == "dark" else 1,
            format_func=lambda x: "深色模式" if x == "dark" else "浅色模式",
            key="_theme_selector",
        )
        if new_theme != st.session_state.theme:
            st.session_state.theme = new_theme
            st.rerun()

    st.markdown("---")
    render_quick_actions()

# 运行当前页面
pg.run()


