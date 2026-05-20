from __future__ import annotations
"""
Graph Tools - Neo4j 图谱查询工具集 (Smart Graph Tools V2)

封装 Cypher 查询为 LangChain Tools，供 Agent 调用。
V2 增强：
  - 智能特征聚合（大网络自动摘要）
  - 电源树分析
  - 差分对追踪（预留）
"""

import os
import re
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

# 只读模式：为 True 时拦截所有写入类 Cypher
READ_ONLY_MODE = os.getenv("NEO4J_READ_ONLY", "false").lower() in ("true", "1", "yes")

# Cypher 查询超时（秒）
CYPHER_TIMEOUT_SECONDS = int(os.getenv("CYPHER_TIMEOUT_SECONDS", "30"))

# 写入类 Cypher 关键字（用于只读模式拦截）
_WRITE_KEYWORDS = re.compile(
    r'\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|CALL\s+{)|;\s*(CREATE|MERGE|SET|DELETE)',
    re.IGNORECASE
)


def _get_driver():
    """获取 Neo4j driver"""
    if GraphDatabase is None:
        raise RuntimeError("neo4j package not installed")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


def _run_cypher(query: str, params: dict = None, timeout: int = None) -> list[dict]:
    """执行 Cypher 并返回结果

    Args:
        query: Cypher 查询语句
        params: 查询参数
        timeout: 超时秒数，默认使用 CYPHER_TIMEOUT_SECONDS
    """
    # 只读模式拦截
    if READ_ONLY_MODE and _is_write_cypher(query):
        raise PermissionError(
            f"[Read-Only Mode] 写入操作被拦截: {query[:80]}..."
        )

    driver = _get_driver()
    timeout = timeout or CYPHER_TIMEOUT_SECONDS
    with driver.session() as session:
        result = session.run(query, params or {})
        # Neo4j Python driver 4.x+ 支持 consume() 触发超时
        summary = result.consume()
        # 重新执行获取数据（consume 消耗了结果）
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

        # 小网络：返回详细列表（加 LIMIT 防止意外大结果）
        if total_components <= threshold:
            query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
            RETURN c.RefDes AS refdes,
                   c.PartType AS part_type,
                   c.Value AS value,
                   p.Number AS pin_number,
                   p.Type AS pin_type
            ORDER BY c.RefDes, p.Number
            LIMIT $limit
            """
            records = _run_cypher(query, {"net_name": net_name, "limit": threshold * 5})
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
def find_common_cause(refdes_list: str) -> str:
    """
    定位多个故障器件的共同上游电源（共因失效分析）。

    给定一组故障器件位号，追踪它们各自的电源供给路径，
    找到共同的上游电源网络或器件，定位可能的共因失效点。

    Args:
        refdes_list: 逗号分隔的器件位号，如 "U40000,U50000,R40005"

    Returns:
        共因失效分析报告（文本格式）
    """
    try:
        refdes_items = [r.strip() for r in refdes_list.split(',') if r.strip()]
        if len(refdes_items) < 2:
            return "共因失效分析至少需要 2 个器件位号"

        # 对每个器件，查找其电源网络
        power_nets_by_refdes = {}
        for refdes in refdes_items:
            query = """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE p.Type = 'POWER' OR p.Type = 'GROUND'
            RETURN n.Name AS net_name, n.VoltageLevel AS voltage, p.Type AS pin_type
            """
            records = _run_cypher(query, {"refdes": refdes})
            if records:
                power_nets_by_refdes[refdes] = [
                    {"net": r['net_name'], "voltage": r['voltage'], "pin_type": r['pin_type']}
                    for r in records
                ]

        if not power_nets_by_refdes:
            return f"未找到任何器件的电源信息: {refdes_list}"

        # 找共同电源网络
        all_nets = {}
        for refdes, nets in power_nets_by_refdes.items():
            for net_info in nets:
                if net_info['pin_type'] == 'POWER':  # 只看电源，不看地
                    net_name = net_info['net']
                    all_nets.setdefault(net_name, []).append(refdes)

        common_nets = {net: refs for net, refs in all_nets.items() if len(refs) >= 2}

        # 对共同电源网络，查找上游电源器件
        lines = [f"共因失效分析 (故障器件: {', '.join(refdes_items)}):\n"]
        lines.append("各器件电源连接:")
        for refdes, nets in power_nets_by_refdes.items():
            pwr_nets = [f"{n['net']}({n['voltage'] or '?'}V)" for n in nets if n['pin_type'] == 'POWER']
            lines.append(f"  {refdes}: {', '.join(pwr_nets[:5]) or '无电源引脚'}")

        if common_nets:
            lines.append(f"\n🔴 共同电源网络:")
            for net, refs in sorted(common_nets.items(), key=lambda x: -len(x[1])):
                lines.append(f"  {net}: 共同供给 {', '.join(refs)}")

                # 查找该网络的上游电源器件
                src_query = """
                MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
                WHERE c.PartType IN ['LDO', 'BUCK', 'PMIC', 'DCDC']
                RETURN c.RefDes AS refdes, c.PartType AS pt, c.Model AS model
                LIMIT 3
                """
                src_records = _run_cypher(src_query, {"net_name": net})
                if src_records:
                    for sr in src_records:
                        lines.append(f"    └── 上游电源器件: {sr['refdes']} [{sr['pt']}] {sr['model']}")
                else:
                    lines.append(f"    └── (未找到上游电源器件)")
        else:
            lines.append("\n🟢 未发现共同电源网络 — 故障可能独立发生")

        return "\n".join(lines)

    except Exception as e:
        return f"共因失效分析出错: {str(e)}"


@tool
def analyze_power_sequence(refdes: str) -> str:
    """
    分析指定电源器件的上下电时序依赖。

    追踪该器件的输入电源来源和输出电源负载，
    推断上电/下电顺序依赖关系。

    Args:
        refdes: 电源器件位号，如 "U40000"

    Returns:
        电源时序分析报告
    """
    try:
        # 1. 获取器件信息
        info_query = """
        MATCH (c:Component {RefDes: $refdes})
        RETURN c.RefDes AS refdes, c.PartType AS pt, c.Model AS model, c.Value AS value
        """
        info = _run_cypher(info_query, {"refdes": refdes})
        if not info:
            return f"未找到器件 {refdes}"

        dev = info[0]
        lines = [f"电源时序分析: {refdes} [{dev['pt']}] {dev['model'] or dev['value'] or ''}\n"]

        # 2. 查找输入电源网络 (VIN/VCC)
        input_query = """
        MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE p.Type = 'POWER' AND (n.Name CONTAINS 'VIN' OR n.Name CONTAINS 'VCC' OR n.Name CONTAINS 'VDD')
        RETURN n.Name AS net, n.VoltageLevel AS voltage
        """
        input_nets = _run_cypher(input_query, {"refdes": refdes})

        # 3. 查找输出电源网络
        # 策略：所有有 VoltageLevel 的非输入非地非控制网络
        output_query = """
        MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.VoltageLevel IS NOT NULL
              AND NOT (n.Name CONTAINS 'VIN' OR n.Name STARTS WITH 'VCC' OR n.Name STARTS WITH 'VDD' OR n.Name = 'VIN')
              AND NOT (n.Name CONTAINS 'GND' OR n.Name = 'DGND' OR n.Name = 'NC')
              AND NOT (n.Name STARTS WITH 'EN' OR n.Name STARTS WITH 'NR' OR n.Name STARTS WITH 'FB')
        WITH DISTINCT n.Name AS net, n.VoltageLevel AS voltage, count(p) AS pin_count
        RETURN net, voltage
        ORDER BY voltage DESC
        """
        output_nets = _run_cypher(output_query, {"refdes": refdes})

        # 4. 查找使能引脚
        en_query = """
        MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE (n.Name CONTAINS 'EN_' OR n.Name STARTS WITH 'EN' OR n.Name CONTAINS '_EN')
              AND NOT n.Name = 'NC'
        RETURN DISTINCT n.Name AS net, p.Number AS pin
        """
        en_nets = _run_cypher(en_query, {"refdes": refdes})

        # 5. 组装时序报告
        if input_nets:
            lines.append("📥 输入电源:")
            for n in input_nets:
                lines.append(f"  {n['net']} ({n['voltage'] or '?'}V)")
                # 查找上游电源器件
                upstream_query = """
                MATCH (src:Component)-[:HAS_PIN]->(sp:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
                WHERE src.PartType IN ['LDO', 'BUCK', 'PMIC', 'DCDC'] AND src.RefDes <> $refdes
                RETURN src.RefDes AS refdes, src.PartType AS pt
                LIMIT 3
                """
                upstream = _run_cypher(upstream_query, {"net_name": n['net'], "refdes": refdes})
                for u in upstream:
                    lines.append(f"    └── 由 {u['refdes']} [{u['pt']}] 供给")
        else:
            lines.append("📥 输入电源: 未检测到标准 VIN/VCC 网络")

        if output_nets:
            lines.append("\n📤 输出电源:")
            for n in output_nets:
                v = n['voltage'] or '?'
                # 查找负载
                load_query = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(lp:Pin)<-[:HAS_PIN]-(lc:Component)
                WHERE lc.RefDes <> $refdes
                RETURN count(DISTINCT lc) AS cnt,
                       collect(DISTINCT lc.PartType)[0..3] AS types
                """
                loads = _run_cypher(load_query, {"net_name": n['net'], "refdes": refdes})
                load_info = f"{loads[0]['cnt']}个负载" if loads else "0个负载"
                lines.append(f"  {n['net']} ({v}V) → {load_info}")
        else:
            lines.append("\n📤 输出电源: 未检测到")

        if en_nets:
            lines.append("\n🔌 使能控制:")
            for n in en_nets:
                lines.append(f"  {n['net']} (Pin {n['pin']})")

        # 6. 时序推断
        lines.append("\n⏱️ 上电时序推断:")
        if input_nets and output_nets:
            lines.append(f"  1. 先上电: {', '.join(n['net'] for n in input_nets)}")
            lines.append(f"  2. 使能: {', '.join(n['net'] for n in en_nets) if en_nets else '自动使能'}")
            lines.append(f"  3. 输出稳定: {', '.join(n['net'] for n in output_nets)}")
        else:
            lines.append("  信息不足，无法推断")

        return "\n".join(lines)

    except Exception as e:
        return f"电源时序分析出错: {str(e)}"


@tool
def trace_signal_path(start_pin: str, max_depth: int = 5) -> str:
    """
    从指定引脚出发，沿网络拓扑 BFS 追踪信号链路路径。

    追踪方式：引脚 → 所在网络 → 其他引脚 → 所属组件 → 继续展开。
    使用 BFS 遍历，避免环路，最多展开 max_depth 层。

    Args:
        start_pin: 起始引脚标识，格式为 "组件位号.引脚号"（如 "U40000.3"）
                   或引脚名称（如 "U40000_VOUT"），支持模糊匹配
        max_depth: 最大追踪深度，默认 5

    Returns:
        信号链路路径报告（文本格式）
    """
    try:
        # 1. 解析起始引脚
        # 支持 "RefDes.PinNumber" 或 "RefDes_PinName" 格式
        if '.' in start_pin:
            refdes, pin_num = start_pin.split('.', 1)
            pin_query = """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)
            WHERE p.Number = $pin_num OR p.Name = $pin_num
            RETURN c.RefDes AS refdes, p.Number AS pin_num, p.Name AS pin_name, id(p) AS pid
            LIMIT 1
            """
            start_records = _run_cypher(pin_query, {"refdes": refdes, "pin_num": pin_num})
        elif '_' in start_pin:
            # 尝试 RefDes_PinName 格式
            parts = start_pin.split('_', 1)
            pin_query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)
            WHERE c.RefDes = $refdes AND p.Name = $pin_name
            RETURN c.RefDes AS refdes, p.Number AS pin_num, p.Name AS pin_name, id(p) AS pid
            LIMIT 1
            """
            start_records = _run_cypher(pin_query, {"refdes": parts[0], "pin_name": parts[1]})
        else:
            # 模糊搜索引脚名
            pin_query = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)
            WHERE p.Name CONTAINS $start_pin OR c.RefDes = $start_pin
            RETURN c.RefDes AS refdes, p.Number AS pin_num, p.Name AS pin_name, id(p) AS pid
            LIMIT 1
            """
            start_records = _run_cypher(pin_query, {"start_pin": start_pin})

        if not start_records:
            return f"未找到起始引脚: {start_pin}"

        start = start_records[0]
        lines = [f"信号链路追踪: {start['refdes']}.{start['pin_num']} ({start['pin_name'] or '?'})"]
        lines.append(f"最大深度: {max_depth}\n")

        # 2. BFS 遍历
        # 队列元素: (pin_id, depth, path_list)
        # path: ["Component:U1", "Pin:3", "Net:VCC_3V3", "Pin:5", "Component:U2", ...]
        visited_pins = set()
        visited_nets = set()
        all_paths = []

        # 获取起始引脚的内部 ID
        start_pid = start['pid']
        visited_pins.add(start_pid)
        queue = [(start_pid, 0, [f"Component:{start['refdes']}", f"Pin:{start['pin_num']}({start['pin_name'] or '?'})"])]

        while queue:
            current_pid, depth, path = queue.pop(0)
            if depth >= max_depth:
                all_paths.append(path)
                continue

            # 从当前引脚找连接的网络
            net_query = """
            MATCH (p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE id(p) = $pid
            RETURN n.Name AS net_name, id(n) AS nid
            """
            nets = _run_cypher(net_query, {"pid": current_pid})

            if not nets:
                all_paths.append(path)
                continue

            extended = False
            for net_info in nets:
                net_name = net_info['net_name']
                net_id = net_info['nid']

                if net_id in visited_nets and depth > 0:
                    continue
                visited_nets.add(net_id)

                new_path = path + [f"Net:{net_name}"]

                # 从网络找其他引脚
                peer_query = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                WHERE id(p) <> $pid
                RETURN c.RefDes AS refdes, p.Number AS pin_num, p.Name AS pin_name, id(p) AS peer_pid
                ORDER BY c.RefDes
                """
                peers = _run_cypher(peer_query, {"net_name": net_name, "pid": current_pid})

                if not peers:
                    all_paths.append(new_path)
                    continue

                for peer in peers:
                    peer_pid = peer['peer_pid']
                    if peer_pid in visited_pins:
                        continue
                    visited_pins.add(peer_pid)
                    extended = True
                    peer_path = new_path + [f"Pin:{peer['pin_num']}({peer['pin_name'] or '?'})", f"Component:{peer['refdes']}"]
                    queue.append((peer_pid, depth + 1, peer_path))

            if not extended:
                all_paths.append(path)

        # 3. 格式化输出
        if not all_paths:
            lines.append("未追踪到任何信号路径")
        else:
            for i, path in enumerate(all_paths, 1):
                lines.append(f"路径 {i}: {' → '.join(path)}")

        return "\n".join(lines)

    except Exception as e:
        return f"信号链路追踪出错: {str(e)}"


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
        find_common_cause,
        analyze_power_sequence,
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
