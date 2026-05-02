"""
规则模板层 (Layer 1)

所有检查逻辑模板统一注册到 TemplateRegistry。
新增模板只需继承 RuleTemplate 并调用 TemplateRegistry.register()。
"""

from agent_system.review_engine.templates.base import (
    RuleTemplate,
    RuleContext,
    TemplateRegistry,
)

# 自动导入并注册所有内置模板
from agent_system.review_engine.templates.decap import DecapCheckTemplate
from agent_system.review_engine.templates.pullup import PullupCheckTemplate
from agent_system.review_engine.templates.esd import ESDCheckTemplate
from agent_system.review_engine.templates.amr import AMRCheckTemplate
from agent_system.review_engine.templates.pinmux import PinMuxCheckTemplate

__all__ = [
    "RuleTemplate",
    "RuleContext",
    "TemplateRegistry",
    "DecapCheckTemplate",
    "PullupCheckTemplate",
    "ESDCheckTemplate",
    "AMRCheckTemplate",
    "PinMuxCheckTemplate",
]
