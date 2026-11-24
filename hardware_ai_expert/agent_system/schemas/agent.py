"""
Agent 状态机数据模型

定义 Agent 状态、消息和结果模型。
对应 Schemas_Design.md Section 4
"""

from __future__ import annotations

from __future__ import annotations

from typing import TypedDict, Literal, Optional, TYPE_CHECKING
try:
    from typing import Annotated, NotRequired
except ImportError:
    from typing_extensions import Annotated, NotRequired
import operator

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent_system.schemas.review import Violation, Hypothesis


# ============================================
# 消息模型
# ============================================


from pydantic import BaseModel, Field


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
    violations: list[Violation]
    selected_rules: list[str]
    review_scope: dict


class DiagnosisState(BaseAgentState):
    """诊断任务状态"""
    hypotheses: Annotated[list[Hypothesis], operator.add]
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
    errors: list[Violation]
    warnings: list[Violation]
    execution_trace: list[ExecutionStep]
    tool_call_count: int


class DiagnosisResult(BaseModel):
    """诊断结果"""
    status: Literal["success", "error"]
    root_cause: Optional[Hypothesis]
    hypotheses: list[Hypothesis]
    visited_nodes_count: int
    execution_trace: list[ExecutionStep]
    tool_call_count: int


# ============================================
# ReAct 决策模型
# ============================================

class ReActDecision(BaseModel):
    """ReAct 单步决策输出"""
    thought: str = Field(..., description="当前推理过程")
    action: str = Field(..., description="要调用的工具名，或 'final_answer'")
    action_input: dict = Field(default_factory=dict, description="工具参数")
    final_answer: Optional[str] = Field(default=None, description="最终回答（当 action='final_answer' 时）")
    is_final: bool = Field(default=False, description="是否结束循环")
    # LLM 本身调用/解析失败时置 True：上层据此把 run 记为 error，而不是 success
    is_error: bool = Field(default=False, description="决策阶段是否发生错误")


class ReActTraceStep(BaseModel):
    """ReAct 执行的单步记录"""
    step_id: int
    thought: str
    action: str
    action_input: dict
    observation: str
    timestamp: str = Field(default_factory=lambda: __import__("datetime").datetime.now().isoformat())
