# 统一 Schema 设计

## 1. 设计目的

### 1.1 问题

当前设计中，Pydantic 数据模型和 Neo4j Schema 分散在多个文档中：

| 文档 | Schema 定义 |
|------|------------|
| Solution.md | Cypher Schema (Component, Pin, Net) |
| Agent_Core_Design.md | AgentMessage, ExecutionStep, Violation |
| Review_Rules_Design.md | ExtractedRule, RuleConfig |
| Design_Guide_Processor.md | DesignGuide, ExtractedKnowledge |

**问题**:
- Schema 定义重复
- 不一致风险
- 维护困难

### 1.2 解决方案

创建 `schemas.py` 统一管理所有数据模型：

```
┌─────────────────────────────────────────────────────────────────┐
│                        schemas.py                                │
│                    统一 Schema 中心                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │ Graph       │ │ Agent       │ │ Review      │              │
│  │ (Neo4j)     │ │ (State)     │ │ (Rules)     │              │
│  │             │ │             │ │             │              │
│  │ Component    │ │ AgentMessage│ │ RuleConfig  │              │
│  │ Pin         │ │ ExecutionStep│ │ Violation   │              │
│  │ Net         │ │ Hypothesis  │ │ Whitelist   │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 模块结构

```python
# agent_system/schemas.py

"""
统一数据模型定义

本模块统一管理所有 Pydantic 数据模型和 Neo4j Schema 定义。
确保数据模型在整个项目中保持一致。

模块划分:
- graph: Neo4j 图谱数据模型
- agent: Agent 状态机数据模型
- review: 审查规则数据模型
- knowledge: 知识库数据模型
"""

from agent_system.schemas.graph import (
    # 节点模型
    ComponentNode,
    PinNode,
    NetNode,
    DesignGuide,
    ExtractedRule,
    ReviewWhitelist,
    # 关系模型
    TopologyTriplet,
    # 约束定义
    NEO4J_CONSTRAINTS,
    NEO4J_INDEXES,
)

from agent_system.schemas.agent import (
    # 消息
    AgentMessage,
    ExecutionStep,
    # 状态
    BaseAgentState,
    ReviewState,
    DiagnosisState,
    QueryState,
    # 结果
    ReviewResult,
    DiagnosisResult,
)

from agent_system.schemas.review import (
    # 规则
    RuleTemplate,
    RuleConfig,
    # 违规
    Violation,
    ViolationEvidence,
    # 白名单
    WhitelistEntry,
)

from agent_system.schemas.knowledge import (
    # 知识
    ExtractedKnowledge,
    KnowledgeChunk,
    # 配置
    DatasheetConfig,
)

__all__ = [
    # Graph
    "ComponentNode",
    "PinNode",
    "NetNode",
    "DesignGuide",
    "ExtractedRule",
    "ReviewWhitelist",
    "TopologyTriplet",
    "NEO4J_CONSTRAINTS",
    "NEO4J_INDEXES",
    # Agent
    "AgentMessage",
    "ExecutionStep",
    "BaseAgentState",
    "ReviewState",
    "DiagnosisState",
    "QueryState",
    "ReviewResult",
    "DiagnosisResult",
    # Review
    "RuleTemplate",
    "RuleConfig",
    "Violation",
    "ViolationEvidence",
    "WhitelistEntry",
    # Knowledge
    "ExtractedKnowledge",
    "KnowledgeChunk",
    "DatasheetConfig",
]
```

---

## 3. Graph Schema (Neo4j)

```python
# agent_system/schemas/graph.py

"""
Neo4j 图谱数据模型

定义与 Neo4j 数据库对应的节点和关系模型。
"""

from typing import Optional, Literal, Annotated
from pydantic import BaseModel, Field, field_validator
import re


# ============================================
# 节点模型
# ============================================

class ComponentNode(BaseModel):
    """
    元件节点模型

    对应 Neo4j: (:Component)
    """
    refdes: str = Field(description="器件位号 (主键)")
    model: Optional[str] = Field(None, description="库模型名")
    value: Optional[str] = Field(None, description="器件参数值")
    part_type: Optional[str] = Field(None, description="器件类型: RES, CAP, IC...")
    mpn: Optional[str] = Field(None, description="厂商型号 (关联键)")

    # 从 Datasheet 提取的规格
    voltage_range: Optional[str] = Field(None, description="工作电压范围")
    max_current_ma: Optional[int] = Field(None, description="最大电流 (mA)")
    operating_temp: Optional[str] = Field(None, description="工作温度范围")
    package: Optional[str] = Field(None, description="封装类型")
    spec_source: Optional[str] = Field(None, description="规格来源")

    @field_validator("refdes")
    @classmethod
    def validate_refdes(cls, v: str) -> str:
        if not re.match(r"^[A-Z]+\d+", v):
            raise ValueError(f"Invalid RefDes format: {v}")
        return v

    def to_cypher_properties(self) -> dict:
        """转换为 Cypher 属性字典"""
        return {
            "RefDes": self.refdes,
            "Model": self.model,
            "Value": self.value,
            "PartType": self.part_type,
            "MPN": self.mpn,
            "VoltageRange": self.voltage_range,
            "MaxCurrent_mA": self.max_current_ma,
            "OperatingTemp": self.operating_temp,
            "Package": self.package,
            "SpecSource": self.spec_source,
        }


class PinNode(BaseModel):
    """
    引脚节点模型

    对应 Neo4j: (:Pin)
    """
    number: str = Field(description="引脚编号")
    component_refdes: str = Field(description="所属器件位号")
    pin_type: Literal["POWER", "SIGNAL", "GND", "NC"] = Field(
        default="SIGNAL",
        description="引脚类型"
    )

    @property
    def pin_id(self) -> str:
        """全局唯一引脚 ID"""
        return f"{self.component_refdes}_{self.number}"

    def to_cypher_properties(self) -> dict:
        return {
            "Id": self.pin_id,
            "Number": self.number,
            "Type": self.pin_type,
        }


class NetNode(BaseModel):
    """
    网络节点模型

    对应 Neo4j: (:Net)
    """
    name: str = Field(description="网络名称 (主键)")
    voltage_level: Optional[str] = Field(None, description="电压等级: 1V8, 3V3...")
    net_type: Literal["POWER", "SIGNAL", "GND", "NC"] = Field(
        default="SIGNAL",
        description="网络类型"
    )

    def to_cypher_properties(self) -> dict:
        return {
            "Name": self.name,
            "VoltageLevel": self.voltage_level,
            "NetType": self.net_type,
        }


class TopologyTriplet(BaseModel):
    """
    拓扑三元组模型

    表示 (Component) - [HAS_PIN] -> (Pin) - [CONNECTS_TO] -> (Net) 的关系
    """
    net_name: str
    component_refdes: str
    pin_number: str
    pin_type: str = "SIGNAL"
    voltage_level: str = "UNKNOWN"

    def to_cypher(self) -> tuple[str, dict]:
        """生成 Cypher MERGE 语句"""
        cypher = """
        MATCH (c:Component {RefDes: $refdes})
        MERGE (p:Pin {Id: $pin_id})
        SET p.Number = $pin_number, p.Type = $pin_type
        MERGE (c)-[:HAS_PIN]->(p)
        MERGE (n:Net {Name: $net_name})
        SET n.VoltageLevel = $voltage_level, n.NetType = 'SIGNAL'
        MERGE (p)-[:CONNECTS_TO]->(n)
        """
        params = {
            "refdes": self.component_refdes,
            "pin_id": f"{self.component_refdes}_{self.pin_number}",
            "pin_number": self.pin_number,
            "pin_type": self.pin_type,
            "net_name": self.net_name,
            "voltage_level": self.voltage_level,
        }
        return cypher, params


# ============================================
# 约束与索引定义
# ============================================

NEO4J_CONSTRAINTS = [
    "CREATE CONSTRAINT component_refdes IF NOT EXISTS FOR (c:Component) REQUIRE c.RefDes IS UNIQUE",
    "CREATE CONSTRAINT pin_id IF NOT EXISTS FOR (p:Pin) REQUIRE p.Id IS UNIQUE",
    "CREATE CONSTRAINT net_name IF NOT EXISTS FOR (n:Net) REQUIRE n.Name IS UNIQUE",
]

NEO4J_INDEXES = [
    "CREATE INDEX component_parttype IF NOT EXISTS FOR (c:Component) ON (c.PartType)",
    "CREATE INDEX component_mpn IF NOT EXISTS FOR (c:Component) ON (c.MPN)",
    "CREATE INDEX pin_type IF NOT EXISTS FOR (p:Pin) ON (p.Type)",
    "CREATE INDEX net_voltage_level IF NOT EXISTS FOR (n:Net) ON (n.VoltageLevel)",
]
```

---

## 4. Agent Schema

```python
# agent_system/schemas/agent.py

"""
Agent 状态机数据模型

定义 Agent 状态、消息和结果模型。
"""

from typing import TypedDict, Annotated, Literal, Optional, NotRequired
from pydantic import BaseModel, Field
import operator


# ============================================
# 消息模型
# ============================================

class AgentMessage(BaseModel):
    """Agent 对话消息"""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


class ExecutionStep(BaseModel):
    """执行步骤"""
    step_id: int
    step_type: Literal["thought", "action", "observation", "reasoning", "report"]
    node: str
    content: str
    metadata: dict = Field(default_factory=dict)


# ============================================
# 状态模型
# ============================================

class BaseAgentState(TypedDict):
    """基础状态 - 所有任务共享"""
    messages: Annotated[list[AgentMessage], operator.add]
    tool_call_count: int
    execution_trace: Annotated[list[ExecutionStep], operator.add]
    context: dict
    error_message: NotRequired[str]


class ReviewState(BaseAgentState):
    """审查任务状态"""
    violations: list["Violation"]
    selected_rules: list[str]
    review_scope: dict


class DiagnosisState(BaseAgentState):
    """诊断任务状态"""
    hypotheses: Annotated[list["Hypothesis"], operator.add]
    visited_nodes: Annotated[set[str], operator.add]


class QueryState(BaseAgentState):
    """查询任务状态"""
    query_result: Optional[dict]
    search_context: dict


# ============================================
# 结果模型
# ============================================

class ReviewResult(BaseModel):
    """审查结果"""
    status: Literal["success", "error"]
    total_components: int
    rules_executed: int
    violations_count: int
    errors: list["Violation"]
    warnings: list["Violation"]
    execution_trace: list[ExecutionStep]
    tool_call_count: int


class DiagnosisResult(BaseModel):
    """诊断结果"""
    status: Literal["success", "error"]
    root_cause: Optional["Hypothesis"]
    hypotheses: list["Hypothesis"]
    visited_nodes_count: int
    execution_trace: list[ExecutionStep]
    tool_call_count: int
```

---

## 5. Review Schema

```python
# agent_system/schemas/review.py

"""
审查规则数据模型

定义规则配置、违规和白名单模型。
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================
# 违规模型
# ============================================

class ViolationEvidence(BaseModel):
    """违规证据"""
    query: str
    result: dict


class Violation(BaseModel):
    """违规项"""
    id: str
    rule_id: str
    rule_name: str
    refdes: str
    net_name: Optional[str] = None
    description: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    expected: str = ""
    actual: str = ""
    evidence: list[ViolationEvidence] = Field(default_factory=list)
    whitelisted: bool = False
    whitelist_reason: Optional[str] = None


# ============================================
# 假设模型 (用于诊断)
# ============================================

class Hypothesis(BaseModel):
    """故障根因假设"""
    id: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)


# ============================================
# 规则模型
# ============================================

class RuleTemplate(BaseModel):
    """规则模板"""
    template_id: str
    name: str
    description: str
    default_severity: Literal["ERROR", "WARNING", "INFO"] = "WARNING"


class RuleConfig(BaseModel):
    """规则配置"""
    id: str
    template_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    severity: Literal["ERROR", "WARNING", "INFO"] = "WARNING"
    enabled: bool = True
    params: dict = Field(default_factory=dict)

    # 适用条件
    applicable_mpns: list[str] = Field(default_factory=list)
    applicable_voltages: list[str] = Field(default_factory=list)
    applicable_nets: list[str] = Field(default_factory=list)

    # 元数据
    version: str = "1.0.0"
    author: str = "system"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    tags: list[str] = Field(default_factory=list)


# ============================================
# 白名单模型
# ============================================

class WhitelistEntry(BaseModel):
    """白名单条目"""
    rule_id: str
    refdes: str
    status: Literal["IGNORE", "APPROVED"] = "IGNORE"
    reason: Optional[str] = None
    added_by: str = "system"
    added_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_cypher(self) -> tuple[str, dict]:
        """生成 Cypher 语句"""
        cypher = """
        MERGE (w:ReviewWhitelist {rule: $rule_id, refdes: $refdes})
        SET w.status = $status,
            w.reason = $reason,
            w.added_by = $added_by,
            w.added_at = datetime($added_at)
        """
        params = self.model_dump()
        return cypher, params
```

---

## 6. 使用示例

```python
# ============================================
# 使用示例
# ============================================

from agent_system.schemas import (
    ComponentNode,
    TopologyTriplet,
    Violation,
    RuleConfig,
)

# 1. 创建元件节点
component = ComponentNode(
    refdes="U30004",
    model="MT25QL02GCBB8E12",
    value="MT25QU256ABA8E12-0AAT",
    part_type="IC",
    mpn="MT25QU256ABA8E12-0AAT"
)

# 2. 创建拓扑三元组
triplet = TopologyTriplet(
    net_name="VDA_CSIRX0_1_1V8",
    component_refdes="U30004",
    pin_number="C4",
    pin_type="POWER",
    voltage_level="1V8"
)

# 3. 生成 Cypher
cypher, params = triplet.to_cypher()

# 4. 创建违规
violation = Violation(
    id="POWER_DECAP_U30004",
    rule_id="POWER_DECAP",
    rule_name="电源去耦电容检查",
    refdes="U30004",
    description="电源引脚缺少去耦电容"
)

# 5. 创建规则配置
rule = RuleConfig(
    id="CUSTOM_1V8_DECAP",
    template_id="decap_check",
    params={"voltage_level": "1V8", "min_count": 2},
    severity="WARNING"
)
```

---

## 7. Neo4j Schema 初始化脚本

```python
# agent_system/schemas/init_neo4j.py

"""
Neo4j Schema 初始化

确保 Neo4j 数据库的约束和索引正确创建。
"""

from neo4j import GraphDatabase
from agent_system.schemas.graph import NEO4J_CONSTRAINTS, NEO4J_INDEXES


def initialize_schema(uri: str, user: str, password: str):
    """初始化 Neo4j Schema"""
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # 创建约束
        for constraint in NEO4J_CONSTRAINTS:
            try:
                session.run(constraint)
                print(f"Constraint created: {constraint[:50]}...")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

        # 创建索引
        for index in NEO4J_INDEXES:
            try:
                session.run(index)
                print(f"Index created: {index[:50]}...")
            except Exception as e:
                if "already exists" not in str(e):
                    raise

    driver.close()
    print("Neo4j Schema initialization completed.")
```

---

## 8. 文件结构

```
agent_system/
├── __init__.py
├── schemas.py              # 【新建】统一导出
├── schemas/
│   ├── __init__.py
│   ├── graph.py          # Neo4j 图谱模型
│   ├── agent.py          # Agent 状态模型
│   ├── review.py         # 审查规则模型
│   └── knowledge.py       # 知识库模型
└── init_neo4j.py         # Schema 初始化脚本
```
