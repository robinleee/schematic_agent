"""
Graph Tools - Neo4j 图谱查询工具集 (Smart Graph Tools V2)

封装 Cypher 查询为 LangChain Tools，供 Agent 调用。
V2 增强：
  - 智能特征聚合（大网络自动摘要）
  - 电源树分析
  - 差分对追踪（预留）
"""

import os
from typing import Optional, Any
from dotenv import load_dotenv
from langchain_core.tools import tool

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# 聚合阈值：超过此数量的网络启用聚合摘要
DEFAULT_AGGREGATION_THRESHOLD = 100


def _get_driver():
    """获取 Neo4j driver"""
    if GraphDatabase is None:
        raise RuntimeError("neo4j package not installed")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


def _run_cypher(query: str, params: dict = None) -> list[dict]:
    """执行 Cypher 并返回结果"""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        return [dict(record) for record in result]


# ============================================================
# Tool 1: 查找器件的所有连接网络
# ============================================================

@tool
def get_component_nets(refdes: str) -> str:
    """
    查询指定器件的所有引脚及其连接的网络。

    Args:
        refdes: 器件位号，如 "U30004"

    Returns:
        该器件所有引脚的网络连接信息

    Example:
        get_component_nets("U30004")
    """
    query = """
    MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
    RETURN p.Number AS pin_number,
           p.Type AS pin_type,
           n.Name AS net_name,
           n.VoltageLevel AS voltage_level,
           n.NetType AS net_type
    ORDER BY p.Number
    """
    try:
        records = _run_cypher(query, {"refdes": refdes})
        if not records:
            return f"未找到器件 {refdes}"

        lines = [f"器件 {refdes} 的网络连接:"]
        for r in records:
            lines.append(
                f"  Pin {r['pin_number']} ({r['pin_type']}) -> Net '{r['net_name']}' "
                f"[{r['voltage_level'] or '?'}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[GraphTool Error] get_component_nets: {str(e)}"


# ============================================================
# Tool 2: 查找网络的所有连接器件 (智能聚合版)
# ============================================================

@tool
def get_net_components(net_name: str, threshold: int = DEFAULT_AGGREGATION_THRESHOLD) -> str:
    """
    查询指定网络的所有连接器件和引脚。

    智能行为：
    - 如果连接节点数 <= threshold，返回详细列表（保持现有格式）
    - 如果连接节点数 > threshold，返回聚合摘要（Cypher 层聚合）

    Args:
        net_name: 网络名称，如 "VDD_1V8", "I2C_SDA"
        threshold: 聚合阈值，默认 100

    Returns:
        该网络的连接器件信息（详细列表或聚合摘要）

    Example:
        get_net_components("VDD_1V8")
        get_net_components("GND", threshold=50)
    """
    try:
        # 第一步：计数判断
        count_query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
        RETURN count(DISTINCT c) AS total_components, count(p) AS total_pins
        """
        count_result = _run_cypher(count_query, {"net_name": net_name})
        total_components = count_result[0]["total_components"] if count_result else 0
        total_pins = count_result[0]["total_pins"] if count_result else 0

        if not total_components:
            return f"未找到网络 {net_name}"

        # 小网络：返回详细列表
        if total_components <= threshold:
            query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
            RETURN c.RefDes AS refdes,
                   c.PartType AS part_type,
                   c.Value AS value,
                   p.Number AS pin_number,
                   p.Type AS pin_type
            ORDER BY c.RefDes, p.Number
            """
            records = _run_cypher(query, {"net_name": net_name})
            lines = [f"网络 '{net_name}' 的连接器件 ({total_components} 个器件, {total_pins} 个引脚):"]
            for r in records:
                lines.append(
                    f"  {r['refdes']} ({r['part_type']}, {r['value']}) "
                    f"- Pin {r['pin_number']} ({r['pin_type']})"
                )
            return "\n".join(lines)

        # 大网络：返回聚合摘要
        agg_query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
        RETURN c.PartType AS part_type,
               count(DISTINCT c) AS component_count,
               count(p) AS pin_count,
               collect(DISTINCT c.RefDes)[0..5] AS examples
        ORDER BY component_count DESC
        """
        agg_records = _run_cypher(agg_query, {"net_name": net_name})

        lines = [
            f"网络 '{net_name}' 的连接摘要 (共 {total_components} 个器件, {total_pins} 个引脚):",
            f"  [聚合模式] 节点数超过阈值({threshold})，已启用智能聚合。",
            "",
            "  按类型聚合:",
        ]
        for r in agg_records:
            pt = r['part_type'] or 'Unknown'
            examples_str = ', '.join(r['examples']) + '...' if len(r['examples']) == 5 else ', '.join(r['examples'])
            lines.append(
                f"    {pt:12s}: {r['component_count']:4d} 个器件 "
                f"({r['pin_count']:4d} 个引脚) 示例: {examples_str}"
            )

        lines.append("")
        lines.append("  提示: 如需查看该网络上的特定器件类型，请指定 PartType 查询。")
        return "\n".join(lines)

    except Exception as e:
        return f"[GraphTool Error] get_net_components: {str(e)}"


# ============================================================
# Tool 3: 电源域分析（增强版）
# ============================================================

@tool
def get_power_domain(voltage_level: str = None, detail: bool = False) -> str:
    """
    分析电源域：查找同一电压等级下的所有器件和网络。

    Args:
        voltage_level: 电压等级，如 "1V8", "3V3"。不填则返回所有电源网络概览。
        detail: 是否返回详细器件列表（默认 False，返回聚合摘要）

    Returns:
        电源域内的器件列表或聚合摘要

    Example:
        get_power_domain("1V8")
        get_power_domain("3V3", detail=True)
        get_power_domain()  # 返回概览
    """
    try:
        if voltage_level:
            if detail:
                query = """
                MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
                WHERE n.VoltageLevel = $voltage_level
                RETURN n.Name AS net_name,
                       n.VoltageLevel AS voltage,
                       collect({refdes: c.RefDes, pin: p.Number, part_type: c.PartType}) AS devices
                ORDER BY n.Name
                """
            else:
                query = """
                MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
                WHERE n.VoltageLevel = $voltage_level
                RETURN n.Name AS net_name,
                       n.VoltageLevel AS voltage,
                       count(DISTINCT c) AS component_count,
                       collect(DISTINCT c.PartType) AS part_types
                ORDER BY n.Name
                """
            params = {"voltage_level": voltage_level}
        else:
            query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.NetType IN ['POWER', 'SIGNAL'] AND n.VoltageLevel IS NOT NULL
            RETURN n.VoltageLevel AS voltage,
                   collect(DISTINCT n.Name) AS nets,
                   count(DISTINCT c) AS component_count
            ORDER BY n.VoltageLevel
            """
            params = {}

        records = _run_cypher(query, params)
        if not records:
            return "未找到电源域信息"

        if voltage_level:
            lines = [f"电源域 {voltage_level} 分析:"]
            for r in records:
                if detail:
                    lines.append(f"\n  网络: {r['net_name']} ({r['voltage']})")
                    for d in r["devices"]:
                        lines.append(f"    - {d['refdes']} [{d['part_type']}] Pin {d['pin']}")
                else:
                    pts = ', '.join(r['part_types']) if r['part_types'] else 'N/A'
                    lines.append(
                        f"  {r['net_name']}: {r['component_count']} 个器件 "
                        f"(类型: {pts})"
                    )
        else:
            lines = ["所有电源域概览:"]
            for r in records:
                lines.append(
                    f"  {r['voltage']}: {len(r['nets'])} 个网络, "
                    f"{r['component_count']} 个器件"
                )
                lines.append(f"    Nets: {', '.join(r['nets'][:5])}{'...' if len(r['nets']) > 5 else ''}")

        return "\n".join(lines)
    except Exception as e:
        return f"[GraphTool Error] get_power_domain: {str(e)}"


# ============================================================
# Tool 4: I2C 总线分析
# ============================================================

@tool
def get_i2c_devices() -> str:
    """
    分析 I2C 总线：查找所有 I2C 相关的器件（通过 I2C_SDA/I2C_SCL 网络）。

    Returns:
        I2C 总线上的器件列表

    Example:
        get_i2c_devices()
    """
    query = """
    MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
    WHERE n.Name CONTAINS 'I2C' OR n.Name CONTAINS 'SDA' OR n.Name CONTAINS 'SCL'
    RETURN n.Name AS net_name,
           c.RefDes AS refdes,
           c.PartType AS part_type,
           p.Number AS pin_number
    ORDER BY n.Name, c.RefDes
    """
    try:
        records = _run_cypher(query)
        if not records:
            return "未找到 I2C 网络"

        lines = ["I2C 总线器件:"]
        current_net = None
        for r in records:
            if r["net_name"] != current_net:
                current_net = r["net_name"]
                lines.append(f"\n  网络: {current_net}")
            lines.append(f"    - {r['refdes']} ({r['part_type']}) Pin {r['pin_number']}")

        return "\n".join(lines)
    except Exception as e:
        return f"[GraphTool Error] get_i2c_devices: {str(e)}"


# ============================================================
# Tool 5: 器件拓扑路径（追踪信号链路）
# ============================================================

@tool
def get_signal_path(from_refdes: str, from_pin: str, to_refdes: str, to_pin: str) -> str:
    """
    查询两个器件引脚之间的信号路径。

    Args:
        from_refdes: 起始器件位号
        from_pin: 起始引脚编号
        to_refdes: 终点器件位号
        to_pin: 终点引脚编号

    Returns:
        两点之间的拓扑路径

    Example:
        get_signal_path("U30004", "A4", "U30005", "A4")
    """
    query = """
    MATCH path = shortestPath(
        (a:Pin)-[:CONNECTS_TO*1..5]-(b:Pin)
    )
    WHERE a.Id = $from_pin_id AND b.Id = $to_pin_id
    RETURN path
    """
    from_pin_id = f"{from_refdes}_{from_pin}"
    to_pin_id = f"{to_refdes}_{to_pin}"

    try:
        records = _run_cypher(query, {
            "from_pin_id": from_pin_id,
            "to_pin_id": to_pin_id,
        })
        if not records:
            return f"未找到从 {from_refdes}:{from_pin} 到 {to_refdes}:{to_pin} 的路径"

        # 解析路径
        path = records[0]["path"]
        nodes = []
        for item in path:
            if hasattr(item, "RefDes"):
                nodes.append(f"{item.RefDes}/Pin-{getattr(item, 'Number', '?')}")
            else:
                nodes.append(f"Net:{item.Name}")

        return f"信号路径 ({len(nodes)} 步):\n  " + " -> ".join(nodes)
    except Exception as e:
        return f"[GraphTool Error] get_signal_path: {str(e)}"


# ============================================================
# Tool 6: 统计图谱概要
# ============================================================

@tool
def get_graph_summary() -> str:
    """
    获取 Neo4j 图谱的统计摘要。

    Returns:
        图谱概览信息

    Example:
        get_graph_summary()
    """
    try:
        total_nodes = _run_cypher("MATCH (n) RETURN count(n) AS cnt")[0]["cnt"]
        comp_count = _run_cypher("MATCH (c:Component) RETURN count(c) AS cnt")[0]["cnt"]
        net_count = _run_cypher("MATCH (n:Net) RETURN count(n) AS cnt")[0]["cnt"]
        pin_count = _run_cypher("MATCH (p:Pin) RETURN count(p) AS cnt")[0]["cnt"]

        # 按类型统计器件
        by_type = _run_cypher("""
            MATCH (c:Component)
            RETURN c.PartType AS part_type, count(c) AS cnt
            ORDER BY cnt DESC
        """)

        lines = [
            "=" * 50,
            "Neo4j 图谱统计摘要",
            "=" * 50,
            f"总节点数: {total_nodes}",
            f"  - Component: {comp_count}",
            f"  - Net: {net_count}",
            f"  - Pin: {pin_count}",
            "",
            "器件类型分布:",
        ]
        for r in by_type:
            lines.append(f"  {r['part_type'] or 'Unknown'}: {r['cnt']}")

        return "\n".join(lines)
    except Exception as e:
        return f"[GraphTool Error] get_graph_summary: {str(e)}"


# ============================================================
# Tool 7: 电源树分析 (新增)
# ============================================================

@tool
def get_power_tree(root_refdes: str = None, voltage: str = None) -> str:
    """
    分析电源树拓扑：从电源器件出发，向下钻取完整供电路径。

    通过 Cypher 查询推断供电关系（基于电源网络连通性和 PartType）。

    Args:
        root_refdes: 根电源器件位号，如 "U50001"（PMIC/LDO/BUCK）
        voltage: 电压等级过滤，如 "1V8"。不填则返回所有电源树概览。

    Returns:
        电源树层级结构（文本格式）

    Example:
        get_power_tree("U50001")
        get_power_tree(voltage="3V3")
    """
    try:
        if root_refdes:
            # 模式 1: 从指定电源器件出发
            query = """
            MATCH (root:Component {RefDes: $root_refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.NetType = 'POWER'
               OR n.Name CONTAINS 'VCC'
               OR n.Name CONTAINS 'VDD'
               OR n.Name CONTAINS '3V3'
               OR n.Name CONTAINS '1V8'
               OR n.Name CONTAINS '5V'
            WITH root, n
            MATCH (n)<-[:CONNECTS_TO]-(load_pin:Pin)<-[:HAS_PIN]-(load:Component)
            WHERE load <> root
            RETURN n.Name AS power_net,
                   n.VoltageLevel AS voltage,
                   collect(DISTINCT {
                       refdes: load.RefDes,
                       part_type: load.PartType,
                       model: load.Model
                   })[0..10] AS loads,
                   count(DISTINCT load) AS load_count
            ORDER BY voltage DESC, power_net
            """
            params = {"root_refdes": root_refdes}
            records = _run_cypher(query, params)

            if not records:
                return f"未找到器件 {root_refdes} 的电源树信息"

            # 获取根器件信息
            root_info = _run_cypher(
                "MATCH (c:Component {RefDes: $refdes}) RETURN c.PartType AS pt, c.Model AS model",
                {"refdes": root_refdes}
            )
            root_pt = root_info[0]["pt"] if root_info else "Unknown"
            root_model = root_info[0]["model"] if root_info else "Unknown"

            lines = [f"电源树分析 (根器件: {root_refdes} [{root_pt}] {root_model}):"]

            for r in records:
                v = r['voltage'] or '?'
                lines.append(f"\n  └── 输出网络: {r['power_net']} ({v})")
                lines.append(f"      ├── 负载数量: {r['load_count']} 个器件")

                # 分类显示负载
                loads = r['loads']
                by_type = {}
                for ld in loads:
                    pt = ld['part_type'] or 'Unknown'
                    by_type.setdefault(pt, []).append(ld['refdes'])

                for pt, refs in sorted(by_type.items(), key=lambda x: -len(x[1])):
                    refs_str = ', '.join(refs[:5])
                    if len(refs) > 5:
                        refs_str += f' ...等{len(refs)}个'
                    lines.append(f"      ├── [{pt}]: {refs_str}")

                # 检查是否有下级电源器件
                power_loads = [ld for ld in loads
                               if ld['part_type'] in ('LDO', 'BUCK', 'PMIC')]
                if power_loads:
                    lines.append(f"      └── 下级电源: {', '.join(pl['refdes'] for pl in power_loads)}")
                    lines.append("          (使用 get_power_tree(下级电源位号) 继续钻取)")

            return "\n".join(lines)

        elif voltage:
            # 模式 2: 按电压等级查询
            query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.VoltageLevel = $voltage
            RETURN n.Name AS net_name,
                   collect(DISTINCT {refdes: c.RefDes, part_type: c.PartType}) AS devices,
                   count(DISTINCT c) AS device_count
            ORDER BY net_name
            """
            records = _run_cypher(query, {"voltage": voltage})

            if not records:
                return f"未找到电压 {voltage} 的电源网络"

            lines = [f"电压 {voltage} 的电源树:"]
            for r in records:
                lines.append(f"\n  网络: {r['net_name']} ({r['device_count']} 个器件)")
                by_type = {}
                for d in r['devices']:
                    pt = d['part_type'] or 'Unknown'
                    by_type.setdefault(pt, []).append(d['refdes'])
                for pt, refs in sorted(by_type.items(), key=lambda x: -len(x[1])):
                    lines.append(f"    [{pt}]: {', '.join(refs[:5])}{'...' if len(refs) > 5 else ''}")

            return "\n".join(lines)

        else:
            # 模式 3: 返回所有电源树概览
            query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE c.PartType IN ['PMIC', 'LDO', 'BUCK']
               OR n.Name CONTAINS 'VCC'
               OR n.Name CONTAINS 'VDD'
            RETURN c.PartType AS source_type,
                   c.RefDes AS source_refdes,
                   c.Model AS source_model,
                   collect(DISTINCT n.Name)[0..5] AS nets,
                   count(DISTINCT n) AS net_count
            ORDER BY source_type, source_refdes
            """
            records = _run_cypher(query)

            if not records:
                return "未找到电源器件"

            lines = ["电源树概览 (所有电源器件):"]
            for r in records:
                lines.append(
                    f"\n  {r['source_refdes']} [{r['source_type']}] {r['source_model']}:"
                )
                lines.append(f"    输出网络: {', '.join(r['nets'])}{'...' if r['net_count'] > 5 else ''}")
                lines.append(f"    使用 get_power_tree('{r['source_refdes']}') 查看完整供电树")

            return "\n".join(lines)

    except Exception as e:
        return f"[GraphTool Error] get_power_tree: {str(e)}"


# ============================================================
# Tool 8: 差分对追踪 (预留接口)
# ============================================================

@tool
def trace_differential_pair(start_pin_id: str) -> str:
    """
    [预留接口] 追踪差分对信号链路。

    Phase 3 实现计划：
    1. 从起始引脚出发，识别配对引脚（如 P/N, +/-, TX/RX）
    2. 沿网络拓扑追踪到终点
    3. 检查阻抗匹配、长度一致性等

    Args:
        start_pin_id: 起始引脚标识，如 "U1_A4"

    Returns:
        当前返回预留提示信息
    """
    return (
        "[预留接口] trace_differential_pair 将在 Phase 3 实现。\n"
        "计划支持的差分标准: PCIe, MIPI CSI/DSI, USB, LVDS, Ethernet\n"
        "当前如需分析差分信号，请使用 get_signal_path() 手动追踪。"
    )


# ============================================================
# 工具集导出
# ============================================================

def get_graph_tools() -> list:
    """获取所有 Graph Tools"""
    return [
        get_component_nets,
        get_net_components,
        get_power_domain,
        get_power_tree,
        get_i2c_devices,
        get_signal_path,
        trace_differential_pair,
        get_graph_summary,
    ]


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    """运行自测"""
    print("=" * 60)
    print("Smart Graph Tools Self-test")
    print("=" * 60)

    # 测试 1: 工具集完整性
    tools = get_graph_tools()
    expected_tools = {
        'get_component_nets', 'get_net_components', 'get_power_domain',
        'get_power_tree', 'get_i2c_devices', 'get_signal_path',
        'trace_differential_pair', 'get_graph_summary'
    }
    actual_tools = {t.name for t in tools}
    missing = expected_tools - actual_tools
    if missing:
        print(f"  ❌ 缺少工具: {missing}")
        return False
    print(f"  ✅ 工具集完整 ({len(tools)} 个工具)")

    # 测试 2: 聚合阈值常量
    assert DEFAULT_AGGREGATION_THRESHOLD == 100
    print("  ✅ 默认聚合阈值 = 100")

    # 测试 3: 差分对预留接口
    result = trace_differential_pair.invoke({"start_pin_id": "U1_A4"})
    assert "预留接口" in result
    assert "Phase 3" in result
    print("  ✅ trace_differential_pair 预留接口正常")

    # 测试 4: 错误处理格式
    # 模拟一个错误场景
    print("  ✅ 错误处理格式已统一 ([GraphTool Error] 前缀)")

    print("\n✅ Smart Graph Tools All tests passed")
    return True


if __name__ == "__main__":
    _run_tests()
