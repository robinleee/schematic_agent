"""
审查规则数据模型

定义规则配置、违规和白名单模型。
对应 Schemas_Design.md Section 5
"""

from __future__ import annotations

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
    id: str = Field(description="违规唯一标识")
    rule_id: str = Field(description="触发的规则 ID")
    rule_name: str = Field(description="规则名称")
    refdes: str = Field(description="涉及的器件位号")
    net_name: Optional[str] = Field(None, description="涉及的网络名称")
    description: str = Field(description="违规描述")
    severity: Literal["ERROR", "WARNING", "INFO"] = Field(
        default="WARNING",
        description="严重程度"
    )
    expected: str = Field(default="", description="期望值")
    actual: str = Field(default="", description="实际值")
    evidence: list[ViolationEvidence] = Field(default_factory=list)
    whitelisted: bool = Field(default=False, description="是否已在白名单中")
    whitelist_reason: Optional[str] = Field(None, description="白名单豁免原因")


# ============================================
# 假设模型 (用于诊断)
# ============================================


class Hypothesis(BaseModel):
    """故障根因假设"""
    id: str = Field(description="假设唯一标识")
    description: str = Field(description="假设描述")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5, description="置信度 0-1")
    evidence: list[str] = Field(default_factory=list, description="支持证据")
    counter_evidence: list[str] = Field(default_factory=list, description="反对证据")


# ============================================
# 规则模型
# ============================================


class RuleTemplate(BaseModel):
    """规则模板"""
    template_id: str = Field(description="模板 ID")
    name: str = Field(description="模板名称")
    description: str = Field(description="模板描述")
    default_severity: Literal["ERROR", "WARNING", "INFO"] = Field(
        default="WARNING",
        description="默认严重程度"
    )


class RuleConfig(BaseModel):
    """规则配置"""
    id: str = Field(description="规则配置 ID")
    template_id: str = Field(description="关联的模板 ID")
    name: Optional[str] = Field(None, description="规则名称")
    description: Optional[str] = Field(None, description="规则描述")
    severity: Literal["ERROR", "WARNING", "INFO"] = Field(
        default="WARNING",
        description="严重程度"
    )
    enabled: bool = Field(default=True, description="是否启用")
    params: dict = Field(default_factory=dict, description="规则参数")

    # 适用条件
    applicable_mpns: list[str] = Field(default_factory=list)
    applicable_voltages: list[str] = Field(default_factory=list)
    applicable_nets: list[str] = Field(default_factory=list)

    # 元数据
    version: str = Field(default="1.0.0")
    author: str = Field(default="system")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    tags: list[str] = Field(default_factory=list)


# ============================================
# 白名单模型
# ============================================


class WhitelistEntry(BaseModel):
    """白名单条目"""
    rule_id: str = Field(description="规则 ID")
    refdes: str = Field(description="豁免的器件位号")
    status: Literal["IGNORE", "APPROVED"] = Field(
        default="IGNORE",
        description="状态"
    )
    reason: Optional[str] = Field(None, description="豁免原因")
    added_by: str = Field(default="system", description="添加人")
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