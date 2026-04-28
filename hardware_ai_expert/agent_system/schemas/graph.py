"""
Neo4j 图谱数据模型

定义与 Neo4j 数据库对应的节点和关系模型。
对应 Schemas_Design.md Section 3
"""

from __future__ import annotations

from typing import Optional, Literal, Annotated, Sequence
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
        """转换为 Cypher 属性字典"""
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
        """转换为 Cypher 属性字典"""
        return {
            "Name": self.name,
            "VoltageLevel": self.voltage_level,
            "NetType": self.net_type,
        }


# ============================================
# 拓扑关系模型
# ============================================


class TopologyTriplet(BaseModel):
    """
    拓扑三元组模型

    表示 (Component) - [HAS_PIN] -> (Pin) - [CONNECTS_TO] -> (Net) 的关系
    """
    net_name: str = Field(description="网络名称")
    component_refdes: str = Field(description="器件位号")
    pin_number: str = Field(description="引脚编号")
    pin_type: str = Field(default="SIGNAL", description="引脚类型")
    voltage_level: str = Field(default="UNKNOWN", description="电压等级")

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

NEO4J_CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT component_refdes IF NOT EXISTS FOR (c:Component) REQUIRE c.RefDes IS UNIQUE",
    "CREATE CONSTRAINT pin_id IF NOT EXISTS FOR (p:Pin) REQUIRE p.Id IS UNIQUE",
    "CREATE CONSTRAINT net_name IF NOT EXISTS FOR (n:Net) REQUIRE n.Name IS UNIQUE",
]

NEO4J_INDEXES: list[str] = [
    "CREATE INDEX component_parttype IF NOT EXISTS FOR (c:Component) ON (c.PartType)",
    "CREATE INDEX component_mpn IF NOT EXISTS FOR (c:Component) ON (c.MPN)",
    "CREATE INDEX pin_type IF NOT EXISTS FOR (p:Pin) ON (p.Type)",
    "CREATE INDEX net_voltage_level IF NOT EXISTS FOR (n:Net) ON (n.VoltageLevel)",
]
