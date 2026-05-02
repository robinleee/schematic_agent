"""
规则模板抽象基类与注册表

定义 Layer 1 的核心接口：
- RuleTemplate: 所有检查模板的抽象基类
- RuleContext: 模板执行上下文（Neo4j driver + graph_tools + knowledge_router）
- TemplateRegistry: 模板注册中心
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_system.schemas import Violation


@dataclass
class RuleContext:
    """规则执行上下文"""
    neo4j_driver: Any
    # 可选扩展
    # graph_tools: Any = None
    # knowledge_router: Any = None


class RuleTemplate(ABC):
    """
    规则模板抽象基类

    子类必须实现：
    - template_id: str  模板唯一标识
    - name: str          模板名称
    - description: str   模板描述
    - check(): 执行检查，返回 Violation 列表
    """

    template_id: str = ""
    name: str = ""
    description: str = ""
    default_severity: str = "WARNING"

    @abstractmethod
    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        """
        执行规则检查

        Args:
            params: 规则参数（来自 YAML/JSON 配置）
            context: 执行上下文（含 Neo4j driver 等）

        Returns:
            违规列表，空列表表示无违规
        """
        pass

    def validate_params(self, params: dict) -> bool:
        """验证参数合法性，默认始终通过"""
        return True


class TemplateRegistry:
    """规则模板注册表（类级别单例）"""

    _templates: dict[str, RuleTemplate] = {}

    @classmethod
    def register(cls, template: RuleTemplate):
        """注册模板实例"""
        cls._templates[template.template_id] = template

    @classmethod
    def get(cls, template_id: str) -> RuleTemplate | None:
        """按 ID 获取模板"""
        return cls._templates.get(template_id)

    @classmethod
    def list_templates(cls) -> list[dict]:
        """列出所有已注册模板"""
        return [
            {
                "id": t.template_id,
                "name": t.name,
                "description": t.description,
            }
            for t in cls._templates.values()
        ]

    @classmethod
    def clear(cls):
        """清空注册表（测试用）"""
        cls._templates.clear()
