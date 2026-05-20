"""
图谱可视化页面 — Neo4j 图谱关系可视化

功能：
  1. 组件关系图：输入 RefDes，展示连接的 Net 和相邻组件
  2. 电源树可视化：展示电源域层级关系（IC → LDO → 负载）
  3. 交互控制：可视化类型选择、深度控制、起始组件输入
  4. 节点样式：Component=矩形蓝色, Net=圆形灰色, 电源网络=圆形红色
"""

import os
import sys
import streamlit as st

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from agent_system.graph_tools import _run_cypher

# 最大邻居数限制，避免渲染卡顿
MAX_NEIGHBORS = 50


def _safe_id(name: str) -> str:
    """Convert a name to a safe DOT identifier."""
    return name.replace(" ", "_").replace("-", "_").replace(".", "_").replace("/", "_")


def _build_component_relation_dot(refdes: str, depth: int) -> str:
    """
    Build DOT string for component relation graph.
    BFS from the given component, expanding through Nets up to `depth` layers.
    """
    visited_components = set()
    visited_nets = set()
    # (refdes, current_depth)
    queue = [(refdes, 0)]
    visited_components.add(refdes)

    dot_nodes = []
    dot_edges = []

    # Track power nets for styling
    power_nets = set()

    while queue:
        current_refdes, current_depth = queue.pop(0)
        if current_depth >= depth:
            continue

        # Find all nets connected to this component
        query = """
        MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        RETURN n.Name AS net_name, n.NetType AS net_type, n.VoltageLevel AS voltage
        ORDER BY n.Name
        """
        try:
            nets = _run_cypher(query, {"refdes": current_refdes})
        except Exception:
            continue

        for net_record in nets:
            net_name = net_record["net_name"]
            net_type = net_record.get("net_type", "")
            is_power = net_type == "POWER" or (net_name and any(
                kw in net_name.upper() for kw in ["VCC", "VDD", "GND", "3V3", "1V8", "5V", "VIN"]
            ))

            if is_power:
                power_nets.add(net_name)

            if net_name in visited_nets:
                continue
            visited_nets.add(net_name)

            # Add net node
            net_id = _safe_id(f"net_{net_name}")
            if is_power:
                dot_nodes.append(
                    f'    {net_id} [label="{net_name}", shape=circle, '
                    f'style=filled, fillcolor="#e53935", fontcolor=white, '
                    f'fontsize=10, width=0.8];'
                )
            else:
                dot_nodes.append(
                    f'    {net_id} [label="{net_name}", shape=circle, '
                    f'style=filled, fillcolor="#616161", fontcolor=white, '
                    f'fontsize=9, width=0.6];'
                )

            # Edge from component to net
            comp_id = _safe_id(f"comp_{current_refdes}")
            dot_edges.append(f'    {comp_id} -- {net_id};')

            # Find neighboring components on this net (limited)
            neighbor_query = """
            MATCH (c2:Component)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
            WHERE c2.RefDes <> $refdes
            RETURN DISTINCT c2.RefDes AS refdes, c2.PartType AS part_type
            ORDER BY c2.RefDes
            LIMIT $limit
            """
            try:
                neighbors = _run_cypher(neighbor_query, {"net_name": net_name, "refdes": current_refdes, "limit": MAX_NEIGHBORS})
            except Exception:
                continue

            for nb in neighbors:
                nb_refdes = nb["refdes"]
                nb_part_type = nb.get("part_type", "")

                nb_comp_id = _safe_id(f"comp_{nb_refdes}")

                if nb_refdes not in visited_components:
                    visited_components.add(nb_refdes)
                    # Add component node
                    label = f"{nb_refdes}\\n({nb_part_type})" if nb_part_type else nb_refdes
                    dot_nodes.append(
                        f'    {nb_comp_id} [label="{label}", shape=box, '
                        f'style=filled, fillcolor="#1565C0", fontcolor=white, '
                        f'fontsize=10];'
                    )
                    # Enqueue for BFS
                    if current_depth + 1 < depth:
                        queue.append((nb_refdes, current_depth + 1))

                # Edge from net to neighbor component
                dot_edges.append(f'    {net_id} -- {nb_comp_id};')

    # Add the root component node (highlighted)
    root_id = _safe_id(f"comp_{refdes}")
    # Check if already added (might have been added as neighbor at depth 0)
    root_already = any(root_id in node for node in dot_nodes)
    if not root_already:
        # Get part type for root
        try:
            root_info = _run_cypher(
                "MATCH (c:Component {RefDes: $refdes}) RETURN c.PartType AS pt",
                {"refdes": refdes}
            )
            pt = root_info[0]["pt"] if root_info else ""
        except Exception:
            pt = ""
        label = f"{refdes}\\n({pt})" if pt else refdes
        dot_nodes.insert(0,
            f'    {root_id} [label="{label}", shape=box, '
            f'style="filled,bold", fillcolor="#0D47A1", fontcolor=white, '
            f'fontsize=12, penwidth=2];'
        )
    else:
        # Replace root node with highlighted version
        dot_nodes = [n for n in dot_nodes if root_id not in n]
        try:
            root_info = _run_cypher(
                "MATCH (c:Component {RefDes: $refdes}) RETURN c.PartType AS pt",
                {"refdes": refdes}
            )
            pt = root_info[0]["pt"] if root_info else ""
        except Exception:
            pt = ""
        label = f"{refdes}\\n({pt})" if pt else refdes
        dot_nodes.insert(0,
            f'    {root_id} [label="{label}", shape=box, '
            f'style="filled,bold", fillcolor="#0D47A1", fontcolor=white, '
            f'fontsize=12, penwidth=2];'
        )

    dot = "graph G {\n"
    dot += "    rankdir=LR;\n"
    dot += "    bgcolor=transparent;\n"
    dot += "    node [fontname=\"Arial\"];\n"
    dot += "    edge [color=\"#555555\"];\n"
    dot += "\n".join(dot_nodes) + "\n"
    dot += "\n".join(dot_edges) + "\n"
    dot += "}"

    return dot


def _build_power_tree_dot(voltage: str = None) -> str:
    """
    Build DOT string for power tree visualization.
    Shows hierarchy: IC → LDO/BUCK → Load components.
    """
    dot_nodes = []
    dot_edges = []

    visited = set()

    try:
        # Find all power source components (PMIC, LDO, BUCK)
        source_query = """
        MATCH (c:Component)
        WHERE c.PartType IN ['PMIC', 'LDO', 'BUCK', 'DCDC']
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
        ORDER BY c.PartType, c.RefDes
        """
        sources = _run_cypher(source_query)

        if not sources:
            return None

        # Add a virtual root for the tree
        dot_nodes.append(
            f'    power_root [label="电源树", shape=doubleoctagon, '
            f'style=filled, fillcolor="#4A148C", fontcolor=white, fontsize=14];'
        )

        for src in sources:
            src_refdes = src["refdes"]
            src_pt = src["part_type"] or ""
            src_model = src.get("model", "") or ""

            if voltage and src_refdes in visited:
                continue
            visited.add(src_refdes)

            src_id = _safe_id(f"comp_{src_refdes}")
            label = f"{src_refdes}\\n{src_pt}\\n{src_model}" if src_model else f"{src_refdes}\\n{src_pt}"

            # Color by type
            type_colors = {
                "PMIC": "#6A1B9A",
                "BUCK": "#E65100",
                "DCDC": "#E65100",
                "LDO": "#1565C0",
            }
            color = type_colors.get(src_pt, "#1565C0")

            dot_nodes.append(
                f'    {src_id} [label="{label}", shape=box, '
                f'style=filled, fillcolor="{color}", fontcolor=white, fontsize=10];'
            )
            dot_edges.append(f'    power_root -- {src_id};')

            # Find output power nets for this source
            output_query = """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.VoltageLevel IS NOT NULL
                  AND NOT n.Name CONTAINS 'GND'
                  AND NOT n.Name = 'DGND'
                  AND NOT n.Name = 'NC'
            RETURN DISTINCT n.Name AS net_name, n.VoltageLevel AS voltage
            ORDER BY n.VoltageLevel DESC
            """
            try:
                output_nets = _run_cypher(output_query, {"refdes": src_refdes})
            except Exception:
                continue

            # Filter by voltage if specified
            if voltage:
                output_nets = [n for n in output_nets if n.get("voltage") == voltage]

            for net_info in output_nets:
                net_name = net_info["net_name"]
                net_v = net_info.get("voltage", "?")
                net_id = _safe_id(f"net_{net_name}")

                dot_nodes.append(
                    f'    {net_id} [label="{net_name}\\n({net_v}V)", shape=circle, '
                    f'style=filled, fillcolor="#e53935", fontcolor=white, '
                    f'fontsize=9, width=0.8];'
                )
                dot_edges.append(f'    {src_id} -- {net_id};')

                # Find load components on this net
                load_query = """
                MATCH (lc:Component)-[:HAS_PIN]->(lp:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
                WHERE lc.RefDes <> $refdes
                  AND NOT lc.PartType IN ['PMIC', 'LDO', 'BUCK', 'DCDC']
                RETURN DISTINCT lc.RefDes AS refdes, lc.PartType AS part_type
                ORDER BY lc.RefDes
                LIMIT 20
                """
                try:
                    loads = _run_cypher(load_query, {"net_name": net_name, "refdes": src_refdes})
                except Exception:
                    continue

                # Group loads by type for compact display
                if loads:
                    # If too many loads, aggregate by type
                    if len(loads) > 8:
                        by_type = {}
                        for ld in loads:
                            pt = ld["part_type"] or "Unknown"
                            by_type.setdefault(pt, []).append(ld["refdes"])
                        for pt, refs in sorted(by_type.items(), key=lambda x: -len(x[1])):
                            agg_id = _safe_id(f"agg_{net_name}_{pt}")
                            label = f"{pt}\\n({len(refs)}个)"
                            dot_nodes.append(
                                f'    {agg_id} [label="{label}", shape=box, '
                                f'style=filled, fillcolor="#37474F", fontcolor=white, '
                                f'fontsize=9, tooltip="{", ".join(refs[:5])}"];'
                            )
                            dot_edges.append(f'    {net_id} -- {agg_id};')
                    else:
                        for ld in loads:
                            ld_refdes = ld["refdes"]
                            ld_pt = ld.get("part_type", "")
                            ld_id = _safe_id(f"comp_{ld_refdes}")
                            label = f"{ld_refdes}\\n({ld_pt})" if ld_pt else ld_refdes
                            dot_nodes.append(
                                f'    {ld_id} [label="{label}", shape=box, '
                                f'style=filled, fillcolor="#37474F", fontcolor=white, '
                                f'fontsize=9];'
                            )
                            dot_edges.append(f'    {net_id} -- {ld_id};')

                # Check for downstream power sources (LDO/BUCK fed by this net)
                downstream_query = """
                MATCH (dc:Component)-[:HAS_PIN]->(dp:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
                WHERE dc.RefDes <> $refdes
                  AND dc.PartType IN ['LDO', 'BUCK', 'DCDC']
                RETURN DISTINCT dc.RefDes AS refdes, dc.PartType AS part_type
                LIMIT 5
                """
                try:
                    downstream = _run_cypher(downstream_query, {"net_name": net_name, "refdes": src_refdes})
                except Exception:
                    downstream = []

                for ds in downstream:
                    ds_refdes = ds["refdes"]
                    ds_pt = ds.get("part_type", "")
                    if ds_refdes in visited:
                        continue
                    visited.add(ds_refdes)
                    ds_id = _safe_id(f"comp_{ds_refdes}")
                    ds_color = type_colors.get(ds_pt, "#1565C0")
                    dot_nodes.append(
                        f'    {ds_id} [label="{ds_refdes}\\n({ds_pt})", shape=box, '
                        f'style=filled, fillcolor="{ds_color}", fontcolor=white, fontsize=10];'
                    )
                    dot_edges.append(f'    {net_id} -- {ds_id};')

    except Exception:
        return None

    dot = "graph G {\n"
    dot += "    rankdir=TB;\n"
    dot += "    bgcolor=transparent;\n"
    dot += "    node [fontname=\"Arial\"];\n"
    dot += "    edge [color=\"#555555\"];\n"
    dot += "\n".join(dot_nodes) + "\n"
    dot += "\n".join(dot_edges) + "\n"
    dot += "}"

    return dot


def render_graph_viz():
    st.markdown("<div class='main-header'>🔗 图谱可视化</div>", unsafe_allow_html=True)
    st.markdown("<div class='header-line'></div>", unsafe_allow_html=True)
    st.markdown(
        "<span style='color:var(--text-secondary);font-size:0.9rem;'>"
        "Neo4j 图谱关系可视化 · 组件连接 · 电源树"
        "</span>",
        unsafe_allow_html=True,
    )

    # Check Neo4j connectivity
    try:
        node_count = _run_cypher("MATCH (n) RETURN count(n) AS cnt")[0]["cnt"]
    except Exception as e:
        st.error(f"❌ Neo4j 连接失败: {e}")
        return

    if node_count == 0:
        st.warning("⚠️ Neo4j 数据库为空，请先通过 ETL 导入页面加载数据。")
        return

    # Sidebar controls
    st.markdown("### 可视化控制")

    ctrl_col1, ctrl_col2 = st.columns(2)
    with ctrl_col1:
        viz_type = st.selectbox(
            "可视化类型",
            options=["组件关系图", "电源树"],
            index=0,
        )
    with ctrl_col2:
        depth = st.slider(
            "展示深度",
            min_value=1,
            max_value=3,
            value=1,
            help="从起始组件开始，扩展几层邻居关系",
        )

    dot_str = None

    if viz_type == "组件关系图":
        # Component relation graph
        refdes = st.text_input(
            "起始组件 RefDes",
            value="U1",
            help="输入组件位号，如 U30004、R40005",
        )

        if st.button("🔍 生成组件关系图", type="primary"):
            if not refdes.strip():
                st.warning("请输入组件 RefDes")
            else:
                with st.spinner("正在查询图谱并生成可视化..."):
                    try:
                        # Verify component exists
                        check = _run_cypher(
                            "MATCH (c:Component {RefDes: $refdes}) RETURN c.RefDes AS r",
                            {"refdes": refdes.strip()},
                        )
                        if not check:
                            st.error(f"未找到组件: {refdes.strip()}")
                        else:
                            dot_str = _build_component_relation_dot(refdes.strip(), depth)
                    except Exception as e:
                        st.error(f"查询失败: {e}")

    else:
        # Power tree
        # Get available voltage levels
        try:
            voltages = _run_cypher("""
                MATCH (n:Net) WHERE n.VoltageLevel IS NOT NULL
                RETURN DISTINCT n.VoltageLevel AS v ORDER BY n.VoltageLevel
            """)
            voltage_options = ["全部"] + [v["v"] for v in voltages]
        except Exception:
            voltage_options = ["全部"]

        selected_voltage = st.selectbox(
            "电压等级过滤",
            options=voltage_options,
            index=0,
            help='选择电压等级过滤电源树，或选"全部"显示完整电源树',
        )

        if st.button("⚡ 生成电源树", type="primary"):
            with st.spinner("正在查询电源树并生成可视化..."):
                voltage_filter = None if selected_voltage == "全部" else selected_voltage
                dot_str = _build_power_tree_dot(voltage_filter)
                if dot_str is None:
                    st.warning("未找到电源器件或电源网络数据")

    # Render graph
    if dot_str:
        st.markdown("### 可视化结果")

        # Legend
        if viz_type == "组件关系图":
            st.markdown("""
            <div style='display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;'>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#0D47A1;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>起始组件</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#1565C0;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>相邻组件</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:14px;height:14px;background:#616161;border-radius:50%;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>信号网络</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:14px;height:14px;background:#e53935;border-radius:50%;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>电源网络</span>
                </span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;'>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#6A1B9A;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>PMIC</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#E65100;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>BUCK/DCDC</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#1565C0;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>LDO</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:14px;height:14px;background:#e53935;border-radius:50%;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>电源网络</span>
                </span>
                <span style='display:inline-flex;align-items:center;gap:4px;'>
                    <span style='display:inline-block;width:16px;height:12px;background:#37474F;border-radius:2px;'></span>
                    <span style='font-size:0.8rem;color:var(--text-secondary);'>负载</span>
                </span>
            </div>
            """, unsafe_allow_html=True)

        try:
            st.graphviz_chart(dot_str, use_container_width=True)
        except Exception as e:
            st.error(f"图表渲染失败: {e}")
            with st.expander("查看 DOT 源码"):
                st.code(dot_str, language="dot")


render_graph_viz()
