# Graph Tools 模块详细设计

## 1. 模块概述

**模块名称**: `agent_system/graph_tools.py`

**核心职责**:
- 将复杂的 Cypher 查询封装为 Python 函数（LangChain Tools）
- 实现防爆截断机制，防止 LLM 生成的大查询导致 OOM
- 提供类型安全的查询接口
- 支持只读权限的 Neo4j 连接（安全设计）

**设计原则**:
- 所有函数必须是幂等的（无写操作）
- 查询结果必须有限制
- 异常必须被妥善处理
- 必须有完整的类型提示

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Graph Tools Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    LangChain Tool Layer                         │    │
│  │  ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐   │    │
│  │  │query_component│ │trace_path     │ │find_peripherals   │   │    │
│  │  │_attributes    │ │               │ │                   │   │    │
│  │  └───────┬───────┘ └───────┬───────┘ └─────────┬─────────┘   │    │
│  │          │                  │                    │              │    │
│  │  ┌───────┴──────────────────┴────────────────────┴─────────┐  │    │
│  │  │              Tool Result Formatter                        │  │    │
│  │  │  - 类型转换 (Neo4j Node → dict)                         │  │    │
│  │  │  - 结果截断 (限制返回数量)                               │  │    │
│  │  │  - 错误包装                                              │  │    │
│  │  └───────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                    │
│  ┌─────────────────────────────────┴─────────────────────────────────┐  │
│  │                     Cypher Query Builder Layer                    │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────┐ │  │
│  │  │Component    │ │Path          │ │Network      │ │Pin       │ │  │
│  │  │Queries      │ │Queries       │ │Queries      │ │Queries   │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └──────────┘ │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│  ┌─────────────────────────────────┴─────────────────────────────────┐  │
│  │                    Neo4j Driver Layer                              │  │
│  │  ┌─────────────────────────────────────────────────────────────┐   │  │
│  │  │  READ-ONLY Session (安全隔离，防止 LLM 误操作 DELETE)      │   │  │
│  │  └─────────────────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心实现

### 3.1 模块初始化与连接管理

```python
# agent_system/graph_tools.py

"""
Graph Tools - Neo4j 图谱查询工具箱

本模块封装了所有对 Neo4j 图谱的只读查询操作。
所有函数均为幂等函数，不会修改数据库状态。

Usage:
    from agent_system.graph_tools import query_component_attributes

    # 初始化连接
    init_graph_tools(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password"
    )

    # 查询器件属性
    result = query_component_attributes("U30004")
"""

import os
import logging
from functools import wraps
from typing import Optional, Any

# Neo4j 驱动
from neo4j import GraphDatabase
from neo4j.driver import Driver, Session, Result

# LangChain Tool
from langchain_core.tools import tool, BaseTool
from langchain_core.runnables import RunnableConfig

# Pydantic 模型
from pydantic import BaseModel, Field

# ============================================
# 日志配置
# ============================================

logger = logging.getLogger(__name__)

# ============================================
# 全局连接管理
# ============================================

class GraphToolsConfig:
    """Graph Tools 全局配置"""
    _driver: Optional[Driver] = None
    _initialized: bool = False

    @classmethod
    def get_driver(cls) -> Driver:
        """获取 Neo4j 驱动实例（单例）"""
        if cls._driver is None:
            raise RuntimeError(
                "Graph Tools 未初始化。请先调用 init_graph_tools()"
            )
        return cls._driver

    @classmethod
    def init(cls, uri: str, user: str, password: str) -> None:
        """初始化 Neo4j 连接"""
        if cls._driver is not None:
            logger.warning("Graph Tools 已初始化，忽略重复初始化请求")
            return

        cls._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            # 只读事务配置
            max_connection_lifetime=3600,
            max_connection_pool_size=50,
            connection_acquisition_timeout=60,
        )
        cls._initialized = True
        logger.info(f"Graph Tools 已初始化，连接至 {uri}")

    @classmethod
    def close(cls) -> None:
        """关闭连接"""
        if cls._driver is not None:
            cls._driver.close()
            cls._driver = None
            cls._initialized = False
            logger.info("Graph Tools 连接已关闭")

    @classmethod
    def is_initialized(cls) -> bool:
        """检查是否已初始化"""
        return cls._initialized


def init_graph_tools(
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
) -> None:
    """
    初始化 Graph Tools

    Args:
        neo4j_uri: Neo4j URI，默认从环境变量 NEO4J_URI 读取
        neo4j_user: Neo4j 用户名，默认从环境变量 NEO4J_USER 读取
        neo4j_password: Neo4j 密码，默认从环境变量 NEO4J_PASSWORD 读取
    """
    from dotenv import load_dotenv

    load_dotenv()

    uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.getenv("NEO4J_USER", "neo4j")
    password = neo4j_password or os.getenv("NEO4J_PASSWORD")

    if not password:
        raise ValueError(
            "NEO4J_PASSWORD 未设置。请在 .env 文件中配置或传入参数。"
        )

    GraphToolsConfig.init(uri, user, password)
```

### 3.2 防爆截断机制

```python
# ============================================
# 防爆截断装饰器
# ============================================

class GraphResultTooLargeError(Exception):
    """
    查询结果过大异常

    当 Cypher 查询返回的结果数量超过限制时抛出此异常。
    LLM 应该根据此错误信息缩小查询范围。
    """

    def __init__(self, count: int, limit: int, suggestion: str = None):
        self.count = count
        self.limit = limit
        self.suggestion = suggestion or (
            "请在 Cypher 查询中增加 WHERE 条件限制结果数量。"
            "例如：添加属性过滤、网络名称匹配、或限制跳数。"
        )
        message = (
            f"查询结果过大（{count} 条），超出限制（{limit} 条）。"
            f"存在 OOM 风险。{self.suggestion}"
        )
        super().__init__(message)


def graph_result_truncator(max_results: int = 50):
    """
    图查询结果截断装饰器

    监控函数返回值中的记录数量。若超过 max_results，
    抛出 GraphResultTooLargeError，强制 LLM 缩小查询范围。

    Args:
        max_results: 最大允许返回的记录数

    Usage:
        @graph_result_truncator(max_results=50)
        def my_query_function(...) -> list:
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            # 检查结果数量
            if isinstance(result, list):
                count = len(result)
            elif isinstance(result, dict):
                count = len(result.get("records", []))
            elif isinstance(result, int):
                # 假设是计数结果
                count = result
            else:
                count = 1

            if count > max_results:
                raise GraphResultTooLargeError(
                    count=count,
                    limit=max_results
                )

            return result

        return wrapper
    return decorator


def handle_graph_error(func):
    """
    图查询错误处理装饰器

    捕获 Neo4j 相关异常，转换为用户友好的错误信息。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GraphResultTooLargeError:
            raise  # 直接重新抛出，不做处理
        except Exception as e:
            logger.error(f"Graph query failed: {e}")
            raise GraphQueryError(
                f"图谱查询失败: {str(e)}",
                original_error=e
            )
    return wrapper


class GraphQueryError(Exception):
    """图查询异常基类"""
    def __init__(self, message: str, original_error: Exception = None):
        self.message = message
        self.original_error = original_error
        super().__init__(message)
```

### 3.3 底层查询函数

```python
# ============================================
# 底层 Cypher 查询函数
# ============================================

def _run_read_query(cypher: str, parameters: dict = None) -> list[dict]:
    """
    执行只读 Cypher 查询

    Args:
        cypher: Cypher 查询语句
        parameters: 查询参数

    Returns:
        查询结果列表，每个元素为字典
    """
    driver = GraphToolsConfig.get_driver()

    with driver.session(database="neo4j") as session:
        # 使用只读事务
        result = session.execute_read(
            lambda tx: tx.run(cypher, parameters or {})
        )
        return [dict(record) for record in result]


def _format_node(node) -> Optional[dict]:
    """将 Neo4j Node 格式化为字典"""
    if node is None:
        return None

    result = dict(node)
    result["_id"] = str(node.id)
    result["_labels"] = list(node.labels)

    return result


def _format_path(path) -> list[dict]:
    """将 Neo4j Path 格式化为节点/关系列表"""
    elements = []

    for element in path:
        if hasattr(element, "type"):  # Relationship
            elements.append({
                "type": "relationship",
                "start": str(element.start_node.id),
                "end": str(element.end_node.id),
                "relationship_type": element.type,
                "properties": dict(element),
            })
        else:  # Node
            elements.append({
                "type": "node",
                "id": str(element.id),
                "labels": list(element.labels),
                "properties": dict(element),
            })

    return elements
```

### 3.4 核心查询工具实现

```python
# ============================================
# 器件属性查询
# ============================================

@handle_graph_error
@graph_result_truncator(max_results=1)
def query_component_attributes(refdes: str) -> dict:
    """
    查询单个器件的完整属性

    Args:
        refdes: 器件位号，例如 "U30004", "R30898"

    Returns:
        器件属性字典，包含:
        - RefDes: 位号
        - Model: 库模型名
        - Value: 器件值
        - PartType: 器件类型
        - MPN: 厂商型号
        - VoltageRange: 工作电压范围
        - MaxCurrent_mA: 最大电流
        - pins: 引脚列表

    Raises:
        GraphQueryError: 查询失败

    Example:
        >>> result = query_component_attributes("U30004")
        >>> print(result["Value"])
        "MT25QU256ABA8E12-0AAT"
    """
    cypher = """
    MATCH (c:Component {RefDes: $refdes})
    OPTIONAL MATCH (c)-[:HAS_PIN]->(p:Pin)
    OPTIONAL MATCH (p)-[:CONNECTS_TO]->(n:Net)
    RETURN
        c.RefDes AS RefDes,
        c.Model AS Model,
        c.Value AS Value,
        c.PartType AS PartType,
        c.MPN AS MPN,
        c.VoltageRange AS VoltageRange,
        c.MaxCurrent_mA AS MaxCurrent_mA,
        c.OperatingTemp AS OperatingTemp,
        c.Package AS Package,
        collect(DISTINCT {
            pin_number: p.Number,
            pin_type: p.Type,
            connected_nets: collect(n.Name)
        }) AS pins
    LIMIT 1
    """

    results = _run_read_query(cypher, {"refdes": refdes})

    if not results:
        return {
            "status": "not_found",
            "RefDes": refdes,
            "message": f"未找到器件: {refdes}"
        }

    return {
        "status": "found",
        **results[0]
    }


@handle_graph_error
@graph_result_truncator(max_results=20)
def query_components_by_type(
    part_type: str,
    limit: int = 20
) -> list[dict]:
    """
    按器件类型查询器件列表

    Args:
        part_type: 器件类型，例如 "RES", "CAP", "IC", "MCU"
        limit: 返回数量限制

    Returns:
        器件列表

    Example:
        >>> components = query_components_by_type("RES", limit=10)
        >>> for c in components:
        ...     print(c["RefDes"], c["Value"])
    """
    cypher = """
    MATCH (c:Component)
    WHERE c.PartType CONTAINS $part_type
    RETURN
        c.RefDes AS RefDes,
        c.Model AS Model,
        c.Value AS Value,
        c.PartType AS PartType
    LIMIT $limit
    """

    return _run_read_query(cypher, {
        "part_type": part_type,
        "limit": limit
    })


@handle_graph_error
@graph_result_truncator(max_results=5)
def query_component_by_mpn(mpn: str) -> list[dict]:
    """
    按厂商型号查询器件

    Args:
        mpn: 厂商型号，例如 "MT25QU256ABA8E12-0AAT"

    Returns:
        匹配的器件列表

    Example:
        >>> components = query_component_by_mpn("MT25QU256ABA8E12-0AAT")
    """
    cypher = """
    MATCH (c:Component)
    WHERE c.MPN CONTAINS $mpn
    RETURN
        c.RefDes AS RefDes,
        c.Model AS Model,
        c.Value AS Value,
        c.MPN AS MPN
    LIMIT 5
    """

    return _run_read_query(cypher, {"mpn": mpn})


# ============================================
# 路径追踪查询
# ============================================

@handle_graph_error
@graph_result_truncator(max_results=20)
def trace_shortest_path(
    source: str,
    target: str,
    avoid_nets: list[str] = None,
    max_hops: int = 10
) -> list[dict]:
    """
    追踪两颗器件之间的最短信号路径

    使用 Neo4j shortestPath 算法查找两点间的连接路径。
    可选排除 GND、VCC 等公共网络。

    Args:
        source: 源器件位号，例如 "J60001"
        target: 目标器件位号，例如 "U60214"
        avoid_nets: 需要排除的网络名称列表，例如 ["GND", "VCC", "DGND"]
        max_hops: 最大跳数限制

    Returns:
        路径信息，包含节点和边的列表

    Raises:
        GraphResultTooLargeError: 路径过长
        GraphQueryError: 查询失败

    Example:
        >>> path = trace_shortest_path("J60001", "U60214")
        >>> for node in path:
        ...     if node["type"] == "node":
        ...         print(node["properties"].get("RefDes"))
    """
    avoid_nets = avoid_nets or ["GND", "VCC", "DGND", "AGND"]

    # 构建排除条件
    avoid_pattern = "|".join(avoid_nets)

    cypher = f"""
    MATCH (source:Component {{RefDes: $source}})
    MATCH (target:Component {{RefDes: $target}})

    // 查找最短路径，排除公共网络
    CALL {{
        WITH source, target
        MATCH path = shortestPath(
            (source)-[:HAS_PIN|CONNECTS_TO*1..{max_hops}]-(target)
        )
        // 过滤掉包含排除网络的路径
        WHERE NONE(n IN nodes(path) WHERE n:Net AND n.Name =~ '{avoid_pattern}')
        RETURN path
    }}

    // 如果没找到排他路径，尝试普通最短路径作为备选
    WITH source, target,
         (CASE WHEN NOT EXISTS(path) THEN
             shortestPath((source)-[:HAS_PIN|CONNECTS_TO*1..{max_hops}]-(target))
          ELSE path END) AS fallback_path

    RETURN fallback_path AS path
    LIMIT 1
    """

    results = _run_read_query(cypher, {
        "source": source,
        "target": target,
    })

    if not results or results[0].get("path") is None:
        return {
            "status": "no_path",
            "message": f"未找到从 {source} 到 {target} 的路径"
        }

    path = results[0]["path"]
    elements = _format_path(path)

    return {
        "status": "found",
        "source": source,
        "target": target,
        "path": elements,
        "node_count": sum(1 for e in elements if e["type"] == "node"),
        "edge_count": sum(1 for e in elements if e["type"] == "relationship"),
    }


@handle_graph_error
@graph_result_truncator(max_results=30)
def find_connected_components(
    refdes: str,
    depth: int = 1,
    relationship_type: str = None
) -> list[dict]:
    """
    查找与指定器件直接/间接连接的所有器件

    Args:
        refdes: 起始器件位号
        depth: 连接深度（1 = 直接邻居）
        relationship_type: 关系类型过滤，例如 "HAS_PIN"

    Returns:
        连接的器件列表

    Example:
        >>> # 查找 U30004 直接连接的器件
        >>> connected = find_connected_components("U30004", depth=1)
    """
    cypher = f"""
    MATCH (c:Component {{RefDes: $refdes}})

    // 使用可变深度查询
    MATCH path = (c)-[:HAS_PIN|CONNECTS_TO*1..{depth}]-(other:Component)

    WITH DISTINCT other, path, c

    // 计算连接距离（跳数）
    WITH other, c,
         length([x IN relationships(path) WHERE type(x) = 'CONNECTS_TO']) AS distance

    RETURN
        other.RefDes AS RefDes,
        other.Model AS Model,
        other.PartType AS PartType,
        other.Value AS Value,
        distance AS hops
    ORDER BY hops, other.RefDes
    """

    return _run_read_query(cypher, {
        "refdes": refdes,
    })


# ============================================
# 周边器件查询
# ============================================

@handle_graph_error
@graph_result_truncator(max_results=50)
def find_connected_peripherals(
    center_refdes: str,
    radius: int = 2,
    peripheral_types: list[str] = None
) -> list[dict]:
    """
    查找特定 IC 周边的被动器件

    常用于电源引脚去耦电容检查、ESD 保护器件检查等场景。

    Args:
        center_refdes: 中心 IC 位号
        radius: 搜索半径（跳数）
        peripheral_types: 过滤的器件类型，例如 ["CAP", "RES"]，None 表示全部

    Returns:
        被动器件列表，包含器件信息和连接的网络

    Example:
        >>> caps = find_connected_peripherals("U30004", radius=1, peripheral_types=["CAP"])
        >>> for cap in caps:
        ...     print(f"{cap['RefDes']}: {cap['Value']} @ {cap['connected_nets']}")
    """
    # 构建类型过滤条件
    type_filter = ""
    if peripheral_types:
        types_str = ", ".join([f"'{t}'" for t in peripheral_types])
        type_filter = f"AND p.PeripheralType IN [{types_str}]"

    cypher = f"""
    MATCH (center:Component {{RefDes: $refdes}})

    // 查找周边器件（通过引脚-网络-引脚连接）
    MATCH (center)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(net:Net)<-[:CONNECTS_TO]-(peri_pin:Pin)<-[:HAS_PIN]-(peri:Component)

    // 过滤：排除自身
    WHERE center <> peri

    // 过滤：周边器件类型
    {type_filter}

    WITH DISTINCT center, peri, net, peri_pin

    RETURN
        peri.RefDes AS RefDes,
        peri.Model AS Model,
        peri.Value AS Value,
        peri.PartType AS PartType,
        collect(DISTINCT net.Name) AS connected_nets,
        collect(DISTINCT peri_pin.Number) AS connected_pins
    ORDER BY peri.PartType, peri.RefDes
    """

    return _run_read_query(cypher, {
        "refdes": center_refdes,
    })


# ============================================
# 网络查询
# ============================================

@handle_graph_error
@graph_result_truncator(max_results=20)
def find_net_by_name(
    net_pattern: str,
    exact_match: bool = False,
    include_hidden: bool = False
) -> list[dict]:
    """
    按名称模式搜索网络

    Args:
        net_pattern: 网络名称或正则模式，例如 "USB", "1V8.*"
        exact_match: 是否精确匹配，False 则使用 CONTAINS
        include_hidden: 是否包含隐藏网络（如 N* 开头的自动命名网络）

    Returns:
        匹配的网络列表

    Example:
        >>> # 查找所有 1.8V 电源网络
        >>> nets = find_net_by_name("1V8")
        >>>
        >>> # 查找 USB 相关网络
        >>> usb_nets = find_net_by_name("USB.*", exact_match=False)
    """
    if exact_match:
        where_clause = "n.Name = $pattern"
    else:
        where_clause = "n.Name CONTAINS $pattern OR n.Name =~ $pattern"

    if not include_hidden:
        where_clause += " AND NOT n.Name =~ 'N.*'"

    cypher = f"""
    MATCH (n:Net)
    WHERE {where_clause}

    // 获取连接到该网络的器件
    OPTIONAL MATCH (p:Pin)-[:CONNECTS_TO]->(n)
    OPTIONAL MATCH (c:Component)-[:HAS_PIN]->(p)

    RETURN
        n.Name AS Name,
        n.VoltageLevel AS VoltageLevel,
        n.NetType AS NetType,
        count(DISTINCT c) AS component_count,
        collect(DISTINCT c.RefDes) AS components
    ORDER BY component_count DESC, Name
    """

    return _run_read_query(cypher, {
        "pattern": net_pattern,
    })


@handle_graph_error
@graph_result_truncator(max_results=50)
def find_nets_by_voltage(voltage_level: str) -> list[dict]:
    """
    按电压等级查找网络

    Args:
        voltage_level: 电压等级，例如 "1V8", "3V3", "5V0"

    Returns:
        该电压等级的所有网络
    """
    cypher = """
    MATCH (n:Net)
    WHERE n.VoltageLevel = $voltage_level

    OPTIONAL MATCH (p:Pin)-[:CONNECTS_TO]->(n)
    OPTIONAL MATCH (c:Component)-[:HAS_PIN]->(p)

    RETURN
        n.Name AS Name,
        n.NetType AS NetType,
        count(DISTINCT c) AS component_count
    ORDER BY Name
    """

    return _run_read_query(cypher, {
        "voltage_level": voltage_level,
    })


# ============================================
# 引脚查询
# ============================================

@handle_graph_error
@graph_result_truncator(max_results=20)
def find_pins_by_type(
    refdes: str,
    pin_types: list[str] = None
) -> list[dict]:
    """
    查找器件的特定类型引脚

    Args:
        refdes: 器件位号
        pin_types: 引脚类型列表，例如 ["POWER", "GND", "SIGNAL"]

    Returns:
        引脚列表

    Example:
        >>> # 查找 IC 的所有电源引脚
        >>> power_pins = find_pins_by_type("U30004", pin_types=["POWER"])
    """
    if pin_types:
        types_str = ", ".join([f"'{t}'" for t in pin_types])
        type_filter = f"AND p.Type IN [{types_str}]"
    else:
        type_filter = ""

    cypher = f"""
    MATCH (c:Component {{RefDes: $refdes}})-[:HAS_PIN]->(p:Pin)
    WHERE true {type_filter}

    OPTIONAL MATCH (p)-[:CONNECTS_TO]->(n:Net)

    RETURN
        p.Number AS pin_number,
        p.Type AS pin_type,
        n.Name AS net_name,
        n.VoltageLevel AS voltage_level
    ORDER BY p.Number
    """

    return _run_read_query(cypher, {
        "refdes": refdes,
    })


# ============================================
# 统计查询
# ============================================

@handle_graph_error
def get_graph_statistics() -> dict:
    """
    获取图谱统计信息

    用于系统健康检查和调试。

    Returns:
        统计信息字典
    """
    cypher = """
    MATCH (c:Component)
    OPTIONAL MATCH (c)-[:HAS_PIN]->(p:Pin)
    OPTIONAL MATCH (p)-[:CONNECTS_TO]->(n:Net)
    OPTIONAL MATCH (c)-[:SUBJECT_TO]->(r:ReviewRule)

    RETURN
        count(DISTINCT c) AS total_components,
        count(DISTINCT p) AS total_pins,
        count(DISTINCT n) AS total_nets,
        count(DISTINCT r) AS total_rules,
        count(DISTINCT c.MPN) AS components_with_mpn,
        count(DISTINCT n.VoltageLevel) AS voltage_domains
    """

    results = _run_read_query(cypher, {})
    return results[0] if results else {}


@handle_graph_error
def get_component_count_by_type() -> list[dict]:
    """
    按类型统计器件数量

    Returns:
        器件类型统计列表
    """
    cypher = """
    MATCH (c:Component)
    RETURN
        c.PartType AS PartType,
        count(*) AS count
    ORDER BY count DESC
    """

    return _run_read_query(cypher, {})
```

---

## 4. LangChain Tool 封装

```python
# ============================================
# LangChain Tool 定义
# ============================================

@tool
def query_component_tool(refdes: str) -> str:
    """
    查询器件属性信息。

    输入器件位号，返回该器件的完整属性信息，包括型号、参数值、MPN、
    引脚数量和连接的网络列表。

    Args:
        refdes: 器件位号，例如 "U30004", "R30898", "C70050"

    Returns:
        器件属性信息字符串

    使用示例:
        query_component_tool("U30004")  # 查询 Flash 芯片属性
        query_component_tool("R30898")  # 查询电阻属性
    """
    result = query_component_attributes(refdes)

    if result["status"] == "not_found":
        return f"未找到器件 {refdes}"

    pins_info = "\n  ".join([
        f"Pin {p['pin_number']} ({p['pin_type']}) -> {', '.join(p['connected_nets'])}"
        for p in result.get("pins", [])
        if p["pin_number"]
    ])

    return f"""
器件: {result['RefDes']}
型号: {result.get('Model', 'N/A')}
参数值: {result.get('Value', 'N/A')}
器件类型: {result.get('PartType', 'N/A')}
厂商型号(MPN): {result.get('MPN', 'N/A')}
工作电压: {result.get('VoltageRange', 'N/A')}
最大电流: {result.get('MaxCurrent_mA', 'N/A')} mA
引脚列表:
  {pins_info or '无'}
""".strip()


@tool
def trace_path_tool(source: str, target: str) -> str:
    """
    追踪两个器件之间的信号路径。

    查找从源器件到目标器件的最短连接路径。
    默认排除 GND、VCC 等公共网络。

    Args:
        source: 源器件位号
        target: 目标器件位号

    Returns:
        路径信息字符串

    使用示例:
        trace_path_tool("J60001", "U60214")  # 追踪 USB 连接路径
        trace_path_tool("U30004", "C70050")  # 追踪电源滤波路径
    """
    result = trace_shortest_path(source, target)

    if result["status"] == "no_path":
        return f"未找到从 {source} 到 {target} 的连接路径"

    # 格式化路径
    path_nodes = [
        e["properties"].get("RefDes") or e["properties"].get("Name")
        for e in result["path"]
        if e["type"] == "node"
    ]

    path_str = " → ".join(path_nodes)

    return f"""
信号路径: {source} → {target}
路径长度: {result['node_count']} 个节点, {result['edge_count']} 条边

路径详情:
{path_str}
""".strip()


@tool
def find_peripherals_tool(center_refdes: str, radius: int = 1) -> str:
    """
    查找器件周边的被动器件。

    查找连接到指定 IC 电源/信号引脚的所有被动器件（电阻、电容、电感等）。
    常用于检查去耦电容、ESD 保护等。

    Args:
        center_refdes: 中心 IC 位号
        radius: 搜索半径（默认 1），表示直接连接的器件

    Returns:
        周边器件列表字符串

    使用示例:
        find_peripherals_tool("U30004", radius=1)  # 查找直接连接的器件
    """
    peripherals = find_connected_peripherals(center_refdes, radius=radius)

    if not peripherals:
        return f"未找到与 {center_refdes} 连接的器件"

    lines = [f"与 {center_refdes} 连接的器件 (共 {len(peripherals)} 个):\n"]

    for p in peripherals:
        lines.append(
            f"  • {p['RefDes']} ({p['PartType']}) {p.get('Value', '')}"
            f"\n    连接网络: {', '.join(p.get('connected_nets', []))}"
        )

    return "\n".join(lines)


@tool
def search_net_tool(net_pattern: str) -> str:
    """
    搜索网络。

    根据名称模式搜索网络，返回网络信息和连接的器件列表。

    Args:
        net_pattern: 网络名称或关键词，例如 "USB", "1V8", "GND"

    Returns:
        网络信息字符串

    使用示例:
        search_net_tool("1V8")  # 搜索 1.8V 电源网络
        search_net_tool("USB")  # 搜索 USB 相关网络
    """
    nets = find_net_by_name(net_pattern)

    if not nets:
        return f"未找到包含 '{net_pattern}' 的网络"

    lines = [f"搜索 '{net_pattern}' 结果 (共 {len(nets)} 个网络):\n"]

    for n in nets[:10]:  # 限制显示数量
        lines.append(
            f"  • {n['Name']}"
            f"\n    电压等级: {n.get('VoltageLevel', 'N/A')}"
            f"\n    连接器件 ({n.get('component_count', 0)}): {', '.join(n.get('components', [])[:5])}"
            f"{'...' if n.get('component_count', 0) > 5 else ''}\n"
        )

    return "\n".join(lines)


# ============================================
# 工具注册
# ============================================

def get_graph_tools() -> list[BaseTool]:
    """
    获取所有图谱查询工具

    Returns:
        LangChain Tool 列表

    Usage:
        from langchain.agents import AgentExecutor, create_react_agent
        from langchain_openai import ChatOpenAI

        tools = get_graph_tools()
        llm = ChatOpenAI(model="qwen-max")
        agent = create_react_agent(llm, tools)
        executor = AgentExecutor(agent=agent, tools=tools)
    """
    return [
        query_component_tool,
        trace_path_tool,
        find_peripherals_tool,
        search_net_tool,
    ]
```

---

## 5. 完整模块代码

```python
# agent_system/graph_tools.py

"""
Graph Tools - Neo4j 图谱查询工具箱

封装所有对 Neo4j 图谱的只读查询操作，提供类型安全的 Python 接口
和 LangChain Tool 封装。

Author: Hardware AI Team
Version: 1.0.0
"""

__version__ = "1.0.0"

# 导出主要接口
__all__ = [
    # 初始化
    "init_graph_tools",
    "GraphToolsConfig",
    # 底层查询
    "query_component_attributes",
    "query_components_by_type",
    "query_component_by_mpn",
    "trace_shortest_path",
    "find_connected_components",
    "find_connected_peripherals",
    "find_net_by_name",
    "find_nets_by_voltage",
    "find_pins_by_type",
    "get_graph_statistics",
    "get_component_count_by_type",
    # 异常
    "GraphQueryError",
    "GraphResultTooLargeError",
    # LangChain Tools
    "get_graph_tools",
    "query_component_tool",
    "trace_path_tool",
    "find_peripherals_tool",
    "search_net_tool",
]
```

---

## 6. 使用示例

### 6.1 基础使用

```python
# 1. 初始化连接
from agent_system.graph_tools import init_graph_tools

init_graph_tools(
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="your_password"
)

# 2. 查询器件属性
from agent_system.graph_tools import query_component_attributes

result = query_component_attributes("U30004")
print(result["Value"])  # "MT25QU256ABA8E12-0AAT"

# 3. 追踪信号路径
from agent_system.graph_tools import trace_shortest_path

path = trace_shortest_path("J60001", "U60214")
print(f"路径节点数: {path['node_count']}")

# 4. 查找周边器件
from agent_system.graph_tools import find_connected_peripherals

caps = find_connected_peripherals("U30004", peripheral_types=["CAP"])
for cap in caps:
    print(f"{cap['RefDes']}: {cap['Value']}")
```

### 6.2 与 LangChain Agent 集成

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain_openai import ChatOpenAI
from agent_system.graph_tools import get_graph_tools

# 初始化
init_graph_tools()

# 创建 Agent
tools = get_graph_tools()
llm = ChatOpenAI(model="qwen-max", temperature=0)

agent = create_react_agent(llm, tools)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 执行查询
result = executor.invoke({
    "input": "查找 U30004 的所有电源引脚和连接的电容"
})
```

### 6.3 错误处理

```python
from agent_system.graph_tools import (
    GraphResultTooLargeError,
    GraphQueryError,
)

try:
    # 这个查询会返回过多结果
    result = find_net_by_name("V")  # 太宽泛
except GraphResultTooLargeError as e:
    print(f"查询结果过大: {e.count} > {e.limit}")
    print(f"建议: {e.suggestion}")
except GraphQueryError as e:
    print(f"查询失败: {e.message}")
```

---

## 7. Neo4j 索引要求

为保证查询性能，以下索引必须在 Neo4j 中创建：

```cypher
// 唯一性约束
CREATE CONSTRAINT refdes_unique IF NOT EXISTS
FOR (c:Component) REQUIRE c.RefDes IS UNIQUE;

CREATE CONSTRAINT pin_id_unique IF NOT EXISTS
FOR (p:Pin) REQUIRE p.Id IS UNIQUE;

CREATE CONSTRAINT net_name_unique IF NOT EXISTS
FOR (n:Net) REQUIRE n.Name IS UNIQUE;

// 性能索引
CREATE INDEX component_parttype IF NOT EXISTS FOR (c:Component) ON (c.PartType);
CREATE INDEX component_mpn IF NOT EXISTS FOR (c:Component) ON (c.MPN);
CREATE INDEX component_model IF NOT EXISTS FOR (c:Component) ON (c.Model);
CREATE INDEX pin_type IF NOT EXISTS FOR (p:Pin) ON (p.Type);
CREATE INDEX net_voltage_level IF NOT EXISTS FOR (n:Net) ON (n.VoltageLevel);
CREATE INDEX net_name IF NOT EXISTS FOR (n:Net) ON (n.Name);
```

---

## 8. 安全考虑

1. **只读连接**: 所有查询使用 `session.execute_read()`，确保无法执行写操作
2. **结果限制**: 所有查询都有 `LIMIT`，防止数据过大
3. **参数化查询**: 使用 `$parameter` 语法，防止 Cypher 注入
4. **异常隔离**: 异常不会泄露数据库内部信息
