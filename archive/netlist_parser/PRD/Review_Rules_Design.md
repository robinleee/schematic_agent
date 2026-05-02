# Review Rules 架构优化方案

## 1. 当前设计的问题分析

### 1.1 规则硬编码的问题

```python
# 当前设计 - 规则参数硬编码
REVIEW_RULES = {
    "POWER_DECAP": {
        "params": {
            "min_decap_per_power_pin": 1,      # ❌ 硬编码
            "recommended_values": ["0.1uF"],   # ❌ 硬编码
            "power_pin_types": ["POWER"],       # ❌ 硬编码
        }
    }
}
```

**问题**:
- 不同电压等级需要不同参数 (1.8V vs 3.3V)
- 不同器件类型需要不同规则 (Flash vs MCU vs FPGA)
- 不同客户可能有不同的设计规范
- 规则更新需要修改代码和重新部署

### 1.2 规则与代码耦合的问题

| 问题 | 影响 |
|------|------|
| 规则参数分散在代码中 | 难以统一管理 |
| 新增规则需要改代码 | 开发成本高 |
| 规则无法版本化 | 无法追溯变更 |
| 无法动态调整规则 | 缺乏灵活性 |

---

## 2. 推荐方案：三层规则引擎

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        三层规则引擎架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 1: 规则模板层 (Template)                  │   │
│  │                                                                   │   │
│  │  定义通用的检查逻辑模板，参数化配置                                 │   │
│  │                                                                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │ decap_chk  │  │ pullup_chk  │  │  esd_chk    │  ...         │   │
│  │  │ (去耦检查) │  │ (上拉检查)  │  │ (ESD检查)   │              │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 2: 规则配置层 (Config)                   │   │
│  │                                                                   │   │
│  │  定义规则实例，支持参数覆盖和多维度配置                            │   │
│  │                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────┐   │   │
│  │  │ rules.yaml / rules.json                                  │   │   │
│  │  │                                                           │   │   │
│  │  │ - id: POWER_1V8_DECAP                                    │   │   │
│  │  │   template: decap_check                                  │   │   │
│  │  │   params:                                                │   │   │
│  │  │     voltage_level: "1V8"                                 │   │   │
│  │  │     min_count: 2                                         │   │   │
│  │  │     required_values: ["0.1uF", "1uF"]                    │   │   │   │
│  │  │     applicable_parts: ["FLASH", "DRAM", "SOC"]           │   │   │
│  │  │   severity: WARNING                                       │   │   │
│  │  │                                                           │   │   │
│  │  │ - id: I2C_STD_PULLUP                                     │   │   │
│  │  │   template: pullup_check                                  │   │   │
│  │  │   params:                                                │   │   │
│  │  │     min_ohm: 2200                                        │   │   │   │
│  │  │     max_ohm: 10000                                       │   │   │
│  │  │   severity: ERROR                                         │   │   │
│  │  └───────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 3: 知识规则层 (Knowledge)                 │   │
│  │                                                                   │   │
│  │  从 Datasheet/行业标准自动提取规则（AI 驱动）                      │   │
│  │                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────┐   │   │
│  │  │ Datasheet: MT25QU256ABA8E12                              │   │   │
│  │  │                                                           │   │   │
│  │  │ Extracted Rules:                                         │   │   │
│  │  │ {                                                         │   │   │
│  │  │   "decap_1V8": { "count": 4, "values": ["0.1uF"] },     │   │   │
│  │  │   "decap_3V3": { "count": 2, "values": ["0.1uF", "4.7uF"]}│   │   │
│  │  │ }                                                         │   │   │
│  │  └───────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 详细设计

### 3.1 规则模板定义

```python
# agent_system/review_engine/templates.py

"""
规则模板定义

每个模板定义一类检查的通用逻辑，通过参数实例化具体规则。
"""

from abc import ABC, abstractmethod
from typing import Any, Callable
from dataclasses import dataclass
import re


@dataclass
class RuleContext:
    """规则执行上下文"""
    neo4j_driver: Any
    graph_tools: Any
    knowledge_router: Any


@dataclass
class RuleTemplate(ABC):
    """
    规则模板抽象基类

    所有规则模板必须实现 check() 方法。
    模板接收参数配置，返回违规列表。
    """

    template_id: str
    name: str
    description: str
    default_severity: str = "WARNING"

    @abstractmethod
    def check(
        self,
        params: dict,
        context: RuleContext
    ) -> list["Violation"]:
        """
        执行规则检查

        Args:
            params: 规则参数
            context: 执行上下文

        Returns:
            违规列表
        """
        pass

    def validate_params(self, params: dict) -> bool:
        """
        验证参数是否合法

        Returns:
            True 表示参数合法
        """
        return True


# ============================================
# 内置规则模板
# ============================================

class DecapCheckTemplate(RuleTemplate):
    """
    电源去耦电容检查模板

    参数:
        voltage_level: 电压等级 (如 "1V8", "3V3")
        min_count: 最少电容数量
        required_values: 要求的具体容值
        applicable_parts: 适用的器件类型
        net_patterns: 网络名称模式
    """

    template_id = "decap_check"
    name = "电源去耦电容检查"
    description = "检查电源引脚是否配置了足够的去耦电容"

    def check(self, params: dict, context: RuleContext) -> list["Violation"]:
        violations = []

        voltage_level = params.get("voltage_level", "")
        min_count = params.get("min_count", 1)
        required_values = params.get("required_values", [])
        applicable_parts = params.get("applicable_parts", ["IC", "MCU", "FPGA"])
        net_patterns = params.get("net_patterns", [voltage_level])

        driver = context.neo4j_driver

        # 1. 查找目标电压网络
        cypher = """
        MATCH (n:Net)
        WHERE n.VoltageLevel = $voltage_level
           OR ANY(pattern IN $patterns WHERE n.Name CONTAINS pattern)
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            nets = list(session.run(cypher, {
                "voltage_level": voltage_level,
                "patterns": net_patterns
            }))

        for record in nets:
            net_name = record["net_name"]

            # 2. 查找该网络的 IC 器件
            cypher = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType IN $part_types
            RETURN DISTINCT c.RefDes AS refdes, c.PartType AS part_type
            """

            with driver.session() as session:
                ics = list(session.run(cypher, {
                    "net_name": net_name,
                    "part_types": applicable_parts
                }))

            for ic in ics:
                refdes = ic["refdes"]

                # 3. 检查去耦电容数量
                cypher = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                WHERE c.PartType CONTAINS 'CAP'
                RETURN c.RefDes AS cap_refdes, c.Value AS cap_value
                """

                with driver.session() as session:
                    caps = list(session.run(cypher, {"net_name": net_name}))

                if len(caps) < min_count:
                    cap_values = [c["cap_value"] for c in caps]
                    violations.append(Violation(
                        id=f"{self.template_id}_{refdes}_{net_name}",
                        rule_id=params.get("rule_id", self.template_id),
                        rule_name=self.name,
                        severity=params.get("severity", self.default_severity),
                        refdes=refdes,
                        net_name=net_name,
                        description=f"{voltage_level} 电源网络 {net_name} 的去耦电容数量不足",
                        expected=f"至少 {min_count} 个电容",
                        actual=f"找到 {len(caps)} 个: {', '.join(cap_values) if cap_values else '无'}",
                    ))

        return violations


class PullupCheckTemplate(RuleTemplate):
    """
    上拉电阻检查模板

    参数:
        net_patterns: 网络名称模式 (如 ["I2C", "SCL", "SDA"])
        min_ohm: 最小阻值
        max_ohm: 最大阻值
        recommended_values: 推荐阻值列表
    """

    template_id = "pullup_check"
    name = "上拉电阻检查"
    description = "检查总线是否配置了合理阻值的上拉电阻"

    def _parse_resistance(self, value: str) -> float:
        """解析电阻值 (返回欧姆)"""
        if not value:
            return 0
        value = value.upper().strip()
        if "K" in value:
            return float(re.sub(r'[^\d.]', '', value)) * 1000
        elif "M" in value:
            return float(re.sub(r'[^\d.]', '', value)) * 1000000
        return float(re.sub(r'[^\d.]', '', value) or 0)

    def check(self, params: dict, context: RuleContext) -> list["Violation"]:
        violations = []

        net_patterns = params.get("net_patterns", [])
        min_ohm = params.get("min_ohm", 1000)
        max_ohm = params.get("max_ohm", 47000)

        driver = context.neo4j_driver

        # 查找目标网络
        cypher = """
        MATCH (n:Net)
        WHERE ANY(pattern IN $patterns WHERE n.Name CONTAINS pattern)
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            nets = list(session.run(cypher, {"patterns": net_patterns}))

        for record in nets:
            net_name = record["net_name"]

            # 查找上拉电阻
            cypher = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType CONTAINS 'RES'
            RETURN c.RefDes AS res_refdes, c.Value AS res_value
            """

            with driver.session() as session:
                resistors = list(session.run(cypher, {"net_name": net_name}))

            has_valid_pullup = False
            for res in resistors:
                resistance = self._parse_resistance(res["res_value"])
                if min_ohm <= resistance <= max_ohm:
                    has_valid_pullup = True
                    break

            if not has_valid_pullup:
                res_values = [r["res_value"] for r in resistors]
                violations.append(Violation(
                    id=f"{self.template_id}_{net_name}",
                    rule_id=params.get("rule_id", self.template_id),
                    rule_name=self.name,
                    severity=params.get("severity", self.default_severity),
                    refdes="总线",
                    net_name=net_name,
                    description=f"网络 {net_name} 未检测到合理阻值的上拉电阻",
                    expected=f"电阻应在 {min_ohm/1000:.1f}kΩ - {max_ohm/1000:.1f}kΩ",
                    actual=f"找到: {', '.join(res_values) if res_values else '无上拉电阻'}",
                ))

        return violations


class ESDCheckTemplate(RuleTemplate):
    """
    ESD 保护检查模板

    参数:
        interface_types: 接口类型列表
        connector_prefixes: 连接器前缀
        max_capacitance_pf: 最大允许电容 (pF)
    """

    template_id = "esd_check"
    name = "ESD 保护检查"
    description = "检查高速接口是否配置了合适的 ESD 保护"

    def check(self, params: dict, context: RuleContext) -> list["Violation"]:
        violations = []

        interface_types = params.get("interface_types", [])
        connector_prefixes = params.get("connector_prefixes", ["J"])
        max_cap_pf = params.get("max_capacitance_pf", 5)

        driver = context.neo4j_driver

        # 查找连接器
        cypher = """
        MATCH (c:Component)
        WHERE c.RefDes STARTS WITH $prefix
           OR c.PartType CONTAINS $interface
        RETURN c.RefDes AS refdes, c.PartType AS part_type
        """

        with driver.session() as session:
            connectors = list(session.run(cypher, {
                "prefix": connector_prefixes[0] if connector_prefixes else "J",
                "interface": "CON"
            }))

        for conn in connectors:
            refdes = conn["refdes"]

            # 查找信号引脚
            cypher = """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE p.Type = 'SIGNAL'
            RETURN p.Number AS pin_number, n.Name AS net_name
            """

            with driver.session() as session:
                signal_pins = list(session.run(cypher, {"refdes": refdes}))

            for pin in signal_pins:
                net_name = pin["net_name"]

                # 检查 ESD 保护
                cypher = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                WHERE c.PartType CONTAINS 'ESD' OR c.PartType CONTAINS 'TVS'
                RETURN c.RefDes AS esd_refdes, c.Value AS esd_value
                """

                with driver.session() as session:
                    esd_devices = list(session.run(cypher, {"net_name": net_name}))

                if not esd_devices:
                    violations.append(Violation(
                        id=f"{self.template_id}_{refdes}_{net_name}",
                        rule_id=params.get("rule_id", self.template_id),
                        rule_name=self.name,
                        severity=params.get("severity", self.default_severity),
                        refdes=refdes,
                        net_name=net_name,
                        description=f"接口 {refdes} 的信号网络 {net_name} 缺少 ESD 保护",
                        expected=f"应配置 ESD/TVS 保护器件 (电容 < {max_cap_pf}pF)",
                        actual="未找到 ESD 保护器件",
                    ))

        return violations


# ============================================
# 模板注册表
# ============================================

class TemplateRegistry:
    """规则模板注册表"""

    _templates: dict[str, RuleTemplate] = {}

    @classmethod
    def register(cls, template: RuleTemplate):
        """注册模板"""
        cls._templates[template.template_id] = template

    @classmethod
    def get(cls, template_id: str) -> RuleTemplate:
        """获取模板"""
        return cls._templates.get(template_id)

    @classmethod
    def list_templates(cls) -> list[dict]:
        """列出所有模板"""
        return [
            {
                "id": t.template_id,
                "name": t.name,
                "description": t.description,
            }
            for t in cls._templates.values()
        ]


# 注册内置模板
TemplateRegistry.register(DecapCheckTemplate())
TemplateRegistry.register(PullupCheckTemplate())
TemplateRegistry.register(ESDCheckTemplate())
```

### 3.2 规则配置层

```python
# agent_system/review_engine/config.py

"""
规则配置管理

支持 YAML/JSON 配置文件，定义规则实例。
"""

import yaml
import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


class RuleConfig(BaseModel):
    """规则配置模型"""
    id: str = Field(description="规则唯一ID")
    template_id: str = Field(description="引用的模板ID")
    name: Optional[str] = Field(None, description="规则名称（覆盖模板）")
    description: Optional[str] = Field(None, description="规则描述")
    severity: str = Field("WARNING", description="严重级别")
    enabled: bool = Field(True, description="是否启用")

    # 参数配置
    params: dict = Field(default_factory=dict, description="模板参数")

    # 适用条件
    applicable_nets: Optional[list[str]] = Field(None, description="适用网络")
    applicable_parts: Optional[list[str]] = Field(None, description="适用器件")
    applicable_voltages: Optional[list[str]] = Field(None, description="适用电压")

    # 元数据
    version: str = Field("1.0.0", description="规则版本")
    author: str = Field("system", description="创建人")
    created_at: Optional[str] = Field(None, description="创建时间")
    tags: list[str] = Field(default_factory=list, description="标签")


class RuleConfigManager:
    """
    规则配置管理器

    负责加载、解析、验证规则配置。
    """

    def __init__(self, config_path: str = None):
        self.config_path = config_path
        self._rules: dict[str, RuleConfig] = {}
        self._rule_versions: dict[str, list[dict]] = {}  # 版本历史

        if config_path:
            self.load_from_file(config_path)

    def load_from_file(self, path: str):
        """从文件加载规则配置"""
        path = Path(path)

        if path.suffix in [".yaml", ".yml"]:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        elif path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}")

        # 解析规则列表
        rules_data = data.get("rules", [])
        for rule_data in rules_data:
            rule = RuleConfig(**rule_data)
            self._rules[rule.id] = rule

        # 记录版本历史
        self._rule_versions[path.stem] = rules_data.copy()

    def add_rule(self, rule: RuleConfig):
        """添加规则"""
        # 验证模板存在
        template = TemplateRegistry.get(rule.template_id)
        if not template:
            raise ValueError(f"Unknown template: {rule.template_id}")

        # 验证参数
        if not template.validate_params(rule.params):
            raise ValueError(f"Invalid params for template: {rule.template_id}")

        rule.created_at = datetime.now().isoformat()
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str):
        """移除规则"""
        self._rules.pop(rule_id, None)

    def get_rule(self, rule_id: str) -> Optional[RuleConfig]:
        """获取规则"""
        return self._rules.get(rule_id)

    def list_rules(self, enabled_only: bool = False) -> list[RuleConfig]:
        """列出所有规则"""
        rules = list(self._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        return rules

    def save_to_file(self, path: str):
        """保存配置到文件"""
        rules_data = [rule.model_dump() for rule in self._rules.values()]

        data = {
            "version": "1.0",
            "rules": rules_data,
        }

        path = Path(path)
        if path.suffix in [".yaml", ".yml"]:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        elif path.suffix == ".json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def merge_rules(self, other_rules: list[RuleConfig], strategy: str = "override"):
        """
        合并规则

        Args:
            other_rules: 要合并的规则列表
            strategy: 合并策略
                - "override": 新规则覆盖旧规则
                - "keep": 保留旧规则
                - "merge": 合并参数
        """
        for rule in other_rules:
            if rule.id in self._rules and strategy == "keep":
                continue

            if rule.id in self._rules and strategy == "merge":
                existing = self._rules[rule.id]
                # 合并参数
                existing.params.update(rule.params)
            else:
                self._rules[rule.id] = rule
```

### 3.3 规则配置示例 (YAML)

```yaml
# config/rules/automotive_rules.yaml

version: "1.0"
rules:
  # ========================================
  # 汽车电子专用规则
  # ========================================

  - id: AUTOMOTIVE_POWER_12V_DECAP
    template_id: decap_check
    name: "汽车 12V 电源去耦检查"
    description: "汽车电子 12V 电源轨道的去耦要求"
    severity: ERROR
    params:
      voltage_level: "12V"
      min_count: 2
      required_values:
        - "0.1uF"
        - "10uF"
      applicable_parts:
        - "IC"
        - "MCU"
        - "GATEWAY"
    tags:
      - "automotive"
      - "power"
      - "12V"

  - id: AUTOMOTIVE_CAN_PULLUP
    template_id: pullup_check
    name: "CAN 总线上拉电阻检查"
    description: "汽车 CAN 总线必须配置 120Ω 终端电阻"
    severity: ERROR
    params:
      net_patterns:
        - "CAN"
        - "H"
        - "L"
      min_ohm: 100
      max_ohm: 150
      recommended_values:
        - "120"
    tags:
      - "automotive"
      - "can"
      - "bus"

  # ========================================
  # 消费电子规则
  # ========================================

  - id: CONSUMER_USB_ESD
    template_id: esd_check
    name: "USB 接口 ESD 检查"
    description: "USB 3.0 接口需要低电容 ESD 保护"
    severity: WARNING
    params:
      interface_types:
        - "USB"
      connector_prefixes:
        - "J"
      max_capacitance_pf: 0.5  # USB 3.0 严格要求
    tags:
      - "consumer"
      - "usb"
      - "esd"

  - id: CONSUMER_DDR_DECAP
    template_id: decap_check
    name: "DDR 电源去耦检查"
    description: "DDR 内存接口的去耦要求"
    severity: ERROR
    params:
      voltage_level: "1V8"
      min_count: 4
      required_values:
        - "0.1uF"
        - "0.022uF"
      applicable_parts:
        - "DDR"
        - "DRAM"
        - "MEMORY"
      net_patterns:
        - "VDDQ"
        - "1V8"
    tags:
      - "consumer"
      - "ddr"
      - "memory"
```

### 3.4 AI 驱动的规则提取

```python
# agent_system/review_engine/knowledge_extractor.py

"""
知识驱动的规则提取

从 Datasheet 中自动提取设计规则。
"""

import re
from typing import Optional
from pydantic import BaseModel


class ExtractedRule(BaseModel):
    """提取的规则"""
    rule_type: str
    voltage_level: Optional[str] = None
    min_count: Optional[int] = None
    values: list[str] = []
    description: str
    confidence: float = 0.0
    source: str


class KnowledgeRuleExtractor:
    """
    知识规则提取器

    使用 LLM 从 Datasheet 内容中提取设计规则。
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def extract_rules_from_datasheet(
        self,
        datasheet_content: str,
        mpn: str
    ) -> list[ExtractedRule]:
        """
        从 Datasheet 内容中提取设计规则

        Args:
            datasheet_content: Datasheet 文本内容
            mpn: 器件型号

        Returns:
            提取的规则列表
        """
        prompt = f"""
你是电子元器件设计规则提取专家。

请从以下 Datasheet 内容中提取硬件设计规则：

型号: {mpn}
内容:
{datasheet_content[:8000]}

请提取以下类型的规则：
1. 电源去耦电容要求 (Decoupling Capacitor Requirements)
2. 上下拉电阻要求 (Pull-up/Pull-down Resistor Requirements)
3. ESD 保护要求 (ESD Protection Requirements)
4. 电源上电时序要求 (Power Sequencing)

输出格式 (JSON):
{{
  "rules": [
    {{
      "rule_type": "decap_check | pullup_check | esd_check | power_sequencing",
      "voltage_level": "电压等级 (如 1V8, 3V3)",
      "min_count": 最少数量,
      "values": ["要求的值列表"],
      "description": "规则描述",
      "confidence": 置信度 (0-1)
    }}
  ]
}}

只输出 JSON，不要有其他内容。
"""

        response = self.llm.invoke(prompt)

        # 解析 JSON
        try:
            import json
            data = json.loads(response.content)
            rules = [
                ExtractedRule(
                    rule_type=r["rule_type"],
                    voltage_level=r.get("voltage_level"),
                    min_count=r.get("min_count"),
                    values=r.get("values", []),
                    description=r.get("description", ""),
                    confidence=r.get("confidence", 0.5),
                    source=f"Datasheet:{mpn}"
                )
                for r in data.get("rules", [])
            ]
            return rules
        except Exception as e:
            print(f"解析规则失败: {e}")
            return []

    def extract_and_save_rules(
        self,
        datasheet_content: str,
        mpn: str,
        neo4j_driver
    ):
        """
        提取规则并保存到 Neo4j

        Args:
            datasheet_content: Datasheet 内容
            mpn: 器件型号
            neo4j_driver: Neo4j 驱动
        """
        rules = self.extract_rules_from_datasheet(datasheet_content, mpn)

        for rule in rules:
            if rule.confidence < 0.7:
                continue  # 跳过低置信度规则

            # 生成规则 ID
            rule_id = f"KB_{mpn}_{rule.rule_type}_{rule.voltage_level or 'generic'}"

            # 保存到 Neo4j
            cypher = """
            MERGE (r:ReviewRule {
                id: $rule_id
            })
            SET r.template_id = $template_id,
                r.voltage_level = $voltage_level,
                r.params = $params,
                r.description = $description,
                r.confidence = $confidence,
                r.source = $source,
                r.mpn = $mpn
            """

            # 确定模板 ID
            template_mapping = {
                "decap_check": "decap_check",
                "pullup_check": "pullup_check",
                "esd_check": "esd_check",
            }
            template_id = template_mapping.get(rule.rule_type, "generic_check")

            with neo4j_driver.session() as session:
                session.run(cypher, {
                    "rule_id": rule_id,
                    "template_id": template_id,
                    "voltage_level": rule.voltage_level,
                    "params": json.dumps({
                        "voltage_level": rule.voltage_level,
                        "min_count": rule.min_count,
                        "required_values": rule.values,
                    }),
                    "description": rule.description,
                    "confidence": rule.confidence,
                    "source": rule.source,
                    "mpn": mpn,
                })

        print(f"从 {mpn} 提取并保存 {len(rules)} 条规则")
        return rules
```

### 3.5 规则引擎整合

```python
# agent_system/review_engine/engine.py

"""
规则引擎主入口

整合模板、配置、知识提取，提供统一的审查接口。
"""

from typing import Optional
from agent_system.review_engine.templates import TemplateRegistry, RuleTemplate, RuleContext
from agent_system.review_engine.config import RuleConfigManager, RuleConfig
from agent_system.review_engine.knowledge_extractor import KnowledgeRuleExtractor


class ReviewRuleEngine:
    """
    灵活的规则审查引擎

    支持:
    - 模板 + 配置模式
    - 知识自动提取规则
    - 规则版本管理
    """

    def __init__(
        self,
        config_path: str = None,
        neo4j_driver = None,
        llm_client = None,
    ):
        self.config_manager = RuleConfigManager(config_path)
        self.knowledge_extractor = KnowledgeRuleExtractor(llm_client) if llm_client else None

        self._context = RuleContext(
            neo4j_driver=neo4j_driver,
            graph_tools=None,
            knowledge_router=None,
        )

    def load_rules_from_config(self, config_path: str):
        """从配置文件加载规则"""
        self.config_manager.load_from_file(config_path)

    def load_rules_from_neo4j(self):
        """从 Neo4j 加载知识规则"""
        if not self._context.neo4j_driver:
            return

        cypher = """
        MATCH (r:ReviewRule)
        WHERE r.template_id IS NOT NULL
        RETURN r.id AS rule_id,
               r.template_id AS template_id,
               r.params AS params,
               r.description AS description
        """

        with self._context.neo4j_driver.session() as session:
            results = list(session.run(cypher))

        for record in results:
            params = json.loads(record["params"]) if record["params"] else {}

            rule = RuleConfig(
                id=record["rule_id"],
                template_id=record["template_id"],
                params=params,
            )
            self.config_manager.add_rule(rule)

    def run_rules(
        self,
        rule_ids: list[str] = None,
        enabled_only: bool = True,
    ) -> list["Violation"]:
        """
        执行规则检查

        Args:
            rule_ids: 要执行的规则 ID，None 表示全部
            enabled_only: 是否只执行启用的规则

        Returns:
            违规列表
        """
        all_violations = []

        # 获取规则列表
        if rule_ids:
            rules = [self.config_manager.get_rule(rid) for rid in rule_ids]
            rules = [r for r in rules if r]
        else:
            rules = self.config_manager.list_rules(enabled_only=enabled_only)

        # 执行每个规则
        for rule in rules:
            violations = self._execute_rule(rule)
            all_violations.extend(violations)

        return all_violations

    def _execute_rule(self, rule: RuleConfig) -> list["Violation"]:
        """执行单条规则"""
        template = TemplateRegistry.get(rule.template_id)

        if not template:
            print(f"Warning: Unknown template {rule.template_id}")
            return []

        try:
            # 合并默认参数和配置参数
            params = {**rule.params, "rule_id": rule.id}
            return template.check(params, self._context)
        except Exception as e:
            print(f"Rule {rule.id} execution failed: {e}")
            return []

    def add_rule(self, rule: RuleConfig):
        """添加规则"""
        self.config_manager.add_rule(rule)

    def export_rules(self, path: str):
        """导出规则到文件"""
        self.config_manager.save_to_file(path)

    def generate_report(self, violations: list["Violation"]) -> str:
        """生成审查报告"""
        # 按严重程度分组
        errors = [v for v in violations if v.severity == "ERROR"]
        warnings = [v for v in violations if v.severity == "WARNING"]
        infos = [v for v in violations if v.severity == "INFO"]

        lines = [
            "# 原理图审查报告\n",
            f"发现问题: {len(violations)} 个\n",
            f"- ERROR: {len(errors)} 个\n",
            f"- WARNING: {len(warnings)} 个\n",
            f"- INFO: {len(infos)} 个\n",
            "\n## 详情\n",
        ]

        for v in errors + warnings:
            lines.append(f"### [{v.severity}] {v.refdes}\n")
            lines.append(f"- {v.description}\n")
            lines.append(f"- 期望: {v.expected}\n")
            lines.append(f"- 实际: {v.actual}\n\n")

        return "".join(lines)
```

---

## 4. 使用示例

```python
# 使用示例

# 1. 初始化引擎
engine = ReviewRuleEngine(
    neo4j_driver=driver,
    llm_client=llm
)

# 2. 加载规则配置
engine.load_rules_from_config("config/rules/automotive_rules.yaml")

# 3. 从知识库加载规则
engine.load_rules_from_neo4j()

# 4. 执行审查
violations = engine.run_rules()

# 5. 生成报告
report = engine.generate_report(violations)
print(report)

# 6. 添加新规则（编程方式）
new_rule = RuleConfig(
    id="CUSTOM_USB_OTG",
    template_id="esd_check",
    params={
        "interface_types": ["USB"],
        "max_capacitance_pf": 1.0,
    },
    severity="WARNING",
)
engine.add_rule(new_rule)
```

---

## 5. 方案对比

| 特性 | 固定规则 | 三层架构 |
|------|----------|----------|
| 规则灵活性 | ❌ 低 | ✅ 高 |
| 多产品线支持 | ❌ 困难 | ✅ 简单 |
| 规则版本管理 | ❌ 无 | ✅ 有 |
| 与知识库联动 | ❌ 无 | ✅ 支持 |
| 配置 vs 代码 | ❌ 代码 | ✅ 配置 + 代码 |
| 维护成本 | ❌ 高 | ✅ 低 |
| AI 驱动 | ❌ 无 | ✅ 支持 |

---

## 6. 结论

推荐采用 **三层架构**：
1. **Layer 1 (Template)**: 定义通用检查逻辑模板
2. **Layer 2 (Config)**: 通过 YAML/JSON 配置实例化规则
3. **Layer 3 (Knowledge)**: 从 Datasheet 自动提取规则（AI 驱动）

这样可以：
- 支持多产品线、多客户的差异化需求
- 规则更新无需修改代码
- 规则可版本化管理
- 与知识库无缝联动
