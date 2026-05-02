"""
Review Engine - 原理图审查规则引擎

三层架构：
- Layer 1 (Template): 通用检查逻辑模板
- Layer 2 (Config): YAML/JSON 规则配置实例化
- Layer 3 (Knowledge): 从 Datasheet 自动提取规则

用法：
    from agent_system.review_engine import ReviewRuleEngine
    engine = ReviewRuleEngine(driver)
    violations = engine.run_rules()
"""

from agent_system.review_engine.engine import ReviewRuleEngine

__all__ = ["ReviewRuleEngine"]
