"""
Graph Tools - Neo4j 图谱查询工具集

封装 Cypher 查询为 LangChain Tools，供 Agent 调用。
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
        return f"查询失败: {e}"


# ============================================================
# Tool 2: 查找网络的所有连接器件
# ============================================================

@tool
def get_net_components(net_name: str) -> str:
    """
    查询指定网络的的所有连接器件和引脚。

    Args:
        net_name: 网络名称，如 "VDD_1V8", "I2C_SDA"

    Returns:
        该网络的所有连接器件信息

    Example:
        get_net_components("VDD_1V8")
    """
    query = """
    MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
    RETURN c.RefDes AS refdes,
           c.PartType AS part_type,
           c.Value AS value,
           p.Number AS pin_number,
           p.Type AS pin_type
    ORDER BY c.RefDes, p.Number
    """
    try:
        records = _run_cypher(query, {"net_name": net_name})
        if not records:
            return f"未找到网络 {net_name}"

        lines = [f"网络 '{net_name}' 的连接器件:"]
        for r in records:
            lines.append(
                f"  {r['refdes']} ({r['part_type']}, {r['value']}) "
                f"- Pin {r['pin_number']} ({r['pin_type']})"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


# ============================================================
# Tool 3: 电源域分析（找电源轨道的上游/下游器件）
# ============================================================

@tool
def get_power_domain(voltage_level: str = None) -> str:
    """
    分析电源域：查找同一电压等级下的所有器件。

    Args:
        voltage_level: 电压等级，如 "1V8", "3V3"。不填则返回所有电源网络。

    Returns:
        电源域内的器件列表

    Example:
        get_power_domain("1V8")
    """
    if voltage_level:
        query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.VoltageLevel = $voltage_level
        RETURN n.Name AS net_name,
               n.VoltageLevel AS voltage,
               collect({refdes: c.RefDes, pin: p.Number}) AS devices
        ORDER BY n.Name
        """
        params = {"voltage_level": voltage_level}
    else:
        query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.NetType IN ['POWER', 'SIGNAL'] AND n.VoltageLevel IS NOT NULL
        RETURN n.VoltageLevel AS voltage,
               collect(DISTINCT n.Name) AS nets,
               collect(DISTINCT c.RefDes) AS components
        ORDER BY n.VoltageLevel
        """
        params = {}

    try:
        records = _run_cypher(query, params)
        if not records:
            return f"未找到电源域信息"

        if voltage_level:
            lines = [f"电源域 {voltage_level} 的器件:"]
            for r in records:
                lines.append(f"  网络: {r['net_name']}")
                for d in r["devices"]:
                    lines.append(f"    - {d['refdes']} (Pin {d['pin']})")
        else:
            lines = ["所有电源域概览:"]
            for r in records:
                lines.append(
                    f"  {r['voltage']}: {len(r['nets'])} 个网络, "
                    f"{len(r['components'])} 个器件"
                )
                lines.append(f"    Nets: {', '.join(r['nets'][:5])}{'...' if len(r['nets']) > 5 else ''}")

        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


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
        return f"查询失败: {e}"


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
        return f"查询失败: {e}"


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
        return f"查询失败: {e}"


# ============================================================
# 工具集导出
# ============================================================

def get_graph_tools() -> list:
    """获取所有 Graph Tools"""
    return [
        get_component_nets,
        get_net_components,
        get_power_domain,
        get_i2c_devices,
        get_signal_path,
        get_graph_summary,
    ]


if __name__ == "__main__":
    # 快速验证
    print(get_graph_summary())
    print()
    print(get_component_nets("U30004"))
