# Agent 核心模块详细设计

## 1. 模块概述

**模块名称**: `agent_system/agent_core.py`

**核心职责**: 基于 LangGraph 状态机编排硬件 AI 专家系统的推理流程，实现原理图审查与故障诊断两大核心功能。

**设计目标**:
- 避免简单的 ReAct 循环，采用状态机管理复杂多轮推理
- 支持任务类型分流：原理图审查 vs 故障诊断
- 内置防死循环机制（visited_nodes + tool_call_count）
- 支持 Human-in-the-Loop 专家干预
- 与 Neo4j 图谱工具、Knowledge Router 无缝集成

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Hardware Agent System                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐    │
│  │   User UI   │────▶│ Streamlit    │────▶│   LangGraph State    │    │
│  │  (输入/反馈) │     │   Handler    │     │       Machine        │    │
│  └──────────────┘     └──────────────┘     └──────────────────────┘    │
│                                                        │                 │
│                         ┌──────────────────────────────┼─────────────┐  │
│                         │                              ▼             │  │
│                         │  ┌─────────────────────────────────────┐  │  │
│                         │  │         Graph State (AgentState)    │  │  │
│                         │  │  • messages: 推理历史                │  │  │
│                         │  │  • task_type: review | diagnosis    │  │  │
│                         │  │  • current_hypothesis: 根因假设     │  │  │
│                         │  │  • visited_nodes: 已查验节点        │  │  │
│                         │  │  • tool_call_count: 计数器          │  │  │
│                         │  │  • execution_trace: 执行流          │  │  │
│                         │  └─────────────────────────────────────┘  │  │
│                         │                              │             │  │
│                         │         ┌───────────────────┼─────────┐   │  │
│                         │         ▼                   ▼         ▼   │  │
│                         │  ┌──────────┐  ┌─────────────┐  ┌──────┐ │  │
│                         │  │ Reasoning │  │ToolExecutor │  │Router│ │  │
│                         │  │   Node    │  │    Node     │  │ Node │ │  │
│                         │  └──────────┘  └─────────────┘  └──────┘ │  │
│                         │         │              │              │     │  │
│                         │         └──────────────┼──────────────┘     │  │
│                         │                        ▼                      │  │
│                         │         ┌─────────────────────────┐          │  │
│                         │         │   Tool Execution Layer  │          │  │
│                         │         │  ┌─────┐ ┌────────────┐ │          │  │
│                         │         │  │graph│ │knowledge   │ │          │  │
│                         │         │  │tools│ │_router     │ │          │  │
│                         │         │  └─────┘ └────────────┘ │          │  │
│                         │         └─────────────────────────┘          │  │
│                         └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 状态机定义

### 3.1 设计优化说明

**原问题**: `HardwareAgentState` 包含 12+ 个字段，状态过于复杂，维护成本高。

**优化方案**: 采用**基础状态 + 任务特定状态**的分层设计。

### 3.2 基础状态设计 (BaseAgentState)

```python
# agent_system/agent_core.py

from typing import TypedDict, Annotated, Literal, Optional
from typing_extensions import NotRequired
import operator
from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    """Agent 对话消息模型"""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


class ExecutionStep(BaseModel):
    """执行步骤追踪"""
    step_id: int
    step_type: Literal["thought", "action", "observation", "reasoning", "report"]
    node: str  # 触发该步骤的节点名称
    content: str
    metadata: dict = Field(default_factory=dict)


class BaseAgentState(TypedDict):
    """
    基础状态 - 所有任务类型共享

    Attributes:
        messages: 对话历史 (Annotated with operator.add 实现增量追加)
        tool_call_count: 工具调用计数器 (防无限循环)
        execution_trace: 执行过程追踪 (用于 UI 展示)
        context: 任务上下文信息
        error_message: 错误信息
    """

    # 共享字段
    messages: Annotated[list[AgentMessage], operator.add]
    tool_call_count: int
    execution_trace: Annotated[list[ExecutionStep], operator.add]
    context: dict
    error_message: NotRequired[str]


class ReviewState(BaseAgentState):
    """
    审查任务状态 - 继承基础状态

    新增字段:
        violations: 发现的违规项列表
        selected_rules: 选中的审查规则
        review_scope: 审查范围 (网络/器件)
    """

    violations: list["ViolationItem"]
    selected_rules: list[str]
    review_scope: dict  # {"type": "net", "pattern": "1V8"}


class DiagnosisState(BaseAgentState):
    """
    诊断任务状态 - 继承基础状态

    新增字段:
        hypotheses: 所有候选假设列表
        visited_nodes: 已查验的节点集合 (防死循环)
        current_hypothesis: 当前假设
    """

    hypotheses: Annotated[list["Hypothesis"], operator.add]
    visited_nodes: Annotated[set[str], operator.add]


class QueryState(BaseAgentState):
    """
    查询任务状态 - 继承基础状态

    新增字段:
        query_result: 查询结果
        search_context: 搜索上下文
    """

    query_result: Optional[dict]
    search_context: dict
```

### 3.3 Violation 与 Hypothesis 模型

```python
class ViolationItem(BaseModel):
    """违规项模型"""
    id: str
    rule_id: str
    rule_name: str
    refdes: str
    description: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    evidence: dict = Field(default_factory=dict)
    whitelisted: bool = False


class Hypothesis(BaseModel):
    """故障根因假设"""
    id: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
```

### 3.4 状态工厂函数

```python
def create_initial_state(
    task_type: str,
    user_input: str,
    **kwargs
) -> dict:
    """
    创建初始状态 - 根据任务类型选择状态

    Returns:
        BaseAgentState | ReviewState | DiagnosisState | QueryState
    """
    base = {
        "messages": [AgentMessage(role="user", content=user_input)],
        "tool_call_count": 0,
        "execution_trace": [],
        "context": {
            "task_type": task_type,
            "user_input": user_input,
            "max_tool_calls": kwargs.get("max_tool_calls", 20),
            "start_time": datetime.now().isoformat(),
        },
    }

    if task_type == TaskType.REVIEW:
        base.update({
            "violations": [],
            "selected_rules": kwargs.get("rules", []),
            "review_scope": kwargs.get("scope", {}),
        })
    elif task_type == TaskType.DIAGNOSIS:
        base.update({
            "hypotheses": [],
            "visited_nodes": set(),
        })
    else:  # SPEC_QUERY
        base.update({
            "query_result": None,
            "search_context": {},
        })

    return base
```

### 3.2 状态机节点定义

```python
# ============================================
# 节点类型枚举
# ============================================

class NodeName:
    """节点名称常量"""
    ENTRY = "entry"
    TASK_CLASSIFIER = "task_classifier"
    REASONING = "reasoning"
    TOOL_EXECUTOR = "tool_executor"
    REVIEW_SPECIFIC = "review_specific"
    DIAGNOSIS_SPECIFIC = "diagnosis_specific"
    HYPOTHESIS_EVALUATOR = "hypothesis_evaluator"
    REPORT_GENERATOR = "report_generator"
    HITL_HANDLER = "hitl_handler"
    END = "end"


class TaskType:
    """任务类型常量"""
    REVIEW = "review"
    DIAGNOSIS = "diagnosis"
    SPEC_QUERY = "spec_query"


# ============================================
# 边路由条件
# ============================================

def classify_task(state: HardwareAgentState) -> str:
    """
    任务分类器：根据用户输入判断任务类型

    Returns:
        "review" | "diagnosis" | "spec_query"
    """
    user_message = state["messages"][-1].content if state["messages"] else ""

    # 使用关键词匹配进行简单分类
    diagnosis_keywords = ["故障", "不工作", "失效", "error", "fault", "not working",
                          "无法识别", "没有响应", "烧毁", "发热"]
    review_keywords = ["审查", "检查", "规则", "review", "check", "audit",
                       "合规", "规范"]
    spec_keywords = ["规格", "参数", "spec", "datasheet", "引脚定义", "voltage"]

    # 实际项目中应调用 LLM 进行分类
    # 此处为简化示例
    if any(kw in user_message.lower() for kw in diagnosis_keywords):
        return TaskType.DIAGNOSIS
    elif any(kw in user_message.lower() for kw in review_keywords):
        return TaskType.REVIEW
    else:
        return TaskType.SPEC_QUERY


def should_continue_execution(state: HardwareAgentState) -> bool:
    """
    判断是否继续执行循环

    终止条件:
    1. 工具调用次数超限 (默认 20 次)
    2. 已产生最终报告
    3. 遇到不可恢复的错误
    4. 假设已收敛 (诊断模式)
    """
    max_tool_calls = state["context"].get("max_tool_calls", 20)

    # 硬终止条件
    if state["tool_call_count"] >= max_tool_calls:
        return False

    if state.get("final_report"):
        return False

    if state.get("error_message"):
        return False

    # 诊断模式：假设已收敛
    if state["task_type"] == TaskType.DIAGNOSIS:
        if len(state["hypotheses"]) > 0:
            top_hypothesis = max(state["hypotheses"], key=lambda h: h.confidence)
            if top_hypothesis.confidence >= 0.9:
                return False

    return True
```

---

## 4. 核心节点实现

### 4.1 Entry Node (入口节点)

```python
# ============================================
# Entry Node - 初始化状态
# ============================================

def entry_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    入口节点：初始化 Agent 状态

    处理逻辑:
    1. 解析用户输入
    2. 初始化上下文
    3. 记录初始步骤
    """
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""

    # 记录初始执行步骤
    initial_step = ExecutionStep(
        step_id=len(state["execution_trace"]) + 1,
        step_type="thought",
        node=NodeName.ENTRY,
        content=f"收到用户请求: {user_message[:100]}...",
        metadata={"raw_input": user_message}
    )

    # 初始化上下文
    context = state.get("context", {})
    context.update({
        "start_time": datetime.now().isoformat(),
        "user_input": user_message,
        "max_tool_calls": context.get("max_tool_calls", 20),
        "confidence_threshold": 0.8,
    })

    return {
        "execution_trace": [initial_step],
        "context": context,
        "visited_nodes": set(),
        "visited_paths": set(),
        "tool_call_count": 0,
        "hypotheses": [],
        "violations": [],
        "should_continue": True,
    }
```

### 4.2 Reasoning Node (推理节点)

```python
# ============================================
# Reasoning Node - 大模型思考
# ============================================

def reasoning_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    推理节点：调用 LLM 进行推理分析

    处理逻辑:
    1. 构建 Prompt (包含状态上下文)
    2. 调用 LLM 生成思考
    3. 决定下一步行动
    4. 更新假设列表 (诊断模式)
    """
    messages = state["messages"]
    task_type = state["task_type"]
    context = state["context"]

    # 构建推理 Prompt
    prompt = build_reasoning_prompt(state)

    # 调用 LLM
    try:
        response = llm.invoke([
            SystemMessage(content=REASONING_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ])

        reasoning_output = response.content

    except Exception as e:
        return {
            "error_message": f"LLM 调用失败: {str(e)}",
            "should_continue": False
        }

    # 记录推理步骤
    reasoning_step = ExecutionStep(
        step_id=len(state["execution_trace"]) + 1,
        step_type="reasoning",
        node=NodeName.REASONING,
        content=reasoning_output,
        metadata={"llm_model": "qwen-max"}
    )

    # 解析 LLM 输出，提取下一步行动
    next_action = parse_llm_action(reasoning_output, task_type)

    # 添加 Assistant 消息
    assistant_message = AgentMessage(
        role="assistant",
        content=reasoning_output
    )

    # 诊断模式：更新假设
    hypotheses = state["hypotheses"]
    if task_type == TaskType.DIAGNOSIS and next_action.get("new_hypothesis"):
        new_hyp = Hypothesis(
            id=f"hyp_{len(hypotheses) + 1}",
            description=next_action["new_hypothesis"]["description"],
            confidence=next_action["new_hypothesis"].get("confidence", 0.5),
            evidence=[],
            counter_evidence=[]
        )
        hypotheses.append(new_hyp)

    return {
        "messages": [assistant_message],
        "execution_trace": [reasoning_step],
        "hypotheses": hypotheses,
        "context": {**context, "next_action": next_action},
        "tool_call_count": state["tool_call_count"],
        "should_continue": True,
    }


def build_reasoning_prompt(state: HardwareAgentState) -> str:
    """构建推理 Prompt"""

    task_type = state["task_type"]
    context = state["context"]
    visited = list(state["visited_nodes"])[:10]  # 限制显示数量
    tool_call_count = state["tool_call_count"]
    max_calls = context.get("max_tool_calls", 20)

    prompt_parts = [
        f"# 当前任务: {task_type}",
        f"# 工具调用次数: {tool_call_count}/{max_calls}",
        f"# 已访问节点: {visited}",
        f"\n## 用户输入\n{context.get('user_input', '')}",
    ]

    # 添加任务特定上下文
    if task_type == TaskType.DIAGNOSIS:
        hypotheses = state["hypotheses"]
        if hypotheses:
            prompt_parts.append(f"\n## 当前假设\n")
            for h in hypotheses[-3:]:  # 只显示最近 3 个
                prompt_parts.append(
                    f"- [{h.id}] {h.description} (置信度: {h.confidence:.0%})"
                )

    elif task_type == TaskType.REVIEW:
        violations = state["violations"]
        if violations:
            prompt_parts.append(f"\n## 已发现违规\n")
            for v in violations[-5:]:
                prompt_parts.append(
                    f"- [{v.severity}] {v.rule_name}: {v.refdes}"
                )

    prompt_parts.append("\n\n请分析当前状态，决定下一步行动。")
    prompt_parts.append("输出格式: JSON {action: 'query_graph'|'search_knowledge'|'update_hypothesis'|'generate_report', params: {...}}")

    return "\n".join(prompt_parts)


REASONING_SYSTEM_PROMPT = """你是一个专业的硬件工程师 AI 助手，专门处理原理图审查和故障诊断。

## 你的能力
1. 理解硬件电路拓扑关系
2. 查询 Neo4j 图谱获取器件信息和网络连接
3. 检索 Datasheet 知识库获取器件规格
4. 推理故障根因和设计违规

## 工作流程
1. 分析用户问题，理解任务目标
2. 使用图谱查询工具收集信息
3. 使用知识检索工具获取规格参数
4. 综合分析形成结论
5. 生成审查报告或诊断报告

## 输出规范
请始终以 JSON 格式输出你的思考和行动，保持简洁专业。
"""
```

### 4.3 Tool Executor Node (工具执行节点)

```python
# ============================================
# Tool Executor Node - 工具执行
# ============================================

from langchain_core.tools import tool
from langchain.tools import Tool


def tool_executor_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    工具执行节点：执行 LLM 决定调用的工具

    支持的工具:
    1. Graph Tools (Neo4j)
       - query_component_attributes
       - trace_shortest_path
       - find_connected_peripherals
       - find_net_by_name

    2. Knowledge Router (RAG)
       - search_hardware_specs

    3. Review Rules
       - check_decapacitor
       - check_pullup_resistor
       - check_esd_protection
    """

    context = state["context"]
    next_action = context.get("next_action", {})
    action_type = next_action.get("action")
    action_params = next_action.get("params", {})

    if not action_type or action_type == "generate_report":
        # 无需执行工具
        return {"should_continue": False}

    # 增加工具调用计数
    tool_call_count = state["tool_call_count"] + 1

    # 记录 Action 步骤
    action_step = ExecutionStep(
        step_id=len(state["execution_trace"]) + 1,
        step_type="action",
        node=NodeName.TOOL_EXECUTOR,
        content=f"调用工具: {action_type}",
        metadata={
            "tool_name": action_type,
            "params": action_params
        }
    )

    # 执行工具
    try:
        result = execute_tool(action_type, action_params, state)

    except Exception as e:
        error_step = ExecutionStep(
            step_id=len(state["execution_trace"]) + 2,
            step_type="observation",
            node=NodeName.TOOL_EXECUTOR,
            content=f"工具执行失败: {str(e)}",
            metadata={"error": str(e)}
        )
        return {
            "execution_trace": [action_step, error_step],
            "tool_call_count": tool_call_count,
            "error_message": str(e),
            "should_continue": False
        }

    # 记录 Observation 步骤
    observation_step = ExecutionStep(
        step_id=len(state["execution_trace"]) + 2,
        step_type="observation",
        node=NodeName.TOOL_EXECUTOR,
        content=str(result)[:500],  # 限制长度
        metadata={
            "tool_name": action_type,
            "result_count": len(result) if isinstance(result, list) else 1
        }
    )

    # 更新 visited_nodes (防死循环)
    visited_nodes = state["visited_nodes"]
    if action_type == "query_component_attributes":
        refdes = action_params.get("refdes")
        if refdes:
            visited_nodes.add(refdes)

    elif action_type == "trace_shortest_path":
        path_key = f"{action_params.get('source')}_{action_params.get('target')}"
        visited_paths.add(path_key)
        # 提取路径上的所有节点
        if isinstance(result, list):
            for node in result:
                if node.get("type") == "Component":
                    visited_nodes.add(node.get("refdes"))

    # 诊断模式：更新假设证据
    hypotheses = state["hypotheses"]
    if state["task_type"] == TaskType.DIAGNOSIS and result:
        for hyp in hypotheses:
            # 简单的证据匹配逻辑
            for item in (result if isinstance(result, list) else [result]):
                if _supports_hypothesis(hyp.description, item):
                    hyp.evidence.append(str(item))
                elif _contradicts_hypothesis(hyp.description, item):
                    hyp.counter_evidence.append(str(item))

    # 审查模式：更新违规列表
    violations = state["violations"]
    if state["task_type"] == TaskType.REVIEW and result:
        if isinstance(result, list):
            violations.extend(result)
        elif result:
            violations.append(result)

    return {
        "execution_trace": [action_step, observation_step],
        "visited_nodes": visited_nodes,
        "visited_paths": visited_paths,
        "tool_call_count": tool_call_count,
        "hypotheses": hypotheses,
        "violations": violations,
        "context": {**context, "last_tool_result": result},
        "should_continue": True
    }


def execute_tool(action_type: str, params: dict, state: HardwareAgentState) -> any:
    """
    统一工具执行入口

    Args:
        action_type: 工具类型
        params: 工具参数
        state: 当前状态

    Returns:
        工具执行结果
    """
    from agent_system.graph_tools import (
        query_component_attributes,
        trace_shortest_path,
        find_connected_peripherals,
        find_net_by_name,
    )
    from agent_system.knowledge_router import search_hardware_specs

    tool_map = {
        "query_component_attributes": query_component_attributes,
        "trace_shortest_path": trace_shortest_path,
        "find_connected_peripherals": find_connected_peripherals,
        "find_net_by_name": find_net_by_name,
        "search_hardware_specs": search_hardware_specs,
    }

    tool_func = tool_map.get(action_type)
    if not tool_func:
        raise ValueError(f"Unknown tool: {action_type}")

    # 调用工具
    result = tool_func(**params)
    return result


def _supports_hypothesis(hypothesis: str, evidence: dict) -> bool:
    """判断证据是否支持假设"""
    # 简化实现，实际应使用 LLM 判断
    evidence_str = str(evidence).lower()
    hypothesis_keywords = hypothesis.lower().split()

    matches = sum(1 for kw in hypothesis_keywords if kw in evidence_str)
    return matches >= len(hypothesis_keywords) * 0.3


def _contradicts_hypothesis(hypothesis: str, evidence: dict) -> bool:
    """判断证据是否反驳假设"""
    # 简化实现
    contradiction_keywords = ["not found", "missing", "failed", "error", "disconnected"]
    evidence_str = str(evidence).lower()

    return any(kw in evidence_str for kw in contradiction_keywords)
```

### 4.4 Review Specific Node (审查专用节点)

```python
# ============================================
# Review Specific Node - 审查专用逻辑
# ============================================

def review_specific_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    审查专用节点：执行预定义的审查规则

    审查流程:
    1. 确定审查范围 (网络、器件类型)
    2. 加载适用的审查规则
    3. 执行规则检查
    4. 收集违规项
    """

    context = state["context"]
    user_input = context.get("user_input", "")

    # 确定审查规则
    rules = determine_review_rules(user_input)

    new_violations = []

    for rule in rules:
        try:
            violations = execute_review_rule(rule, state)
            new_violations.extend(violations)
        except Exception as e:
            # 规则执行失败，记录但不中断
            error_step = ExecutionStep(
                step_id=len(state["execution_trace"]) + 1,
                step_type="thought",
                node=NodeName.REVIEW_SPECIFIC,
                content=f"规则 {rule['id']} 执行失败: {str(e)}"
            )

    # 合并违规列表
    all_violations = state["violations"] + new_violations

    # 检查是否应该终止
    should_continue = len(all_violations) < 10  # 最多报告 10 个违规

    return {
        "violations": all_violations,
        "should_continue": should_continue
    }


def determine_review_rules(user_input: str) -> list[dict]:
    """根据用户输入确定适用的审查规则"""
    from agent_system.review_rules import REVIEW_RULES

    # 默认执行所有规则
    return REVIEW_RULES


def execute_review_rule(rule: dict, state: HardwareAgentState) -> list[ViolationItem]:
    """
    执行单条审查规则

    Args:
        rule: 规则定义
        state: 当前状态

    Returns:
        违规项列表
    """
    from agent_system.graph_tools import find_net_by_name, query_component_attributes

    violations = []
    rule_id = rule["id"]

    if rule_id == "POWER_DECAP":
        # 检查电源去耦电容
        # 1. 查找所有电源网络
        power_nets = find_net_by_name(net_pattern=".*V.*")  # 简化匹配

        for net in power_nets[:5]:  # 限制检查数量
            net_name = net["name"]

            # 2. 查找连接到该网络的 IC
            ic_components = find_components_on_net(net_name, part_types=["IC", "MCU"])

            # 3. 检查每个 IC 是否有去耦电容
            for ic in ic_components:
                caps = find_connected_peripherals(
                    center_refdes=ic["refdes"],
                    radius=1,
                    part_types=["CAP"]
                )

                if len(caps) == 0:
                    violations.append(ViolationItem(
                        id=f"{rule_id}_{ic['refdes']}_{net_name}",
                        rule_id=rule_id,
                        rule_name=rule["description"],
                        refdes=ic["refdes"],
                        description=f"IC {ic['refdes']} 的电源网络 {net_name} 缺少去耦电容",
                        severity="WARNING",
                        evidence={"net": net_name, "found_caps": 0}
                    ))

    elif rule_id == "I2C_PULLUP":
        # 检查 I2C 上拉电阻
        i2c_nets = find_net_by_name(net_pattern=".*I2C.*|.*SCL.*|.*SDA.*")

        for net in i2c_nets:
            net_name = net["name"]

            # 查找连接到 I2C 网络的电阻
            resistors = find_components_on_net(net_name, part_types=["RES"])

            has_pullup = False
            for res in resistors:
                attrs = query_component_attributes(refdes=res["refdes"])
                value = attrs.get("value", "").lower()
                # 检查是否是合理的上拉电阻值 (2.2k-10k)
                if any(v in value for v in ["2.2k", "4.7k", "10k", "4k7", "10k"]):
                    has_pullup = True
                    break

            if not has_pullup and len(resistors) > 0:
                violations.append(ViolationItem(
                    id=f"{rule_id}_{net_name}",
                    rule_id=rule_id,
                    rule_name=rule["description"],
                    refdes="N/A",
                    description=f"I2C 网络 {net_name} 未检测到上拉电阻",
                    severity="ERROR",
                    evidence={"net": net_name, "resistors_found": len(resistors)}
                ))

    # ... 其他规则实现

    return violations
```

### 4.5 Diagnosis Specific Node (诊断专用节点)

```python
# ============================================
# Diagnosis Specific Node - 诊断专用逻辑
# ============================================

def diagnosis_specific_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    诊断专用节点：执行故障诊断逻辑

    诊断流程:
    1. 理解故障现象
    2. 定位相关器件/网络
    3. 追踪信号路径
    4. 收集证据
    5. 推理根因
    """

    user_input = state["context"].get("user_input", "")

    # 提取故障相关关键词
    symptoms = extract_symptoms(user_input)

    # 根据症状定位可能的问题区域
    hypothesis = analyze_symptoms(symptoms, state)

    # 更新假设列表
    hypotheses = state["hypotheses"]
    if hypothesis:
        new_hyp = Hypothesis(
            id=f"hyp_{len(hypotheses) + 1}",
            description=hypothesis["description"],
            confidence=hypothesis.get("confidence", 0.3),
            evidence=[],
            counter_evidence=[]
        )
        hypotheses.append(new_hyp)

    return {
        "hypotheses": hypotheses,
        "current_hypothesis": hypothesis["description"] if hypothesis else None
    }


def extract_symptoms(user_input: str) -> list[dict]:
    """从用户输入中提取故障症状"""

    symptom_patterns = {
        "接口故障": ["无法识别", "不识别", "识别失败", "no device detected"],
        "通信故障": ["通信失败", "超时", "无响应", "no response"],
        "电源问题": ["不供电", "电压异常", "电流过大", "短路"],
        "发热问题": ["发热", "过热", "烫", "thermal"],
        "信号问题": ["信号衰减", "噪声", "干扰", "noise"],
    }

    symptoms = []
    for category, keywords in symptom_patterns.items():
        for kw in keywords:
            if kw in user_input.lower():
                symptoms.append({
                    "category": category,
                    "keyword": kw,
                    "description": f"检测到 {category} 症状 (关键词: {kw})"
                })
                break

    return symptoms


def analyze_symptoms(symptoms: list[dict], state: HardwareAgentState) -> dict | None:
    """
    分析症状，生成假设

    Returns:
        Hypothesis dict with description and confidence
    """

    if not symptoms:
        return None

    # 基于症状类型生成假设
    symptom_to_hypothesis = {
        "接口故障": [
            ("ESD 保护器件选型不当", 0.6),
            ("连接器接触不良", 0.5),
            ("信号线布线问题", 0.4),
        ],
        "通信故障": [
            ("上拉/下拉电阻配置错误", 0.6),
            ("终端电阻不匹配", 0.5),
            ("信号完整性问题", 0.4),
        ],
        "电源问题": [
            ("去耦电容缺失", 0.7),
            ("LDO 负载能力不足", 0.5),
            ("电源完整性问题", 0.6),
        ],
        "发热问题": [
            ("散热设计不足", 0.7),
            ("功耗超出预期", 0.6),
            ("短路或漏电", 0.5),
        ],
        "信号问题": [
            ("ESD 器件寄生电容过大", 0.6),
            ("阻抗不匹配", 0.5),
            ("串扰问题", 0.4),
        ],
    }

    all_hypotheses = []
    for symptom in symptoms:
        category = symptom["category"]
        if category in symptom_to_hypothesis:
            for desc, conf in symptom_to_hypothesis[category]:
                all_hypotheses.append({
                    "description": f"{symptom['description']} -> {desc}",
                    "confidence": conf * 0.8  # 初始置信度折扣
                })

    if not all_hypotheses:
        return None

    # 返回置信度最高的假设
    return max(all_hypotheses, key=lambda x: x["confidence"])
```

### 4.6 Report Generator Node (报告生成节点)

```python
# ============================================
# Report Generator Node - 报告生成
# ============================================

def report_generator_node(state: HardwareAgentState) -> HardwareAgentState:
    """
    报告生成节点：生成最终审查报告或诊断报告

    输出格式:
    - 审查模式：违规项列表 + 总体评价
    - 诊断模式：根因分析 + 修复建议
    """

    task_type = state["task_type"]

    if task_type == TaskType.REVIEW:
        report = generate_review_report(state)
    elif task_type == TaskType.DIAGNOSIS:
        report = generate_diagnosis_report(state)
    else:
        report = generate_spec_query_report(state)

    # 记录报告步骤
    report_step = ExecutionStep(
        step_id=len(state["execution_trace"]) + 1,
        step_type="report",
        node=NodeName.REPORT_GENERATOR,
        content="生成最终报告",
        metadata={"report_length": len(report)}
    )

    return {
        "final_report": report,
        "execution_trace": [report_step],
        "should_continue": False
    }


def generate_review_report(state: HardwareAgentState) -> str:
    """生成原理图审查报告"""

    violations = state["violations"]
    context = state["context"]
    tool_call_count = state["tool_call_count"]

    # 统计违规
    error_count = sum(1 for v in violations if v.severity == "ERROR")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")

    report_parts = [
        "# 原理图审查报告\n",
        f"**审查时间**: {context.get('start_time', 'N/A')}",
        f"**工具调用**: {tool_call_count} 次\n",
        "---\n",
        f"## 审查结果汇总\n",
        f"| 严重程度 | 数量 |",
        f"|----------|------|",
        f"| ERROR | {error_count} |",
        f"| WARNING | {warning_count} |",
        f"| **总计** | {len(violations)} |\n",
    ]

    if violations:
        report_parts.append("---\n## 违规详情\n\n")

        # 按严重程度分组
        errors = [v for v in violations if v.severity == "ERROR"]
        warnings = [v for v in violations if v.severity == "WARNING"]

        if errors:
            report_parts.append("### ERROR 级别\n\n")
            for v in errors:
                report_parts.append(
                    f"#### {v.refdes}: {v.rule_name}\n"
                    f"- **规则ID**: {v.rule_id}\n"
                    f"- **描述**: {v.description}\n"
                    f"- **证据**: {v.evidence}\n\n"
                )

        if warnings:
            report_parts.append("### WARNING 级别\n\n")
            for v in warnings:
                report_parts.append(
                    f"#### {v.refdes}: {v.rule_name}\n"
                    f"- **描述**: {v.description}\n\n"
                )
    else:
        report_parts.append("## 审查结论\n\n")
        report_parts.append("**✅ 未发现设计违规项，原理图符合审查规则。**\n")

    # 总体评价
    if error_count > 0:
        report_parts.append("---\n## 总体评价\n\n")
        report_parts.append("⚠️ **存在 ERROR 级别违规，建议修改后再进行下一阶段设计。**\n")
    elif warning_count > 0:
        report_parts.append("---\n## 总体评价\n\n")
        report_parts.append("ℹ️ **存在 WARNING 级别提示，建议确认是否符合设计意图。**\n")
    else:
        report_parts.append("---\n## 总体评价\n\n")
        report_parts.append("✅ **设计符合规范，通过审查。**\n")

    return "".join(report_parts)


def generate_diagnosis_report(state: HardwareAgentState) -> str:
    """生成故障诊断报告"""

    hypotheses = state["hypotheses"]
    visited_nodes = state["visited_nodes"]
    context = state["context"]
    tool_call_count = state["tool_call_count"]

    # 按置信度排序假设
    hypotheses_sorted = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)

    report_parts = [
        "# 故障诊断报告\n",
        f"**诊断时间**: {context.get('start_time', 'N/A')}",
        f"**工具调用**: {tool_call_count} 次\n",
        "---\n",
    ]

    if hypotheses_sorted:
        # 根因分析
        top_hyp = hypotheses_sorted[0]
        report_parts.extend([
            "## 根因分析\n\n",
            f"**最可能根因** (置信度: {top_hyp.confidence:.0%}):\n\n",
            f"{top_hyp.description}\n\n",
        ])

        # 支持证据
        if top_hyp.evidence:
            report_parts.extend([
                "### 支持证据\n\n",
            ])
            for i, evidence in enumerate(top_hyp.evidence[:5], 1):
                report_parts.append(f"{i}. {evidence}\n")

        # 反面证据
        if top_hyp.counter_evidence:
            report_parts.extend([
                "\n### 反面证据\n\n",
            ])
            for i, evidence in enumerate(top_hyp.counter_evidence[:3], 1):
                report_parts.append(f"{i}. {evidence}\n")

        # 候选假设
        if len(hypotheses_sorted) > 1:
            report_parts.extend([
                "\n---\n## 候选根因 (按置信度排序)\n\n",
                "| 假设 | 置信度 | 证据数 |",
                "|------|--------|------|\n",
            ])
            for hyp in hypotheses_sorted[1:5]:
                report_parts.append(
                    f"| {hyp.description[:50]}... | {hyp.confidence:.0%} | "
                    f"{len(hyp.evidence)} |\n"
                )

        # 修复建议
        report_parts.extend([
            "\n---\n## 修复建议\n\n",
            generate_fix_suggestions(top_hyp.description),
        ])

    else:
        report_parts.append("## 诊断结果\n\n")
        report_parts.append(
            "⚠️ **无法确定根因，建议提供更多故障现象信息或联系硬件专家。**\n"
        )

    # 排查路径
    if visited_nodes:
        report_parts.extend([
            "\n---\n## 已排查节点\n\n",
            f"共排查 {len(visited_nodes)} 个器件节点:\n\n",
            ", ".join(sorted(visited_nodes)[:20]),
            f"{'...' if len(visited_nodes) > 20 else ''}\n",
        ])

    return "".join(report_parts)


def generate_fix_suggestions(hypothesis: str) -> str:
    """根据假设生成修复建议"""

    suggestions = []

    if "ESD" in hypothesis:
        suggestions.extend([
            "1. 检查 ESD 保护器件规格，确保寄生电容满足信号速率要求",
            "2. 对于 USB 3.0/HDMI 等高速信号，建议使用电容 < 0.5pF 的 ESD 保护器件",
            "3. 推荐器件: USBLC6-2SC6 (ST), RCLAMP0521P (Semtech)",
            "",
        ])

    if "去耦电容" in hypothesis or "电源" in hypothesis:
        suggestions.extend([
            "1. 按照 Datasheet 要求配置去耦电容",
            "2. 每个电源引脚建议至少配置 0.1µF 陶瓷电容",
            "3. 高频应用建议增加 10µF 钽电容或固态电容",
            "",
        ])

    if "上拉电阻" in hypothesis or "I2C" in hypothesis:
        suggestions.extend([
            "1. I2C 总线必须在 SCL/SDA 上配置 2.2kΩ-10kΩ 上拉电阻",
            "2. 电阻值选择需考虑总线电容和上升时间要求",
            "3. 计算公式: R = (VDD - 0.4) / (3mA)",
            "",
        ])

    if "散热" in hypothesis:
        suggestions.extend([
            "1. 检查器件功耗是否超出预期",
            "2. 增加散热焊盘和热过孔",
            "3. 考虑增加散热片或风扇",
            "",
        ])

    if not suggestions:
        suggestions.append("1. 建议联系硬件专家进行进一步分析\n")

    return "\n".join(suggestions)
```

---

## 5. 状态机构建

```python
# ============================================
# LangGraph 状态机构建
# ============================================

from langgraph.graph import StateGraph, END


def build_hardware_agent_graph() -> StateGraph:
    """
    构建硬件 Agent 状态机

    图结构:
    entry -> task_classifier -> reasoning -> tool_executor
                                        |           |
                                        v           v
                               review_specific  diagnosis_specific
                                        |           |
                                        v           v
                               hypothesis_evaluator (diagnosis only)
                                        |
                                        v
                                  report_generator -> end
    """

    # 创建图
    graph = StateGraph(HardwareAgentState)

    # 添加节点
    graph.add_node(NodeName.ENTRY, entry_node)
    graph.add_node(NodeName.TASK_CLASSIFIER, task_classifier_node)
    graph.add_node(NodeName.REASONING, reasoning_node)
    graph.add_node(NodeName.TOOL_EXECUTOR, tool_executor_node)
    graph.add_node(NodeName.REVIEW_SPECIFIC, review_specific_node)
    graph.add_node(NodeName.DIAGNOSIS_SPECIFIC, diagnosis_specific_node)
    graph.add_node(NodeName.HYPOTHESIS_EVALUATOR, hypothesis_evaluator_node)
    graph.add_node(NodeName.REPORT_GENERATOR, report_generator_node)
    graph.add_node(NodeName.HITL_HANDLER, hitl_handler_node)

    # 设置入口点
    graph.set_entry_point(NodeName.ENTRY)

    # 添加边
    graph.add_edge(NodeName.ENTRY, NodeName.TASK_CLASSIFIER)

    # Task Classifier 分支
    graph.add_conditional_edges(
        NodeName.TASK_CLASSIFIER,
        classify_task,
        {
            TaskType.REVIEW: NodeName.REASONING,
            TaskType.DIAGNOSIS: NodeName.REASONING,
            TaskType.SPEC_QUERY: NodeName.REASONING,
        }
    )

    # Reasoning 后的条件边
    graph.add_conditional_edges(
        NodeName.REASONING,
        lambda state: state["context"].get("next_action", {}).get("action", "generate_report"),
        {
            "query_graph": NodeName.TOOL_EXECUTOR,
            "search_knowledge": NodeName.TOOL_EXECUTOR,
            "execute_review": NodeName.REVIEW_SPECIFIC,
            "execute_diagnosis": NodeName.DIAGNOSIS_SPECIFIC,
            "generate_report": NodeName.REPORT_GENERATOR,
        }
    )

    # Tool Executor 循环回 Reasoning
    graph.add_edge(NodeName.TOOL_EXECUTOR, NodeName.REASONING)

    # 审查分支
    graph.add_edge(NodeName.REVIEW_SPECIFIC, NodeName.REPORT_GENERATOR)

    # 诊断分支
    graph.add_edge(NodeName.DIAGNOSIS_SPECIFIC, NodeName.HYPOTHESIS_EVALUATOR)
    graph.add_conditional_edges(
        NodeName.HYPOTHESIS_EVALUATOR,
        lambda state: "continue" if state["should_continue"] else "done",
        {
            "continue": NodeName.REASONING,
            "done": NodeName.REPORT_GENERATOR,
        }
    )

    # HITL 处理 (可选中断)
    graph.add_edge(NodeName.HITL_HANDLER, NodeName.REASONING)

    # 报告生成后结束
    graph.add_edge(NodeName.REPORT_GENERATOR, END)

    return graph.compile()


def task_classifier_node(state: HardwareAgentState) -> HardwareAgentState:
    """任务分类器节点"""
    task_type = classify_task(state)
    return {"task_type": task_type}


def hypothesis_evaluator_node(state: HardwareAgentState) -> HardwareAgentState:
    """假设评估器节点 - 判断是否继续搜索"""
    hypotheses = state["hypotheses"]

    if not hypotheses:
        return {"should_continue": True}

    # 检查置信度是否已收敛
    top_hyp = max(hypotheses, key=lambda h: h.confidence)

    # 置信度 > 90% 或 工具调用次数过多，终止
    if top_hyp.confidence >= 0.9:
        return {"should_continue": False}

    if state["tool_call_count"] >= state["context"].get("max_tool_calls", 20) - 2:
        return {"should_continue": False}

    return {"should_continue": True}


def hitl_handler_node(state: HardwareAgentState) -> HardwareAgentState:
    """Human-in-the-Loop 处理器"""
    # 处理用户对违规项的反馈
    # 例如：将违规项加入白名单
    return state
```

---

## 6. Agent 运行接口

```python
# ============================================
# Agent 运行接口
# ============================================

class HardwareAgent:
    """
    硬件 AI 专家系统 Agent

    使用示例:
    ```python
    agent = HardwareAgent(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        llm_model="qwen-max"
    )

    # 原理图审查
    result = agent.review(
        user_input="检查所有 1.8V 电源网络的去耦电容配置",
        rules=["POWER_DECAP", "ESD_PROTECTION"]
    )

    # 故障诊断
    result = agent.diagnose(
        user_input="USB 接口无法识别设备"
    )

    # 获取执行流 (用于 UI 展示)
    for step in result["execution_trace"]:
        print(f"[{step.step_type}] {step.content}")
    ```
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        llm_model: str = "qwen-max",
        max_tool_calls: int = 20,
    ):
        self.graph = build_hardware_agent_graph()
        self.max_tool_calls = max_tool_calls

        # 初始化工具
        from agent_system.graph_tools import init_graph_tools
        init_graph_tools(neo4j_uri, neo4j_user, neo4j_password)

        # 初始化 LLM
        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(
            model=llm_model,
            temperature=0.0,
        )

    def review(
        self,
        user_input: str,
        rules: list[str] = None,
        **kwargs
    ) -> dict:
        """
        执行原理图审查

        Args:
            user_input: 审查指令
            rules: 指定审查规则 (None 表示全部规则)

        Returns:
            审查结果字典
        """
        initial_state = self._create_initial_state(
            task_type=TaskType.REVIEW,
            user_input=user_input,
            context={"rules": rules or []}
        )

        result = self.graph.invoke(initial_state)
        return self._format_result(result)

    def diagnose(
        self,
        user_input: str,
        **kwargs
    ) -> dict:
        """
        执行故障诊断

        Args:
            user_input: 故障描述

        Returns:
            诊断结果字典
        """
        initial_state = self._create_initial_state(
            task_type=TaskType.DIAGNOSIS,
            user_input=user_input,
            context={}
        )

        result = self.graph.invoke(initial_state)
        return self._format_result(result)

    def query_spec(
        self,
        user_input: str,
        **kwargs
    ) -> dict:
        """
        执行规格查询

        Args:
            user_input: 查询内容

        Returns:
            查询结果字典
        """
        initial_state = self._create_initial_state(
            task_type=TaskType.SPEC_QUERY,
            user_input=user_input,
            context={}
        )

        result = self.graph.invoke(initial_state)
        return self._format_result(result)

    def _create_initial_state(
        self,
        task_type: str,
        user_input: str,
        context: dict
    ) -> dict:
        """创建初始状态"""

        return {
            "messages": [AgentMessage(role="user", content=user_input)],
            "task_type": task_type,
            "hypotheses": [],
            "visited_nodes": set(),
            "visited_paths": set(),
            "tool_call_count": 0,
            "execution_trace": [],
            "violations": [],
            "context": {
                **context,
                "max_tool_calls": self.max_tool_calls,
            },
            "should_continue": True,
        }

    def _format_result(self, state: dict) -> dict:
        """格式化输出结果"""
        return {
            "status": "success" if state.get("final_report") else "error",
            "task_type": state["task_type"],
            "report": state.get("final_report", ""),
            "error": state.get("error_message"),
            "violations": [
                v.model_dump() for v in state.get("violations", [])
            ],
            "hypotheses": [
                h.model_dump() for h in state.get("hypotheses", [])
            ],
            "execution_trace": [
                {
                    "id": s.step_id,
                    "type": s.step_type,
                    "node": s.node,
                    "content": s.content,
                    "metadata": s.metadata,
                }
                for s in state.get("execution_trace", [])
            ],
            "tool_call_count": state["tool_call_count"],
            "visited_nodes": list(state["visited_nodes"]),
        }
```

---

## 7. 文件结构

```
agent_system/
├── __init__.py
├── agent_core.py          # 本文档 - 核心状态机
├── graph_tools.py         # Neo4j 图谱工具
├── knowledge_router.py    # 三级检索路由
├── review_rules.py        # 审查规则库
├── datasheet_processor.py  # Qianfan-OCR 解析
├── datasheet_linker.py     # Datasheet 关联
└── schemas.py             # Pydantic 数据模型
```

---

## 8. 依赖

```python
# requirements.txt

# Core
langgraph>=0.1
langchain-core>=0.2
langchain-openai>=0.1

# Database
neo4j>=5.0

# Validation
pydantic>=2.0

# Optional: For local LLM
# vllm>=0.3
# transformers>=4.30
```

---

## 9. 后续工作

1. **Pydantic Schema 分离**: 将数据模型移到 `schemas.py`
2. **错误处理增强**: 添加重试机制和超时控制
3. **性能优化**: 批量工具调用、缓存机制
4. **监控指标**: 添加 Prometheus metrics
5. **集成测试**: 编写端到端测试用例
