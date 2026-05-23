"""
统一 ReAct Agent — 覆盖审查/诊断/查询三种任务

核心思路：
- 不再区分硬编码状态机和 ReAct 引擎
- 所有任务类型统一走 ReAct 循环：Thought → Action → Observation → ...
- LLM 自主选择工具、自主决定何时输出最终结论
- 内置防死循环保护：步数限制 + 同工具重复检测 + 强制收敛

工具集：
1. graph_tools — Neo4j 图谱查询（7 个）
2. review_engine — 规则审查（run_review）
3. knowledge_search — 知识库语义搜索
4. component_summary — 器件概览

与旧版对比：
- 旧 agent_core.py: 状态机 + 诊断专用 ReAct，review/query 走硬编码
- 新版: 统一 ReAct，LLM 根据用户问题自主推理、选工具、综合结论
"""

from __future__ import annotations

import json
import logging
import re
import inspect
from datetime import datetime
from typing import Optional, Dict, Any, List

from agent_system.llm_client import LLMClient
from agent_system.graph_tools import (
    get_graph_summary,
    get_component_nets,
    get_net_components,
    get_power_domain,
    get_power_tree,
    get_i2c_devices,
    get_signal_path,
    find_common_cause,
    analyze_power_sequence,
    trace_signal_path,
    get_graph_tools as _get_all_graph_tools,
)
from agent_system.knowledge_router import KnowledgeRouter
from agent_system.review_engine import ReviewRuleEngine
from agent_system.schemas import (
    ReActDecision,
    ReActTraceStep,
    Violation,
    Hypothesis,
)

logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

MAX_REACT_STEPS = 10
SAME_TOOL_REPEAT_LIMIT = 3
OBSERVATION_TRUNCATE = 1200
TOOL_RESULT_TRUNCATE = 3000
MAX_HISTORY_STEPS = 6


# ============================================================
# 工具注册
# ============================================================

# 图谱工具
GRAPH_TOOLS = {
    "get_graph_summary": get_graph_summary,
    "get_component_nets": get_component_nets,
    "get_net_components": get_net_components,
    "get_power_domain": get_power_domain,
    "get_power_tree": get_power_tree,
    "get_i2c_devices": get_i2c_devices,
    "get_signal_path": get_signal_path,
    "find_common_cause": find_common_cause,
    "analyze_power_sequence": analyze_power_sequence,
    "trace_signal_path": trace_signal_path,
}


def _run_review(rule_ids: list = None) -> str:
    """执行规则审查引擎（返回摘要）"""
    try:
        from agent_system.graph_tools import _get_driver
        driver = _get_driver()
        engine = ReviewRuleEngine(driver)
        violations = engine.run_rules(rule_ids=rule_ids, enabled_only=True)

        # 只返回摘要，不返回完整报告
        by_rule = {}
        by_severity = {}
        for v in violations:
            by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1
            sev = v.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1

        summary = f"审查完成: 共 {len(violations)} 个违规\n"
        summary += "按规则: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_rule.items(), key=lambda x: -x[1])) + "\n"
        summary += "按严重度: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_severity.items(), key=lambda x: -x[1])) + "\n"

        # 只展示前 10 条典型违规
        if violations:
            summary += "\n典型违规 (前10条):\n"
            for v in violations[:10]:
                summary += f"  - [{v.severity}] {v.rule_id}: {v.description[:100]}\n"
            if len(violations) > 10:
                summary += f"  ... 还有 {len(violations) - 10} 条\n"

        return summary
    except Exception as e:
        return f"[审查引擎错误] {e}"


def _search_knowledge(query: str, mpn: str = "") -> str:
    """搜索知识库"""
    try:
        router = KnowledgeRouter()
        result = router.search(mpn=mpn or "general", query=query)
        if result.status == "success" and result.content:
            content = result.content
            if len(content) > TOOL_RESULT_TRUNCATE:
                content = content[:TOOL_RESULT_TRUNCATE] + "\n[截断]"
            return f"[知识库搜索] query='{query}' mpn='{mpn}'\n置信度: {result.confidence:.2f}\n来源: {result.source}\n\n{content}"
        else:
            return f"[知识库] 未找到相关内容 (query='{query}', mpn='{mpn}')"
    except Exception as e:
        return f"[知识库搜索错误] {e}"


# 扩展工具集：图谱 + 审查 + 知识库
ALL_TOOLS = dict(GRAPH_TOOLS)
ALL_TOOLS["run_review"] = _run_review
ALL_TOOLS["search_knowledge"] = _search_knowledge


# ============================================================
# 工具 Schema（供 LLM 选择）
# ============================================================

def _build_tool_schemas() -> list[dict]:
    """构建工具描述列表"""
    schemas = []

    # 图谱工具 — 从 LangChain StructuredTool 提取
    for tool_obj in _get_all_graph_tools():
        desc = getattr(tool_obj, 'description', '') or ''
        if "预留接口" in desc:
            continue
        if not hasattr(tool_obj, 'func'):
            continue  # skip non-StructuredTool entries
        fn = tool_obj.func
        sig = inspect.signature(fn)
        params = {}
        required = []
        for pname, param in sig.parameters.items():
            if pname in ("args", "kwargs"):
                continue
            ptype = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    ptype = "integer"
                elif param.annotation == bool:
                    ptype = "boolean"
                elif param.annotation == float:
                    ptype = "number"
            params[pname] = {"type": ptype, "description": pname}
            if param.default == inspect.Parameter.empty:
                required.append(pname)
        schemas.append({
            "name": tool_obj.name,
            "description": (tool_obj.description or "").strip().split("\n")[0],
            "parameters": {"type": "object", "properties": params, "required": required},
        })

    # 审查引擎
    schemas.append({
        "name": "run_review",
        "description": "运行原理图规则审查引擎，检查设计违规。建议只传入相关规则ID，避免全量运行耗时过长。",
        "parameters": {
            "type": "object",
            "properties": {
                "rule_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要运行的规则ID列表，为空则运行全部(慢)。建议只选相关规则！可选: I2C_STD_PULLUP, OPENDRAIN_PULLUP, POWER_3V3_DECAP, POWER_1V8_DECAP, POWER_5V0_DECAP, EXTERNAL_IO_ESD, NC_FLOATING_CHECK, AMR_RESISTOR_POWER, USB_ESD_PROTECTION, ETHERNET_ESD_PROTECTION",
                },
            },
            "required": [],
        },
    })

    # 知识库搜索
    schemas.append({
        "name": "search_knowledge",
        "description": "搜索硬件设计知识库（设计指南、降额规范、ESD要求等）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题描述"},
                "mpn": {"type": "string", "description": "器件型号（可选，用于过滤）"},
            },
            "required": ["query"],
        },
    })

    return schemas


TOOL_SCHEMAS = _build_tool_schemas()


# ============================================================
# ReAct Agent 主类
# ============================================================

class ReActAgent:
    """
    统一 ReAct Agent

    用法：
        agent = ReActAgent()
        result = agent.run("帮我审查 I2C 上拉电阻")
        print(result["report"])
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.tool_schemas = TOOL_SCHEMAS
        self.tool_map = ALL_TOOLS

    # --------------------------------------------------------
    # System Prompt
    # --------------------------------------------------------

    def _build_system_prompt(self, task_type_hint: str = "") -> str:
        """构建 ReAct 系统提示"""
        tool_lines = []
        for t in self.tool_schemas:
            req = ", ".join(t["parameters"].get("required", [])) or "无"
            desc = t["description"]
            tool_lines.append(f"  - {t['name']}: {desc} (必填: {req})")

        task_guidance = ""
        if task_type_hint == "review":
            task_guidance = (
                "\n## Task Guidance: Review\n"
                "The user wants a schematic design review. Recommended approach:\n"
                "1. Call run_review to execute rule checks (optionally with specific rule_ids)\n"
                "2. If you need more context on specific violations, use get_i2c_devices/get_power_domain/get_net_components\n"
                "3. After run_review, you should summarize findings in final_answer. Do NOT call run_review again.\n"
                "4. Focus on the most severe findings (ERROR level) and provide actionable recommendations.\n"
            )
        elif task_type_hint == "diagnosis":
            task_guidance = (
                "\n## Task Guidance: Diagnosis\n"
                "The user has a hardware failure. Follow this systematic approach:\n"
                "\n"
                "### Step 1: Understand the symptom (1 tool call)\n"
                "- If the symptom involves a specific component, call get_component_nets(refdes=...) to see its connections\n"
                "- If the symptom involves a power issue, call get_power_tree(refdes=...) or analyze_power_sequence(refdes=...)\n"
                "- If the symptom involves signal integrity, call trace_signal_path(start_pin=...)\n"
                "\n"
                "### Step 2: Expand investigation (1-2 tool calls)\n"
                "- For power issues: find_common_cause(refdes_list=[...]) to check shared upstream\n"
                "- For signal issues: get_signal_path(from=..., to=...) to check connectivity\n"
                "- For unknown component behavior: search_knowledge(query=...) to check datasheet specs\n"
                "\n"
                "### Step 3: Cross-reference (0-1 tool calls)\n"
                "- Use get_i2c_devices() if I2C bus issues suspected\n"
                "- Use get_power_domain(voltage_level=...) if power rail issues suspected\n"
                "- Use search_knowledge(query=...) for failure patterns or spec limits\n"
                "\n"
                "### Step 4: Conclude\n"
                "- Output final_answer with: Root Cause, Evidence, Recommendations\n"
                "- Include specific voltage values, component refs, and net names\n"
                "\n"
                "### Decision Rules for Diagnosis\n"
                "- Do NOT call run_review for diagnosis tasks (it's for design review, not failure analysis)\n"
                "- Do NOT call more than 4 graph tools total before concluding\n"
                "- Do NOT call the same tool with the same parameters twice\n"
                "- If you already have enough evidence from 2-3 tools, conclude immediately\n"
            )
        elif task_type_hint == "query":
            task_guidance = (
                "\n## Task Guidance: Query\n"
                "The user wants information about a component, net, or design rule.\n"
                "1. Use graph tools to look up specific components/nets\n"
                "2. Search knowledge base for specs/guidelines\n"
                "3. Provide a clear, structured answer\n"
            )

        return (
            "You are Jarvis, a hardware design expert AI. You analyze schematic designs using graph database and knowledge base tools.\n\n"
            "## Rules\n"
            "1. Think step-by-step. Decide what information you need before choosing a tool.\n"
            "2. Choose ONE tool per step. Analyze the observation before the next step.\n"
            "3. Do NOT repeat the same tool with the same parameters.\n"
            "4. When you have enough evidence, output final_answer.\n"
            "5. Keep thoughts concise (1-3 sentences).\n"
            "6. In final_answer, provide a well-structured Markdown report in Chinese.\n"
            f"{task_guidance}\n"
            "## Available Tools\n"
            + "\n".join(tool_lines)
            + "\n\n## Output Format\n"
            'Respond ONLY with a JSON object:\n'
            '{"thought": "推理过程", "action": "tool_name", "action_input": {"param": "value"}, "is_final": false}\n\n'
            'When ready to conclude:\n'
            '{"thought": "已收集足够信息", "action": "final_answer", "final_answer": "## 结论\\n...", "is_final": true}\n\n'
            "## Decision Rules\n"
            "- After run_review, you ALREADY have all violation data. Do NOT call run_review again.\n"
            "- If you called run_review and got results, you should output final_answer within 1-2 more steps.\n"
            "- If you called 2+ graph tools after run_review, you should output final_answer.\n"
            "- NEVER call more than 3 get_net_components/get_component_nets in total.\n"
            "Respond ONLY with valid JSON. No markdown fences, no extra text."
        )

    # --------------------------------------------------------
    # History Formatting
    # --------------------------------------------------------

    def _format_history(self, trace: list[ReActTraceStep]) -> str:
        """格式化 ReAct 历史（带截断 + 已调用工具摘要）"""
        if not trace:
            return "（无历史记录）"

        lines = []
        total = len(trace)

        if total > MAX_HISTORY_STEPS:
            early = trace[:total - MAX_HISTORY_STEPS]
            lines.append(f"[前 {len(early)} 步摘要]")
            for s in early:
                obs = s.observation[:80].replace("\n", " ")
                lines.append(f"  Step {s.step_id}: {s.action} → {obs}...")
            lines.append("")

        recent = trace[-MAX_HISTORY_STEPS:]
        for s in recent:
            lines.append(f"Step {s.step_id}:")
            lines.append(f"  Thought: {s.thought}")
            lines.append(f"  Action: {s.action}({json.dumps(s.action_input, ensure_ascii=False)})")
            obs = s.observation[:OBSERVATION_TRUNCATE]
            if len(s.observation) > OBSERVATION_TRUNCATE:
                obs += " ... [截断]"
            lines.append(f"  Observation: {obs}")

        # 已调用工具摘要（防止 LLM 重复调用）
        tool_calls = {}
        for s in trace:
            key = f"{s.action}({json.dumps(s.action_input, ensure_ascii=False)})"
            tool_calls.setdefault(s.action, []).append(key)
        lines.append("")
        lines.append("[已调用工具 — 不要重复相同调用]")
        for tool, calls in tool_calls.items():
            lines.append(f"  {tool}: {len(calls)}次 — {', '.join(calls[:3])}")

        return "\n".join(lines)

    # --------------------------------------------------------
    # LLM Decision
    # --------------------------------------------------------

    def _llm_decide(self, user_input: str, history: str, system_prompt: str, force_final: bool = False) -> ReActDecision:
        """调用 LLM 做下一步决策"""
        prompt = (
            f"## User Request\n{user_input}\n\n"
            f"## History\n{history}\n\n"
            f"## Next Step\nDecide the next action based on the user request and previous observations."
        )

        if force_final:
            system_prompt += (
                "\n\n## CRITICAL\n"
                "You MUST now output ONLY a final_answer JSON. "
                "Do NOT select any tool. Set is_final=true. "
                "Provide a comprehensive conclusion in Chinese."
            )

        # 尝试 chat_json
        result = self.llm.chat_json(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=1024,
        )

        # Fallback: 原始文本宽松解析
        if result is None:
            logger.warning("chat_json failed, trying raw text fallback")
            try:
                resp = self.llm.chat(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.2,
                    max_tokens=1024,
                    strip_thinking=True,
                )
                result = self._fallback_parse(resp.content)
            except Exception as e:
                logger.error(f"Raw text fallback failed: {e}")

        if result is None:
            return ReActDecision(
                thought="LLM 调用失败",
                action="final_answer",
                final_answer="## 处理失败\n\nLLM 决策调用失败，请检查模型服务状态。",
                is_final=True,
            )

        # 校验 action
        action = result.get("action", "final_answer")
        is_final = result.get("is_final", False)

        if force_final and not is_final and action in self.tool_map:
            action = "final_answer"
            is_final = True
            result.setdefault("final_answer", self._generate_fallback_report(history))

        if action not in self.tool_map and action != "final_answer":
            action = "final_answer"
            is_final = True
            result.setdefault("final_answer", "## 处理异常\n\nLLM 选择了无效工具。")

        return ReActDecision(
            thought=result.get("thought", ""),
            action=action,
            action_input=result.get("action_input", {}),
            final_answer=result.get("final_answer"),
            is_final=is_final,
        )

    @staticmethod
    def _fallback_parse(text: str) -> Optional[dict]:
        """宽松解析非结构化文本 — 复用 LLMClient._extract_json"""
        if not text:
            return None

        # 复用 LLMClient._extract_json（括号平衡+thinking清洗+截断修复）
        parsed = LLMClient._extract_json(text)
        if parsed and "action" in parsed:
            return parsed

        # 关键词匹配
        lower = text.lower()
        if "final" in lower or "结论" in text or "总结" in text:
            return {"thought": "LLM 输出含结论", "action": "final_answer", "final_answer": text[:2000], "is_final": True}

        for tool_name in ALL_TOOLS:
            if tool_name in text:
                return {"thought": f"提取到工具: {tool_name}", "action": tool_name, "action_input": {}, "is_final": False}

        return None

    @staticmethod
    def _generate_fallback_report(history: str) -> str:
        """兜底报告"""
        return (
            "## 分析结论\n\n"
            "根据已收集的信息：\n\n"
            f"{history[:2000]}\n\n"
            "---\n[系统生成摘要]"
        )

    # --------------------------------------------------------
    # Tool Execution
    # --------------------------------------------------------

    def _execute_tool(self, action: str, action_input: dict) -> str:
        """执行工具调用"""
        if action not in self.tool_map:
            return f"[错误] 未知工具: {action}"

        tool_fn = self.tool_map[action]
        try:
            # 图谱工具用 .invoke()，Python 函数直接调用
            if hasattr(tool_fn, "invoke"):
                result = tool_fn.invoke(action_input)
            else:
                result = tool_fn(**action_input)

            text = str(result) if result else "（无返回内容）"
            if len(text) > TOOL_RESULT_TRUNCATE:
                text = text[:TOOL_RESULT_TRUNCATE] + f"\n\n[截断，原始 {len(text)} 字符]"
            return text
        except Exception as e:
            return f"[工具错误] {action}: {e}"

    # --------------------------------------------------------
    # Task Type Detection
    # --------------------------------------------------------

    @staticmethod
    def _detect_task_type(user_input: str) -> str:
        """轻量关键词分类（无需 LLM）"""
        s = user_input.lower()
        review_kw = ["审查", "检查", "review", "合规", "违规", "去耦", "上拉", "esd", "降额"]
        diagnosis_kw = ["故障", "失效", "error", "黑屏", "死机", "诊断", "掉电", "不工作", "无法启动", "boot失败"]

        review_score = sum(1 for kw in review_kw if kw in s)
        diagnosis_score = sum(1 for kw in diagnosis_kw if kw in s)

        if diagnosis_score > review_score:
            return "diagnosis"
        elif review_score > 0:
            return "review"
        else:
            return "query"

    # --------------------------------------------------------
    # Main ReAct Loop
    # --------------------------------------------------------

    def run(self, user_input: str, task_type: str = "") -> dict:
        """
        执行统一 ReAct 循环

        Args:
            user_input: 用户输入
            task_type: 任务类型提示 (review/diagnosis/query)，为空则自动检测

        Returns:
            dict: {status, report, execution_trace, tool_call_count, ...}
        """
        if not task_type:
            task_type = self._detect_task_type(user_input)

        system_prompt = self._build_system_prompt(task_type)
        trace: list[ReActTraceStep] = []
        tool_call_count = 0
        error_message = None
        final_report = ""

        force_final_next = False

        for step in range(MAX_REACT_STEPS):
            history = self._format_history(trace)
            force_final = force_final_next or step >= MAX_REACT_STEPS - 2
            force_final_next = False

            decision = self._llm_decide(user_input, history, system_prompt, force_final=force_final)

            if decision.is_final or decision.action == "final_answer":
                final_report = decision.final_answer or "## 处理完成\n\nLLM 未输出结论。"
                break

            # 执行工具
            observation = self._execute_tool(decision.action, decision.action_input)
            tool_call_count += 1

            # 智能收敛检测：如果已经调用 4+ 个工具且最后一步是图谱工具，强制下一轮总结
            graph_tool_count = sum(1 for t in trace if t.action in GRAPH_TOOLS)
            if graph_tool_count >= 4 and decision.action in GRAPH_TOOLS:
                logger.info(f"Smart convergence: {graph_tool_count} graph tools called, forcing final")
                # 不强制，但设置 flag 让下一轮 force_final
                force_final_next = True
            else:
                force_final_next = False

            trace.append(ReActTraceStep(
                step_id=step + 1,
                thought=decision.thought,
                action=decision.action,
                action_input=decision.action_input,
                observation=observation,
            ))

            # 防死循环
            recent_same = sum(
                1 for t in trace[-SAME_TOOL_REPEAT_LIMIT:]
                if t.action == decision.action and t.action_input == decision.action_input
            )
            if recent_same >= SAME_TOOL_REPEAT_LIMIT:
                error_message = f"工具 {decision.action} 重复调用超限，强制终止"
                final_report = f"## 分析异常终止\n\n{error_message}\n\n## 已收集信息\n\n" + self._summarize_trace(trace)
                break
        else:
            error_message = f"达到最大步数限制 ({MAX_REACT_STEPS})"
            final_report = f"## 分析超时\n\n{error_message}\n\n## 已收集信息\n\n" + self._summarize_trace(trace)

        return {
            "status": "success" if not error_message else "timeout",
            "task_type": task_type,
            "report": final_report,
            "error": error_message,
            "execution_trace": [
                {
                    "step_id": t.step_id,
                    "thought": t.thought,
                    "action": t.action,
                    "action_input": t.action_input,
                    "observation": t.observation[:500],
                    "timestamp": t.timestamp,
                }
                for t in trace
            ],
            "tool_call_count": tool_call_count,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def _summarize_trace(trace: list[ReActTraceStep]) -> str:
        if not trace:
            return "无执行记录"
        lines = ["### 执行摘要"]
        for t in trace:
            lines.append(f"- Step {t.step_id}: {t.action} → {t.observation[:100]}...")
        return "\n".join(lines)

    # --------------------------------------------------------
    # 兼容旧版 API
    # --------------------------------------------------------

    def review(self, user_input: str, **kwargs) -> dict:
        """审查任务（兼容旧版）"""
        return self.run(user_input, task_type="review")

    def diagnose(self, user_input: str, **kwargs) -> dict:
        """诊断任务（兼容旧版）"""
        return self.run(user_input, task_type="diagnosis")

    def query_spec(self, user_input: str, **kwargs) -> dict:
        """查询任务（兼容旧版）"""
        return self.run(user_input, task_type="query")


# ============================================================
# 验证
# ============================================================

if __name__ == "__main__":
    import time

    agent = ReActAgent()

    tests = [
        ("review", "帮我审查一下 I2C 上拉电阻是否合规"),
        ("diagnosis", "I2C 总线通信失败，设备无法响应"),
        ("query", "查一下 U4 器件的电源网络连接情况"),
    ]

    for task_type, query in tests:
        print(f"\n{'='*60}")
        print(f"Test: [{task_type}] {query}")
        print(f"{'='*60}")
        t0 = time.time()
        result = agent.run(query, task_type=task_type)
        elapsed = time.time() - t0
        print(f"Status: {result['status']}")
        print(f"Tool calls: {result['tool_call_count']}")
        print(f"Steps: {len(result['execution_trace'])}")
        print(f"Time: {elapsed:.1f}s")
        print(f"Report preview:\n{result['report'][:500]}")
