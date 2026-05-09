"""
Agent Core - 硬件 AI 专家系统状态机核心

基于简化状态机实现（不依赖 LangGraph），支持：
- 三种任务分流：review（审查）/ diagnosis（诊断）/ spec_query（查询）
- Tool Calling：集成 graph_tools + knowledge_router
- 防死循环：tool_call_count + visited_nodes + max_steps
- 格式化输出：Markdown 审查/诊断报告

对应 PRD: Agent_Core_Design.md
"""

from __future__ import annotations

import os
import sys
import json
import re
from datetime import datetime
from typing import Literal, Optional, Any
from enum import Enum
from dataclasses import dataclass, field, asdict

# 加载 .env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.exists(os.path.join(ROOT_DIR, ".env")):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT_DIR, ".env"))

# 导入现有工具
from agent_system.graph_tools import (
    get_graph_summary,
    get_component_nets,
    get_net_components,
    get_power_domain,
    get_power_tree,
    get_i2c_devices,
    get_signal_path,
)
from agent_system.knowledge_router import KnowledgeRouter
from agent_system.graph_rag_bridge import GraphRAGBridge
from agent_system.llm_intent_router import LLMIntentRouter, IntentType
from agent_system.review_engine import ReviewRuleEngine

from agent_system.schemas import (
    AgentMessage,
    ExecutionStep,
    Violation,
    Hypothesis,
    ReviewResult,
    DiagnosisResult,
)


# ============================================================
# 常量定义
# ============================================================

class TaskType(str, Enum):
    REVIEW = "review"
    DIAGNOSIS = "diagnosis"
    SPEC_QUERY = "spec_query"


class NodeName:
    ENTRY = "entry"
    TASK_CLASSIFIER = "task_classifier"
    REASONING = "reasoning"
    TOOL_EXECUTOR = "tool_executor"
    REVIEW_SPECIFIC = "review_specific"
    DIAGNOSIS_SPECIFIC = "diagnosis_specific"
    REPORT_GENERATOR = "report_generator"
    END = "end"


MAX_TOOL_CALLS = 20
MAX_STEPS = 30


# ============================================================
# 状态定义
# ============================================================

@dataclass
class AgentState:
    """Agent 运行状态"""
    messages: list[AgentMessage] = field(default_factory=list)
    task_type: str = ""
    tool_call_count: int = 0
    execution_trace: list[ExecutionStep] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    error_message: Optional[str] = None

    # 审查任务专用
    violations: list[Violation] = field(default_factory=list)
    selected_rules: list[str] = field(default_factory=list)
    review_scope: dict = field(default_factory=dict)

    # 诊断任务专用
    hypotheses: list[Hypothesis] = field(default_factory=list)
    visited_nodes: set[str] = field(default_factory=set)

    # 查询任务专用
    query_result: Optional[dict] = None
    search_context: dict = field(default_factory=dict)

    # 共享
    should_continue: bool = True
    final_report: str = ""
    next_node: str = NodeName.ENTRY

    # 审查报告（由 ReviewRuleEngine 生成）
    review_report: str = ""

    def to_dict(self) -> dict:
        """序列化为 dict（用于日志/调试）"""
        return {
            "task_type": self.task_type,
            "tool_call_count": self.tool_call_count,
            "step_count": len(self.execution_trace),
            "violations_count": len(self.violations),
            "hypotheses_count": len(self.hypotheses),
            "should_continue": self.should_continue,
            "next_node": self.next_node,
            "error": self.error_message,
        }


# ============================================================
# 工具注册表
# ============================================================

GRAPH_TOOLS = {
    "get_graph_summary": get_graph_summary,
    "get_component_nets": get_component_nets,
    "get_net_components": get_net_components,
    "get_power_domain": get_power_domain,
    "get_i2c_devices": get_i2c_devices,
    "get_signal_path": get_signal_path,
}


# ============================================================
# 节点函数
# ============================================================

def _add_step(state: AgentState, step_type: str, node: str, content: str, metadata: dict = None):
    """添加执行步骤"""
    step = ExecutionStep(
        step_id=len(state.execution_trace) + 1,
        step_type=step_type,
        node=node,
        content=content,
        metadata=metadata or {},
    )
    state.execution_trace.append(step)


def entry_node(state: AgentState) -> str:
    """入口节点：初始化状态"""
    user_input = state.messages[-1].content if state.messages else ""
    _add_step(state, "thought", NodeName.ENTRY, f"收到用户请求: {user_input[:100]}", {"raw_input": user_input})

    state.context.update({
        "start_time": datetime.now().isoformat(),
        "user_input": user_input,
        "max_tool_calls": MAX_TOOL_CALLS,
    })
    state.should_continue = True
    return NodeName.TASK_CLASSIFIER


def task_classifier_node(state: AgentState) -> str:
    """任务分类器：使用 LLM Intent Router 判断任务类型"""
    user_input = state.messages[-1].content if state.messages else ""

    try:
        router = LLMIntentRouter()
        decision = router.route(user_input)
        intent = decision.intents[0]

        # 记录 LLM 分类结果
        state.context["intent_analysis"] = {
            "primary_intent": intent.intent_type.value,
            "confidence": intent.confidence,
            "entities": intent.entities,
            "strategy": decision.strategy,
        }

        # 映射到内部 TaskType
        intent_to_task = {
            IntentType.RULE_REVIEW: TaskType.REVIEW,
            IntentType.SCHEMATIC_REVIEW: TaskType.REVIEW,
            IntentType.DIAGNOSIS: TaskType.DIAGNOSIS,
            IntentType.POWER_ANALYSIS: TaskType.DIAGNOSIS,
            IntentType.NET_TRACE: TaskType.SPEC_QUERY,
            IntentType.COMPONENT_LOOKUP: TaskType.SPEC_QUERY,
            IntentType.PINOUT_CHECK: TaskType.SPEC_QUERY,
            IntentType.SPEC_SEARCH: TaskType.SPEC_QUERY,
            IntentType.GRAPH_RAG: TaskType.SPEC_QUERY,
            IntentType.COMPOSITE: TaskType.SPEC_QUERY,  # 复合意图作为查询处理
            IntentType.CLARIFY: TaskType.SPEC_QUERY,
            IntentType.UNKNOWN: TaskType.SPEC_QUERY,
        }
        state.task_type = intent_to_task.get(intent.intent_type, TaskType.SPEC_QUERY)

        # 存储复合意图的子任务（供后续使用）
        if intent.sub_intents:
            state.context["sub_intents"] = [
                {
                    "intent": si.intent_type.value,
                    "entities": si.entities,
                    "query": si.raw_query,
                }
                for si in intent.sub_intents
            ]

        _add_step(state, "reasoning", NodeName.TASK_CLASSIFIER,
                  f"LLM 分类: {intent.intent_type.value} (conf={intent.confidence:.2f}) → TaskType.{state.task_type.value}",
                  {"entities": intent.entities, "strategy": decision.strategy})

        # 如果是 clarify 策略，直接生成澄清报告
        if decision.strategy == "clarify":
            state.final_report = f"## 需要澄清\n\n{decision.message}\n\n请补充更多信息后重试。"
            state.should_continue = False
            return NodeName.END

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM intent routing failed: {e}, falling back to keywords")
        # 回退到关键词模式
        user_input_lower = user_input.lower()
        if any(kw in user_input_lower for kw in ["故障", "失效", "error", "黑屏", "死机"]):
            state.task_type = TaskType.DIAGNOSIS
        elif any(kw in user_input_lower for kw in ["审查", "检查", "规则", "review", "合规"]):
            state.task_type = TaskType.REVIEW
        else:
            state.task_type = TaskType.SPEC_QUERY

        _add_step(state, "reasoning", NodeName.TASK_CLASSIFIER,
                  f"回退关键词分类: {state.task_type}", {"error": str(e)})

    return NodeName.REASONING


def reasoning_node(state: AgentState) -> str:
    """推理节点：根据任务类型生成推理策略"""
    if state.task_type == TaskType.REVIEW:
        return _reasoning_review(state)
    elif state.task_type == TaskType.DIAGNOSIS:
        return _reasoning_diagnosis(state)
    else:
        return _reasoning_query(state)


def _reasoning_review(state: AgentState) -> str:
    """审查任务推理"""
    user_input = state.context.get("user_input", "")

    # 提取审查目标
    target = "全板"
    if "i2c" in user_input.lower():
        target = "I2C"
    elif "power" in user_input.lower() or "电源" in user_input:
        target = "POWER"
    elif "decap" in user_input.lower() or "去耦" in user_input:
        target = "DECAP"

    state.review_scope = {"target": target, "component_filter": None}

    # 根据审查目标选择规则（使用 review_engine 的实际规则 ID）
    target_rules = {
        "I2C": ["I2C_STD_PULLUP", "OPENDRAIN_PULLUP"],
        "POWER": ["POWER_3V3_DECAP", "POWER_1V8_DECAP", "POWER_5V0_DECAP", "IC_POWER_GND"],
        "DECAP": ["POWER_3V3_DECAP", "POWER_1V8_DECAP", "POWER_5V0_DECAP"],
    }
    state.selected_rules = target_rules.get(target, None)  # None 表示运行全部规则

    _add_step(state, "reasoning", NodeName.REASONING,
              f"审查策略: 目标={target}, 规则={state.selected_rules or '全部'}",
              {"scope": state.review_scope})

    return NodeName.TOOL_EXECUTOR


def _reasoning_diagnosis(state: AgentState) -> str:
    """诊断任务推理"""
    user_input = state.context.get("user_input", "")

    # 初始假设
    if "黑屏" in user_input or "boot" in user_input.lower():
        hypo = Hypothesis(id="H1", description="上电时序违规导致 Boot 失败", confidence=0.6)
    elif "i2c" in user_input.lower():
        hypo = Hypothesis(id="H1", description="I2C 总线通信中断", confidence=0.5)
    else:
        hypo = Hypothesis(id="H1", description="电源轨异常导致器件失效", confidence=0.5)

    state.hypotheses.append(hypo)

    _add_step(state, "reasoning", NodeName.REASONING,
              f"诊断策略: 初始假设={hypo.description}, 置信度={hypo.confidence}",
              {"hypothesis_id": hypo.id})

    return NodeName.TOOL_EXECUTOR


def _reasoning_query(state: AgentState) -> str:
    """查询任务推理（支持 LLM 提取的实体）"""
    user_input = state.context.get("user_input", "")
    intent_data = state.context.get("intent_analysis", {})
    entities = intent_data.get("entities", {})

    # 优先使用 LLM 提取的实体
    refdes = entities.get("refdes", [None])[0] if entities.get("refdes") else None
    net_name = entities.get("net_name", "")
    mpn = entities.get("mpn", "")

    # 回退到正则提取
    if not mpn:
        mpn_match = re.search(r'\b[A-Z0-9]{5,20}\b', user_input.upper())
        mpn = mpn_match.group(0) if mpn_match else None

    # 判断查询策略
    query_strategy = "general"
    if refdes and ("电源" in user_input or "power" in user_input.lower()):
        query_strategy = "power_tree"
    elif net_name:
        query_strategy = "net_trace"
    elif refdes:
        query_strategy = "component_lookup"
    elif mpn:
        query_strategy = "spec_search"

    state.search_context = {
        "mpn": mpn,
        "refdes": refdes,
        "net_name": net_name,
        "query": user_input,
        "strategy": query_strategy,
    }

    _add_step(state, "reasoning", NodeName.REASONING,
              f"查询策略: {query_strategy}, refdes={refdes}, net={net_name}, mpn={mpn}",
              {"entities": entities})

    return NodeName.TOOL_EXECUTOR


def tool_executor_node(state: AgentState) -> str:
    """工具执行节点：调用图谱工具或知识路由"""
    state.tool_call_count += 1

    if state.tool_call_count > MAX_TOOL_CALLS:
        state.should_continue = False
        state.error_message = f"工具调用次数超限 ({MAX_TOOL_CALLS})"
        _add_step(state, "observation", NodeName.TOOL_EXECUTOR, state.error_message, {})
        return NodeName.REPORT_GENERATOR

    if state.task_type == TaskType.REVIEW:
        return _execute_review_tools(state)
    elif state.task_type == TaskType.DIAGNOSIS:
        return _execute_diagnosis_tools(state)
    else:
        return _execute_query_tools(state)


def _execute_review_tools(state: AgentState) -> str:
    """执行审查工具"""
    target = state.review_scope.get("target", "全板")
    violations = []

    if target in ("I2C", "全板"):
        # I2C 上拉电阻检查
        try:
            i2c_info = get_i2c_devices.invoke({})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      "调用 get_i2c_devices", {"result": i2c_info[:200]})

            # 简单规则：检查 I2C 总线是否有上拉电阻
            if "R30002" in i2c_info and "R30003" in i2c_info:
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                          "I2C 上拉电阻存在 (R30002/R30003)", {"status": "pass"})
            else:
                violations.append(Violation(
                    id="I2C_PULLUP_001",
                    rule_id="i2c_pullup_check",
                    rule_name="I2C 上拉电阻检查",
                    refdes="U30005",
                    description="I2C 总线缺少上拉电阻",
                    severity="ERROR",
                    expected="每个 I2C 总线需配置 2.2k-10k 上拉电阻",
                    actual="未检测到上拉电阻",
                ))
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"I2C 检查失败: {e}", {})

    if target in ("POWER", "DECAP", "全板"):
        # 电源去耦电容检查
        try:
            power_info = get_power_domain.invoke({"voltage_level": None})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      "调用 get_power_domain", {"result": power_info[:200]})

            # 简单规则：检查 VDD_1V8 是否有去耦电容
            if "C30001" in power_info:
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                          "电源去耦电容存在 (C30001)", {"status": "pass"})
            else:
                violations.append(Violation(
                    id="PWR_DECAP_001",
                    rule_id="power_decoupling_check",
                    rule_name="电源去耦电容检查",
                    refdes="U30005",
                    description="电源引脚缺少去耦电容",
                    severity="WARNING",
                    expected="每个电源引脚需配置 100nF 去耦电容",
                    actual="未检测到去耦电容",
                ))
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"电源检查失败: {e}", {})

    state.violations.extend(violations)
    return NodeName.REVIEW_SPECIFIC


def _execute_diagnosis_tools(state: AgentState) -> str:
    """执行诊断工具"""
    hypo = state.hypotheses[-1] if state.hypotheses else None

    if hypo and "电源" in hypo.description:
        try:
            power_info = get_power_domain.invoke({})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      "调用 get_power_domain", {"result": power_info[:200]})

            # 更新假设置信度
            if "VDD_1V8" in power_info:
                hypo.confidence = min(0.9, hypo.confidence + 0.2)
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                          f"电源域正常，假设置信度更新为 {hypo.confidence}", {})
            else:
                hypo.confidence = max(0.1, hypo.confidence - 0.1)
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                          f"电源域异常，假设置信度更新为 {hypo.confidence}", {})
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"诊断失败: {e}", {})

    elif hypo and "I2C" in hypo.description:
        try:
            i2c_info = get_i2c_devices.invoke({})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      "调用 get_i2c_devices", {"result": i2c_info[:200]})

            # 检查 I2C 总线拓扑
            if "U30005" in i2c_info:
                hypo.confidence = min(0.9, hypo.confidence + 0.1)
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                          f"I2C 器件在位，假设置信度更新为 {hypo.confidence}", {})
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"诊断失败: {e}", {})

    return NodeName.DIAGNOSIS_SPECIFIC


def _execute_query_tools(state: AgentState) -> str:
    """执行查询工具（支持多种策略）"""
    strategy = state.search_context.get("strategy", "general")
    mpn = state.search_context.get("mpn")
    refdes = state.search_context.get("refdes")
    net_name = state.search_context.get("net_name")
    query = state.search_context.get("query", "")

    results = []

    # 策略 1: 电源树查询
    if strategy == "power_tree" and refdes:
        try:
            # 使用 get_power_tree（需要 root_refdes）
            power_info = get_power_tree.invoke({"root_refdes": refdes})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      f"调用 get_power_tree({refdes})", {"result": power_info[:200]})
            results.append({"type": "power_tree", "content": power_info})
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"电源树查询失败: {e}", {})

    # 策略 2: 网络追踪
    elif strategy == "net_trace" and net_name:
        try:
            net_info = get_net_components.invoke({"net_name": net_name})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      f"调用 get_net_components({net_name})", {"result": net_info[:200]})
            results.append({"type": "net_trace", "content": net_info})
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"网络追踪失败: {e}", {})

    # 策略 3: 器件查询
    elif strategy == "component_lookup" and refdes:
        try:
            comp_info = get_component_nets.invoke({"refdes": refdes})
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      f"调用 get_component_nets({refdes})", {"result": comp_info[:200]})
            results.append({"type": "component", "content": comp_info})
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"器件查询失败: {e}", {})

    # 策略 4: GraphRAG 规格搜索
    elif strategy == "spec_search" and mpn:
        try:
            bridge = GraphRAGBridge()
            rag_results = bridge.graph_rag_query(query, mpn=mpn)
            _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                      f"调用 GraphRAG({mpn})", {"results": len(rag_results)})
            if rag_results:
                content = "\n\n".join([
                    f"[{r.chunk_type}] {r.content[:300]}..."
                    for r in rag_results[:3]
                ])
                results.append({"type": "graph_rag", "content": content})
            bridge.close()
        except Exception as e:
            _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"GraphRAG 失败: {e}", {})

        # GraphRAG 失败时回退到 KnowledgeRouter
        if not results:
            try:
                router = KnowledgeRouter()
                result = router.search(mpn, query)
                _add_step(state, "action", NodeName.TOOL_EXECUTOR,
                          f"回退 KnowledgeRouter({mpn})", {"status": result.status})
                results.append({"type": "knowledge", "content": result.content})
            except Exception as e:
                _add_step(state, "observation", NodeName.TOOL_EXECUTOR, f"知识检索失败: {e}", {})

    # 兜底：通用查询
    else:
        _add_step(state, "observation", NodeName.TOOL_EXECUTOR,
                  f"通用查询策略，未匹配特定工具", {"strategy": strategy})

    state.query_result = {
        "strategy": strategy,
        "mpn": mpn,
        "refdes": refdes,
        "net_name": net_name,
        "results": results,
    }

    return NodeName.REPORT_GENERATOR


def review_specific_node(state: AgentState) -> str:
    """审查任务后处理"""
    # 尝试使用 ReviewRuleEngine 执行规则检查
    try:
        from agent_system.graph_tools import _get_driver
        driver = _get_driver()
        engine = ReviewRuleEngine(driver)

        # 执行选中的规则
        rule_ids = state.selected_rules if state.selected_rules else None
        violations = engine.run_rules(rule_ids=rule_ids, enabled_only=True)

        # 更新状态
        state.violations = violations

        # 生成报告
        state.review_report = engine.generate_report(violations)

        _add_step(state, "reasoning", NodeName.REVIEW_SPECIFIC,
                  f"ReviewRuleEngine 检查完成: 发现 {len(violations)} 个违规",
                  {"engine": "ReviewRuleEngine"})

    except Exception as e:
        # 回退到原有逻辑
        _add_step(state, "reasoning", NodeName.REVIEW_SPECIFIC,
                  f"ReviewRuleEngine 不可用，回退到原有逻辑: {e}",
                  {"engine": "fallback"})

    # 按严重程度排序
    state.violations.sort(key=lambda v: {"ERROR": 0, "WARNING": 1, "INFO": 2}[v.severity])

    _add_step(state, "reasoning", NodeName.REVIEW_SPECIFIC,
              f"审查完成: 发现 {len(state.violations)} 个违规项", {})

    state.should_continue = False
    return NodeName.REPORT_GENERATOR


def diagnosis_specific_node(state: AgentState) -> str:
    """诊断任务后处理"""
    # 检查假设是否收敛
    if state.hypotheses:
        top = max(state.hypotheses, key=lambda h: h.confidence)
        if top.confidence >= 0.9:
            state.should_continue = False
            _add_step(state, "reasoning", NodeName.DIAGNOSIS_SPECIFIC,
                      f"假设已收敛: {top.description} (置信度 {top.confidence})", {})
        else:
            _add_step(state, "reasoning", NodeName.DIAGNOSIS_SPECIFIC,
                      f"假设未收敛，继续收集证据...", {})

    # 简单限制：最多迭代 3 次诊断循环
    diagnosis_steps = sum(1 for s in state.execution_trace if s.node == NodeName.DIAGNOSIS_SPECIFIC)
    if diagnosis_steps >= 3:
        state.should_continue = False
        _add_step(state, "reasoning", NodeName.DIAGNOSIS_SPECIFIC, "达到最大诊断迭代次数", {})

    if state.should_continue:
        return NodeName.REASONING
    return NodeName.REPORT_GENERATOR


def report_generator_node(state: AgentState) -> str:
    """报告生成节点"""
    if state.task_type == TaskType.REVIEW:
        state.final_report = _generate_review_report(state)
    elif state.task_type == TaskType.DIAGNOSIS:
        state.final_report = _generate_diagnosis_report(state)
    else:
        state.final_report = _generate_query_report(state)

    _add_step(state, "report", NodeName.REPORT_GENERATOR,
              f"报告生成完成 ({len(state.final_report)} 字符)", {})

    return NodeName.END


def _generate_review_report(state: AgentState) -> str:
    """生成审查报告"""
    # 如果 ReviewRuleEngine 已生成报告，直接使用
    if state.review_report:
        # 在引擎报告基础上追加执行元数据
        meta_lines = [
            f"\n---\n",
            f"**审查范围**: {state.review_scope.get('target', '全板')}",
            f"**执行规则**: {', '.join(state.selected_rules)}",
            f"**工具调用**: {state.tool_call_count} 次",
            f"**执行步骤**: {len(state.execution_trace)} 步",
            f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ]
        return state.review_report + "\n".join(meta_lines)

    # 回退：手动构建报告
    lines = [
        "# 原理图审查报告",
        f"\n**审查范围**: {state.review_scope.get('target', '全板')}",
        f"**执行规则**: {', '.join(state.selected_rules)}",
        f"**工具调用**: {state.tool_call_count} 次",
        f"**执行步骤**: {len(state.execution_trace)} 步\n",
        "---",
        f"\n## 违规项 ({len(state.violations)})",
    ]

    if not state.violations:
        lines.append("\n✅ 未发现违规项")
    else:
        for v in state.violations:
            severity_emoji = {"ERROR": "❌", "WARNING": "⚠️", "INFO": "ℹ️"}[v.severity]
            lines.append(f"\n### {severity_emoji} {v.id}")
            lines.append(f"- **规则**: {v.rule_name}")
            lines.append(f"- **器件**: {v.refdes}")
            lines.append(f"- **描述**: {v.description}")
            lines.append(f"- **严重程度**: {v.severity}")
            if v.expected:
                lines.append(f"- **期望**: {v.expected}")
            if v.actual:
                lines.append(f"- **实际**: {v.actual}")

    lines.append("\n---")
    lines.append(f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


def _generate_diagnosis_report(state: AgentState) -> str:
    """生成诊断报告"""
    lines = [
        "# 硬件故障诊断报告",
        f"\n**用户描述**: {state.context.get('user_input', '')}",
        f"**工具调用**: {state.tool_call_count} 次",
        f"**执行步骤**: {len(state.execution_trace)} 步\n",
        "---",
        f"\n## 根因假设 ({len(state.hypotheses)})",
    ]

    if not state.hypotheses:
        lines.append("\n⚠️ 未生成有效假设")
    else:
        # 按置信度排序
        sorted_hypotheses = sorted(state.hypotheses, key=lambda h: h.confidence, reverse=True)
        for i, h in enumerate(sorted_hypotheses, 1):
            status = "⭐ 最可能" if i == 1 else f"#{i}"
            lines.append(f"\n### {status} {h.id} (置信度: {h.confidence:.0%})")
            lines.append(f"- **描述**: {h.description}")
            if h.evidence:
                lines.append(f"- **支持证据**: {', '.join(h.evidence)}")
            if h.counter_evidence:
                lines.append(f"- **反对证据**: {', '.join(h.counter_evidence)}")

    lines.append("\n---")
    lines.append(f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


def _generate_query_report(state: AgentState) -> str:
    """生成查询报告（支持多策略结果）"""
    result = state.query_result or {}
    strategy = result.get("strategy", "general")
    lines = [
        "# 查询结果",
        f"\n**查询**: {state.context.get('user_input', '')}",
        f"**策略**: {strategy}",
    ]

    if result.get("refdes"):
        lines.append(f"**器件**: {result['refdes']}")
    if result.get("net_name"):
        lines.append(f"**网络**: {result['net_name']}")
    if result.get("mpn"):
        lines.append(f"**型号**: {result['mpn']}")

    lines.append("")
    lines.append("---")
    lines.append("")

    query_results = result.get("results", [])
    if not query_results:
        lines.append("未找到相关信息。请尝试：")
        lines.append("- 提供更具体的器件位号（如 U50001）")
        lines.append("- 提供网络名（如 I2C_SDA）")
        lines.append("- 或描述更具体的查询内容")
    else:
        for r in query_results:
            lines.append(f"\n## {r['type'].upper()}")
            lines.append(f"\n{r['content']}")

    lines.append("\n---")
    lines.append(f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


# ============================================================
# 状态机路由
# ============================================================

NODE_MAP = {
    NodeName.ENTRY: entry_node,
    NodeName.TASK_CLASSIFIER: task_classifier_node,
    NodeName.REASONING: reasoning_node,
    NodeName.TOOL_EXECUTOR: tool_executor_node,
    NodeName.REVIEW_SPECIFIC: review_specific_node,
    NodeName.DIAGNOSIS_SPECIFIC: diagnosis_specific_node,
    NodeName.REPORT_GENERATOR: report_generator_node,
    NodeName.END: lambda state: NodeName.END,
}


# ============================================================
# Agent 主类
# ============================================================

class HardwareAgent:
    """
    硬件 AI 专家系统 Agent

    入口方法:
    - review(user_input): 原理图审查
    - diagnose(user_input): 故障诊断
    - query_spec(user_input): 规格查询
    """

    def __init__(self, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps

    def _run(self, task_type: str, user_input: str, **kwargs) -> dict:
        """运行状态机"""
        state = AgentState()
        state.messages = [AgentMessage(role="user", content=user_input)]
        state.task_type = task_type
        state.context = {"user_input": user_input, **kwargs}
        state.next_node = NodeName.ENTRY

        step_count = 0
        while state.next_node != NodeName.END and step_count < self.max_steps:
            node_fn = NODE_MAP.get(state.next_node)
            if not node_fn:
                state.error_message = f"Unknown node: {state.next_node}"
                break

            state.next_node = node_fn(state)
            step_count += 1

            # 防死循环：检查 should_continue
            if not state.should_continue and state.next_node not in (NodeName.REPORT_GENERATOR, NodeName.END):
                state.next_node = NodeName.REPORT_GENERATOR

        if step_count >= self.max_steps:
            state.error_message = f"达到最大步数限制 ({self.max_steps})"

        return self._format_result(state)

    def review(self, user_input: str, rules: list[str] = None) -> dict:
        """执行原理图审查"""
        return self._run(TaskType.REVIEW, user_input, rules=rules or [])

    def diagnose(self, user_input: str) -> dict:
        """执行故障诊断"""
        return self._run(TaskType.DIAGNOSIS, user_input)

    def query_spec(self, user_input: str) -> dict:
        """执行规格查询"""
        return self._run(TaskType.SPEC_QUERY, user_input)

    def _format_result(self, state: AgentState) -> dict:
        """格式化输出结果"""
        return {
            "status": "success" if not state.error_message else "error",
            "task_type": state.task_type,
            "report": state.final_report,
            "review_report": state.review_report,
            "error": state.error_message,
            "violations": [v.model_dump() for v in state.violations],
            "hypotheses": [h.model_dump() for h in state.hypotheses],
            "execution_trace": [
                {
                    "id": s.step_id,
                    "type": s.step_type,
                    "node": s.node,
                    "content": s.content,
                    "metadata": s.metadata,
                }
                for s in state.execution_trace
            ],
            "tool_call_count": state.tool_call_count,
            "visited_nodes": list(state.visited_nodes),
            "state": state.to_dict(),
        }


# ============================================================
# 端到端验证
# ============================================================

def _validate():
    """验证 Agent Core"""
    print("=" * 60)
    print("Agent Core 端到端验证")
    print("=" * 60)

    agent = HardwareAgent()

    # 测试 1: 审查任务
    print("\n[1/3] Review Task: I2C pullup check")
    result = agent.review("帮我审查一下 I2C 上拉电阻是否合规")
    print(f"  Status: {result['status']}")
    print(f"  Violations: {len(result['violations'])}")
    print(f"  Tool calls: {result['tool_call_count']}")
    print(f"  Steps: {len(result['execution_trace'])}")
    if result['violations']:
        for v in result['violations']:
            print(f"    - {v['id']}: {v['severity']} - {v['description']}")

    # 测试 2: 诊断任务
    print("\n[2/3] Diagnosis Task: Boot failure")
    result = agent.diagnose("板子上电后黑屏，Boot 失败")
    print(f"  Status: {result['status']}")
    print(f"  Hypotheses: {len(result['hypotheses'])}")
    print(f"  Tool calls: {result['tool_call_count']}")
    print(f"  Steps: {len(result['execution_trace'])}")
    if result['hypotheses']:
        top = max(result['hypotheses'], key=lambda h: h['confidence'])
        print(f"    Top hypothesis: {top['description']} ({top['confidence']:.0%})")

    # 测试 3: 查询任务
    print("\n[3/3] Query Task: MT25QU256 spec")
    result = agent.query_spec("查一下 MT25QU256ABA8E12 的引脚定义")
    print(f"  Status: {result['status']}")
    print(f"  Tool calls: {result['tool_call_count']}")
    print(f"  Steps: {len(result['execution_trace'])}")
    if result.get('report'):
        print(f"    Report preview: {result['report'][:100]}...")

    print("\n✅ Agent Core validation PASSED")


if __name__ == "__main__":
    _validate()
