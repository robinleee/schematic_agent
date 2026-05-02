# Smart Graph Tools 升级规格说明

## 任务概述

升级 `agent_system/graph_tools.py`，实现 PRD V5.0 要求的 Smart Graph Tools：
1. **智能特征聚合**：`get_net_components` 对大网络（>100 节点）做 Cypher 层聚合摘要
2. **电源树工具**：新增 `get_power_tree()` 支持从电源器件向下钻取完整供电拓扑
3. **差分对追踪**：预留 `trace_differential_pair()` 接口

## 具体需求

### 1. get_net_components 智能聚合

**当前问题**：对 GND/VCC 等大网络返回全量节点列表，可能数千条，LLM 上下文溢出。

**PRD 要求**：
> "若节点数量 > 阈值，在 Cypher 层聚合统计（如：'该网络包含 120 个电容，3 个电阻'）。返回聚合摘要而非截断列表。"

**实现要求**：

```python
@tool
def get_net_components(net_name: str, threshold: int = 100) -> str:
    """
    查询指定网络的所有连接器件和引脚。
    
    智能行为：
    - 如果连接节点数 <= threshold，返回详细列表（保持现有格式）
    - 如果连接节点数 > threshold，返回聚合摘要（Cypher 层聚合）
    """
```

**聚合查询 Cypher**：

```cypher
// 第一步：计数
MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
RETURN count(DISTINCT c) AS total_components,
       count(p) AS total_pins

// 第二步（如果超过阈值）：聚合摘要
MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $net_name})
RETURN c.PartType AS part_type,
       count(DISTINCT c) AS component_count,
       count(p) AS pin_count,
       collect(DISTINCT c.RefDes)[0..5] AS examples
ORDER BY component_count DESC
```

**返回格式（聚合模式）**：

```
网络 'GND' 的连接摘要 (共 3241 个器件, 4123 个引脚):
  按类型聚合:
    PASSIVE    : 2890 个器件 (示例: C1, C2, C3, C4, C5...)
    IC         :  234 个器件 (示例: U1, U2, U3, U4, U5...)
    CONNECTOR  :   56 个器件 (示例: J1, J2, J3, J4, J5...)
    ...
  提示: 该网络节点数超过阈值(100)，已启用聚合模式。
        如需查看该网络上的特定器件类型，请指定 PartType 查询。
```

---

### 2. 新增 get_power_tree() 工具

**PRD 要求**：
> "升级 get_power_tree()，基于强化的 [:POWERED_BY] 关系支持从 LDO 向下钻取完整供电树拓扑。"

**实现要求**：

由于当前 ETL 阶段尚未建立 `[:POWERED_BY]` 关系，本工具需要：
1. 通过 Cypher 查询推断供电关系（基于电源网络连通性和 PartType）
2. 返回层级化的电源树结构

```python
@tool
def get_power_tree(root_refdes: str = None, voltage: str = None) -> str:
    """
    分析电源树拓扑。
    
    Args:
        root_refdes: 根电源器件位号，如 "U50001"（PMIC/LDO/BUCK）
        voltage: 电压等级过滤，如 "1V8"
        
    Returns:
        电源树层级结构（文本或 JSON）
        
    两种查询模式：
    1. 指定 root_refdes: 从该器件出发，向下遍历所有供电路径
    2. 指定 voltage: 返回该电压等级下的所有电源网络及负载
    """
```

**查询逻辑（基于推断）**：

```cypher
// 模式 1: 从指定 PMIC/LDO 出发
MATCH (root:Component {RefDes: $root_refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
WHERE n.NetType = 'POWER' OR n.Name CONTAINS 'VCC' OR n.Name CONTAINS 'VDD'
WITH root, n
MATCH (n)<-[:CONNECTS_TO]-(load_pin:Pin)<-[:HAS_PIN]-(load:Component)
WHERE load <> root
RETURN n.Name AS power_net,
       n.VoltageLevel AS voltage,
       collect(DISTINCT {refdes: load.RefDes, part_type: load.PartType}) AS loads
ORDER BY voltage, power_net
```

**返回格式**：

```
电源树分析 (根器件: U50001 TPS5430 [BUCK]):
  └── 输出网络: VCC_3V3 (3.3V)
      ├── 负载: U60001 [MCU] (Pin 1, 2)
      ├── 负载: U60002 [FPGA] (Pin A1, A2)
      └── 下级电源: U50002 [LDO]
          └── 输出网络: VCC_1V8 (1.8V)
              ├── 负载: U60001 [MCU] (Pin 5)
              └── 负载: U70001 [SENSOR] (Pin 3)
```

---

### 3. 预留 trace_differential_pair() 接口

**PRD 要求**：
> "预留 trace_differential_pair(start_pin) 工具，专用于未来排查 PCIe、MIPI 等差分走线的一致性。"

**实现要求**：

先实现框架和注释，逻辑待 Phase 3 补齐：

```python
@tool
def trace_differential_pair(start_pin_id: str) -> str:
    """
    [预留接口] 追踪差分对信号链路。
    
    Phase 3 实现：
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
        "计划支持的差分标准: PCIe, MIPI, USB, LVDS, Ethernet\n"
        "当前如需分析差分信号，请使用 get_signal_path() 手动追踪。"
    )
```

---

### 4. 其他改进

#### 4.1 get_power_domain 增强

当前 `get_power_domain` 按电压等级聚合统计，但缺少具体器件列表。增加 `detail` 参数：

```python
@tool
def get_power_domain(voltage_level: str = None, detail: bool = False) -> str:
    """
    增强版电源域分析。
    
    Args:
        voltage_level: 电压等级，如 "1V8"
        detail: 是否返回详细器件列表（默认 False，返回聚合摘要）
    """
```

#### 4.2 错误处理增强

所有工具统一包装异常，返回结构化错误信息：

```python
try:
    records = _run_cypher(query, params)
except Exception as e:
    return f"[GraphTool Error] {tool_name}: {str(e)}"
```

---

## 验收标准

1. **get_net_components**:
   - 对小网络（如 I2C_SDA）返回详细列表（格式不变）
   - 对大网络（如 GND）返回聚合摘要，包含 PartType 分布和示例器件
   - 聚合模式明确提示用户已启用聚合

2. **get_power_tree**:
   - 能正确识别 PMIC/LDO/BUCK → 电源网络 → 负载器件 的层级关系
   - 支持通过 root_refdes 和 voltage 两种模式查询
   - 返回格式清晰，包含电压等级和器件类型

3. **trace_differential_pair**:
   - 已注册为可用工具
   - 返回友好的预留提示信息

4. **单元测试**:
   - 提供 self-test 代码，验证聚合逻辑和电源树推断
   - 至少覆盖 3 种网络类型（小信号网络、大电源网络、I2C 网络）

## 注意事项

1. **不要修改现有工具的签名**（参数名和类型），除非明确说明
2. **向后兼容**：`get_net_components` 的默认行为对小网络保持不变
3. **Neo4j 数据依赖**：工具运行需要 Neo4j 已注入数据（由 ETL + load_to_neo4j 完成）
4. **PartType 标准化依赖**：`get_power_tree` 依赖标准化的 PartType（PASSIVE, PMIC, BUCK, LDO 等）

## 交付物

1. 修改后的 `agent_system/graph_tools.py`
2. 单元测试通过输出
