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

from agent_system.graph_tools import _run_cypher, get_current_project


def _pid_where(alias: str = "n", prefix: str = " AND ") -> str:
    """根据当前 project_id 生成 WHERE 子句片段"""
    pid = get_current_project()
    if pid == "default":
        return ""
    return f"{prefix}({alias}.project_id = '{pid}' OR {alias}.project_id IS NULL)"

# 最大邻居数限制，避免渲染卡顿
MAX_NEIGHBORS = 50


def _build_common_cause_dot(graph_data: dict) -> str:
    """Build DOT string for common cause failure visualization."""
    dot_nodes = []
    dot_edges = []

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Add nodes
    for node in nodes:
        nid = _safe_id(node["id"])
        label = node["id"]
        if node.get("model"):
            label = f"{node['id']}\n{node['model']}"
        label = _safe_label(label)
        is_shared = node.get("is_shared", False)

        if is_shared:
            # Shared upstream: red/orange
            dot_nodes.append(
                f'    {nid} [label="{label}", shape=box, '
                f'style="filled,bold", fillcolor="#E65100", fontcolor=white, '
                f'fontsize=11, penwidth=2];'
            )
        elif node.get("level", 0) == 0:
            # Source component: blue
            dot_nodes.append(
                f'    {nid} [label="{label}", shape=box, '
                f'style=filled, fillcolor="#1565C0", fontcolor=white, '
                f'fontsize=10];'
            )
        else:
            # Upstream component: dark
            dot_nodes.append(
                f'    {nid} [label="{label}", shape=box, '
                f'style=filled, fillcolor="#37474F", fontcolor=white, '
                f'fontsize=9];'
            )

    # Add edges
    for edge in edges:
        src_id = _safe_id(edge["source"])
        tgt_id = _safe_id(edge["target"])
        label = edge.get("label", "")
        if label:
            label = _safe_label(label)
        dot_edges.append(f'    {src_id} -- {tgt_id} [label="{label}", fontsize=8];')

    dot = "graph G {\n"
    dot += "    rankdir=TB;\n"
    dot += "    bgcolor=transparent;\n"
    dot += "    node [fontname=\"Arial\"];\n"
    dot += "    edge [color=\"#555555\"];\n"
    dot += "\n".join(dot_nodes) + "\n"
    dot += "\n".join(dot_edges) + "\n"
    dot += "}"

    return dot


def _safe_id(name: str) -> str:
    """Convert a name to a safe DOT identifier."""
    return name.replace(" ", "_").replace("-", "_").replace(".", "_").replace("/", "_").replace("+", "_PLUS_")


def _safe_label(text: str) -> str:
    """Escape special characters for DOT label strings."""
    if not text:
        return text
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace('?', '&#63;')
        .replace('{', '&#123;')
        .replace('}', '&#125;')
        .replace('|', '&#124;'))


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
            net_name = _safe_label(net_record["net_name"])
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
            safe_net = _safe_label(net_name)
            if is_power:
                dot_nodes.append(
                    f'    {net_id} [label="{safe_net}", shape=circle, '
                    f'style=filled, fillcolor="#e53935", fontcolor=white, '
                    f'fontsize=10, width=0.8];'
                )
            else:
                dot_nodes.append(
                    f'    {net_id} [label="{safe_net}", shape=circle, '
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
                nb_part_type = _safe_label(nb.get("part_type", ""))

                nb_comp_id = _safe_id(f"comp_{nb_refdes}")

                if nb_refdes not in visited_components:
                    visited_components.add(nb_refdes)
                    # Add component node
                    label = f"{nb_refdes}\\n({nb_part_type})" if nb_part_type else nb_refdes
                    safe_label = _safe_label(label)
                    dot_nodes.append(
                        f'    {nb_comp_id} [label="{safe_label}", shape=box, '
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


def _build_power_chain_dot(refdes: str, direction: str, max_depth: int) -> str:
    """Build DOT string for power chain visualization."""
    try:
        nodes = []
        edges = []
        visited = {refdes}
        queue = [(refdes, 0)]

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            if direction in ("downstream", "both"):
                downstream_q = """
                MATCH (src:Component {RefDes: $rd})-[r:POWERED_BY]->(load:Component)
                RETURN load.RefDes AS rd, load.PartType AS pt, load.Model AS model, r.voltage AS voltage
                """
                for r in _run_cypher(downstream_q, {"rd": current}):
                    if r['rd'] in visited:
                        continue
                    visited.add(r['rd'])
                    pt = r['pt'] or 'IC'
                    v = r['voltage'] or '?'
                    nodes.append((r['rd'], pt, r['model'] or '', v))
                    edges.append((current, r['rd'], v + 'V'))
                    queue.append((r['rd'], depth + 1))

            if direction in ("upstream", "both"):
                upstream_q = """
                MATCH (src:Component)-[r:POWERED_BY]->(load:Component {RefDes: $rd})
                RETURN src.RefDes AS rd, src.PartType AS pt, src.Model AS model, r.voltage AS voltage
                """
                for r in _run_cypher(upstream_q, {"rd": current}):
                    if r['rd'] in visited:
                        continue
                    visited.add(r['rd'])
                    pt = r['pt'] or 'IC'
                    v = r['voltage'] or '?'
                    nodes.append((r['rd'], pt, r['model'] or '', v))
                    edges.append((r['rd'], current, v + 'V'))
                    queue.append((r['rd'], depth + 1))

        if not nodes and not edges:
            return None

        pt_colors = {'PMIC': '#6A1B9A', 'LDO': '#1565C0', 'BUCK': '#E65100',
                     'DCDC': '#E65100', 'IC': '#37474F', 'LOAD': '#37474F'}
        lines = ['digraph PowerChain {', '  rankdir=LR;', '  node [shape=box,style=filled,fontname="sans-serif"];']

        # Start node
        lines.append(f'  {_safe_id(refdes)} [label="{_safe_label(refdes)}\\n(起点)",fillcolor="#FFC107",fontcolor="#000"];')

        for rd, pt, model, v in nodes:
            color = pt_colors.get(pt, '#37474F')
            model_short = model[:15] if model else ''
            v_label = f'\\n{v}V' if v != '?' else ''
            label = f'{rd}\\n{pt}' + (f'\\n{model_short}' if model_short else '') + v_label
            lines.append(f'  {_safe_id(rd)} [label="{_safe_label(label)}",fillcolor="{color}",fontcolor="white"];')

        for src, dst, vlabel in edges:
            lines.append(f'  {_safe_id(src)} -> {_safe_id(dst)} [label="{_safe_label(vlabel)}",color="#e53935",fontcolor="#e53935"];')

        lines.append('}')
        return '\n'.join(lines)
    except Exception:
        return None


def _build_fault_root_dot(refdes: str) -> str:
    """Build DOT string for fault root cause visualization."""
    try:
        nodes = [(refdes, 'FAULT', '', '')]
        edges = []
        visited = {refdes}

        # Upstream power
        upstream_q = """
        MATCH (src:Component)-[r:POWERED_BY]->(c:Component {RefDes: $rd})
        RETURN src.RefDes AS rd, src.PartType AS pt, src.Model AS model, r.voltage AS voltage
        """
        for r in _run_cypher(upstream_q, {"rd": refdes}):
            if r['rd'] in visited:
                continue
            visited.add(r['rd'])
            nodes.append((r['rd'], r['pt'] or 'IC', r['model'] or '', r['voltage'] or '?'))
            edges.append((r['rd'], refdes, 'POWERED_BY', 90))

            # 2nd level upstream
            up2_q = """
            MATCH (src2:Component)-[r:POWERED_BY]->(src:Component {RefDes: $rd2})
            RETURN src2.RefDes AS rd, src2.PartType AS pt, r.voltage AS voltage
            """
            for u2 in _run_cypher(up2_q, {"rd2": r['rd']}):
                if u2['rd'] in visited:
                    continue
                visited.add(u2['rd'])
                nodes.append((u2['rd'], u2['pt'] or 'IC', '', u2['voltage'] or '?'))
                edges.append((u2['rd'], r['rd'], 'POWERED_BY', 70))

        # Enable signal drivers
        en_q = """
        MATCH (c:Component {RefDes: $rd})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.Name =~ '(?i).*(_EN|EN_|ENABLE|^EN$)'
        MATCH (drv:Component)-[:HAS_PIN]->(dp:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE drv.RefDes <> $rd
        RETURN DISTINCT drv.RefDes AS rd, drv.PartType AS pt, n.Name AS net
        """
        for r in _run_cypher(en_q, {"rd": refdes}):
            if r['rd'] in visited:
                continue
            visited.add(r['rd'])
            nodes.append((r['rd'], r['pt'] or 'IC', '', ''))
            edges.append((r['rd'], refdes, f'EN: {r["net"]}', 85))

        if len(nodes) <= 1:
            return None

        lines = ['digraph FaultRoot {', '  rankdir=RL;', '  node [shape=box,style=filled,fontname="sans-serif"];']
        lines.append(f'  {_safe_id(refdes)} [label="{_safe_label(refdes)}\\n⚠ 故障点",fillcolor="#e53935",fontcolor="white"];')

        for rd, pt, model, v in nodes[1:]:
            v_label = f'\\n{v}V' if v and v != '?' else ''
            label = f'{rd}\\n{pt}' + v_label
            lines.append(f'  {_safe_id(rd)} [label="{_safe_label(label)}",fillcolor="#FF9800",fontcolor="#000"];')

        for src, dst, elabel, _ in edges:
            lines.append(f'  {_safe_id(src)} -> {_safe_id(dst)} [label="{_safe_label(elabel)}",color="#e53935"];')

        lines.append('}')
        return '\n'.join(lines)
    except Exception:
        return None


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
        source_query = f"""
        MATCH (c:Component)
        WHERE c.PartType IN ['PMIC', 'LDO', 'BUCK', 'DCDC']{_pid_where('c')}
        RETURN c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
        ORDER BY c.PartType, c.RefDes
        """
        # Limit sources to avoid generating enormous DOT
        MAX_SOURCES = 15
        sources = _run_cypher(source_query)

        if not sources:
            return None

        total_sources = len(sources)
        sources = sources[:MAX_SOURCES]

        # Add a virtual root for the tree
        root_label = f"电源树" + (f" (前{MAX_SOURCES}/{total_sources}个)" if total_sources > MAX_SOURCES else "")
        dot_nodes.append(
            f'    power_root [label="{root_label}", shape=doubleoctagon, '
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
            safe_label = _safe_label(label)

            # Color by type
            type_colors = {
                "PMIC": "#6A1B9A",
                "BUCK": "#E65100",
                "DCDC": "#E65100",
                "LDO": "#1565C0",
            }
            color = type_colors.get(src_pt, "#1565C0")

            dot_nodes.append(
                f'    {src_id} [label="{safe_label}", shape=box, '
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

            # Limit nets per source to keep graph manageable
            output_nets = output_nets[:8]

            for net_info in output_nets:
                net_name = net_info["net_name"]
                net_v = net_info.get("voltage", "?")
                net_id = _safe_id(f"net_{net_name}")

                dot_nodes.append(
                    f'    {net_id} [label="{_safe_label(net_name)}\\n({_safe_label(str(net_v))}V)", shape=circle, '
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
                            safe_label = _safe_label(label)
                            dot_nodes.append(
                                f'    {agg_id} [label="{safe_label}", shape=box, '
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
                            safe_label = _safe_label(label)
                            dot_nodes.append(
                                f'    {ld_id} [label="{safe_label}", shape=box, '
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
                    ds_label = _safe_label(f"{ds_refdes}\\n({ds_pt})")
                    dot_nodes.append(
                        f'    {ds_id} [label="{ds_label}", shape=box, '
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
        "Neo4j 图谱关系可视化 · 组件连接 · 电源树 · 共因失效"
        "</span>",
        unsafe_allow_html=True,
    )

    # Check Neo4j connectivity
    try:
        node_count = _run_cypher(f"MATCH (n) WHERE 1=1{_pid_where('n')} RETURN count(n) AS cnt")[0]["cnt"]
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
            options=["组件关系图", "电源树", "电源链路", "故障溯源", "共因失效分析"],
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

    # Use session_state to persist DOT across reruns (button click triggers rerun)
    if "_graph_viz_dot" not in st.session_state:
        st.session_state._graph_viz_dot = None

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
                        check = _run_cypher(
                            "MATCH (c:Component {RefDes: $refdes}) RETURN c.RefDes AS r",
                            {"refdes": refdes.strip()},
                        )
                        if not check:
                            st.error(f"未找到组件: {refdes.strip()}")
                        else:
                            st.session_state._graph_viz_dot = ("component", _build_component_relation_dot(refdes.strip(), depth))
                    except Exception as e:
                        st.error(f"查询失败: {e}")

    elif viz_type == "电源树":
        try:
            voltages = _run_cypher(f"""
                MATCH (n:Net) WHERE n.VoltageLevel IS NOT NULL{_pid_where('n')}
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
                dot_result = _build_power_tree_dot(voltage_filter)
                if dot_result is None:
                    st.warning("未找到电源器件或电源网络数据")
                else:
                    st.session_state._graph_viz_dot = ("power", dot_result)

    elif viz_type == "电源链路":
        # Power chain tracing
        chain_refdes = st.text_input(
            "起始电源器件 RefDes",
            value="UU45",
            help="输入电源器件位号，追踪上/下游电源链路",
        )
        chain_dir = st.selectbox(
            "追踪方向",
            options=["both", "downstream", "upstream"],
            index=0,
            format_func=lambda x: {"both": "双向（上游+下游）", "downstream": "下游（负载端）", "upstream": "上游（供电端）"}[x],
        )
        chain_depth = st.slider(
            "追踪深度",
            min_value=1,
            max_value=5,
            value=3,
        )

        if st.button("⚡ 生成电源链路图", type="primary"):
            if not chain_refdes.strip():
                st.warning("请输入器件 RefDes")
            else:
                with st.spinner("正在追踪电源链路..."):
                    try:
                        from agent_system.graph_tools import trace_power_chain
                        result = trace_power_chain.invoke({
                            "refdes": chain_refdes.strip(),
                            "direction": chain_dir,
                            "max_depth": chain_depth,
                        })
                        # Build DOT from power chain
                        dot_str = _build_power_chain_dot(chain_refdes.strip(), chain_dir, chain_depth)
                        if dot_str:
                            st.session_state._graph_viz_dot = ("power_chain", dot_str)
                            with st.expander("📋 链路详情"):
                                st.text(result)
                        else:
                            st.info("未找到电源链路数据")
                    except Exception as e:
                        st.error(f"链路追踪失败: {e}")

    elif viz_type == "故障溯源":
        # Fault root cause tracing
        fault_refdes = st.text_input(
            "故障器件 RefDes",
            value="U1",
            help="输入故障器件位号，分析根因",
        )
        fault_symptom = st.text_input(
            "故障现象（可选）",
            value="",
            help="如：无输出、电压异常、不工作",
        )

        if st.button("🔍 故障溯源分析", type="primary"):
            if not fault_refdes.strip():
                st.warning("请输入器件 RefDes")
            else:
                with st.spinner("正在分析故障根因..."):
                    try:
                        from agent_system.graph_tools import trace_fault_root
                        result = trace_fault_root.invoke({
                            "refdes": fault_refdes.strip(),
                            "symptom": fault_symptom.strip(),
                        })
                        # Build DOT from fault analysis
                        dot_str = _build_fault_root_dot(fault_refdes.strip())
                        if dot_str:
                            st.session_state._graph_viz_dot = ("fault", dot_str)
                        with st.expander("📋 根因分析报告"):
                            st.text(result)
                    except Exception as e:
                        st.error(f"分析失败: {e}")

    elif viz_type == "共因失效分析":
        # Common cause failure analysis
        refdes_list = st.text_input(
            "分析器件列表（逗号分隔）",
            value="U60140,U60000",
            help="输入多个器件位号，分析它们的电源共同上游",
        )

        if st.button("⚡ 共因失效分析", type="primary"):
            if not refdes_list.strip():
                st.warning("请输入器件位号")
            else:
                with st.spinner("正在分析共因失效风险..."):
                    try:
                        from agent_system.graph_tools import common_cause_risk_score, get_common_cause_graph

                        # 风险评分
                        score_result = common_cause_risk_score.invoke({"refdes_list": refdes_list.strip()})
                        st.markdown("### 风险评估")
                        st.text(score_result)

                        # 图谱数据
                        graph_json = get_common_cause_graph.invoke({"refdes_list": refdes_list.strip()})
                        import json
                        graph_data = json.loads(graph_json)

                        if graph_data.get("nodes"):
                            dot_str = _build_common_cause_dot(graph_data)
                            if dot_str:
                                st.session_state._graph_viz_dot = ("common_cause", dot_str)
                        else:
                            st.info("未发现电源上游共享关系")

                    except Exception as e:
                        st.error(f"分析失败: {e}")

    # Render graph from session state
    if st.session_state._graph_viz_dot is not None:
        saved_type, dot_str = st.session_state._graph_viz_dot
        st.markdown("### 可视化结果")

        # Legend
        if saved_type == "component":
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

        # For large DOT (>10KB), use server-side PNG rendering
        # viz.js frontend can choke on large graphs
        try:
            if len(dot_str) > 10000:
                import graphviz as gv
                import tempfile
                src = gv.Source(dot_str)
                tmp_dir = tempfile.mkdtemp()
                out_path = src.render(format='png', directory=tmp_dir)
                st.image(out_path, use_container_width=True)
                # Cleanup
                try:
                    import os
                    os.remove(out_path)
                    for f in os.listdir(tmp_dir):
                        os.remove(os.path.join(tmp_dir, f))
                    os.rmdir(tmp_dir)
                except Exception:
                    pass
            else:
                st.graphviz_chart(dot_str, use_container_width=True)
        except Exception as e:
            st.error(f"图表渲染失败: {e}")
            with st.expander("查看 DOT 源码"):
                st.code(dot_str, language="dot")


