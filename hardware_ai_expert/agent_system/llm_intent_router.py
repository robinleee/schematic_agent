"""
LLM Intent Router - 本地 LLM 意图分类与路由

核心功能：
  1. 用本地 LLM (Ollama/vLLM) 替代关键词正则，做意图分类
  2. 支持复合意图拆解（如"检查 U1 的电源和上拉电阻"→多个子任务）
  3. 置信度评估 + 兜底澄清策略
  4. 结构化 JSON 输出（LLMClient 封装）

依赖：Ollama (gemma4:26b) 或 vLLM
"""

from __future__ import annotations

import os
import json
import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List
from dotenv import load_dotenv

from agent_system.llm_client import LLMClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

class IntentType(str, Enum):
    # 图谱查询类
    NET_TRACE = "net_trace"              # 追踪网络连接
    COMPONENT_LOOKUP = "component_lookup" # 查询器件信息
    POWER_ANALYSIS = "power_analysis"     # 电源树/域分析
    PINOUT_CHECK = "pinout_check"        # 引脚配置检查
    # 规则审查类
    RULE_REVIEW = "rule_review"          # 执行审查规则
    SCHEMATIC_REVIEW = "schematic_review" # 完整原理图审查
    # 诊断类
    DIAGNOSIS = "diagnosis"             # 故障诊断
    # 知识检索类
    SPEC_SEARCH = "spec_search"          # 查器件规格
    GRAPH_RAG = "graph_rag"             # True GraphRAG 检索
    # 复合/兜底
    COMPOSITE = "composite"             # 复合意图（需拆解）
    CLARIFY = "clarify"                 # 意图不明确，需要澄清
    UNKNOWN = "unknown"


@dataclass
class Intent:
    intent_type: IntentType
    confidence: float          # 0.0-1.0
    entities: dict             # 提取的实体
    sub_intents: List[Intent]  # 复合意图的子意图列表
    raw_query: str = ""        # 原始查询


@dataclass
class RoutingDecision:
    intents: List[Intent]
    strategy: str              # "direct", "composite", "clarify"
    message: str = ""          # 给用户的反馈


# ============================================================
# LLM 调用 (已由 LLMClient 统一封装)
# ============================================================
# 保留 OllamaClient 作为兼容层，内部委托给 LLMClient

class OllamaClient:
    """Ollama API 客户端 (兼容层，委托 LLMClient)"""

    def __init__(self, model: str = None):
        self._client = LLMClient(provider="ollama", model=model)

    def generate(self, prompt: str, temperature: float = 0.1,
                 max_tokens: int = 512) -> str:
        """调用 LLM 生成文本"""
        try:
            resp = self._client.chat(
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.content
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""


# ============================================================
# Prompt 工程
# ============================================================

def _build_classification_prompt(query: str) -> str:
    """构建意图分类 prompt（避免花括号转义问题）"""
    return f"""You are an intent classification engine for a hardware schematic analysis AI.

## Task
Analyze the user's query and classify it into one or more intents. Extract relevant entities.

## Intent Types
- net_trace: Trace a signal net (e.g., "What connects to I2C_SDA?")
- component_lookup: Look up component info (e.g., "What is U1?")
- power_analysis: Power domain/tree analysis (e.g., "Show power tree for U1")
- pinout_check: Pin configuration check (e.g., "Check pinout of U1")
- rule_review: Run specific design rules (e.g., "Check pull-up resistors")
- schematic_review: Full schematic review (e.g., "Review this design")
- spec_search: Search component datasheet (e.g., "What is the voltage rating of TPS5430?")
- graph_rag: Graph-based RAG search (e.g., "Find decoupling recommendations for TPS5430")
- composite: Multiple distinct intents in one query
- clarify: Intent is ambiguous or unclear

## Output Format
Respond ONLY with a JSON object in this exact format:
{{
  "primary_intent": "intent_type",
  "confidence": 0.95,
  "entities": {{
    "refdes": ["U1", "R5"],
    "net_name": "I2C_SDA",
    "mpn": "TPS5430",
    "rule_type": "pull_up"
  }},
  "is_composite": false,
  "sub_queries": []
}}

Rules:
- confidence must be between 0.0 and 1.0
- If is_composite is true, provide sub_queries array with {{"intent": "...", "query": "..."}}
- Extract ALL refdes (U/R/C/L/Q prefix), net names, and MPNs from the query
- If no entities found, use empty objects

## User Query
"{query}"

## JSON Response:"""


CLARIFICATION_PROMPT = """The user's query is ambiguous. Generate a clarification question.

Query: "{query}"
Identified issue: {issue}

Generate a brief, helpful question to clarify the user's intent."""


# ============================================================
# Intent Router 核心
# ============================================================

class LLMIntentRouter:
    """LLM 驱动的意图路由器"""

    # 简单兜底模式：当 LLM 不可用时回退到关键词匹配
    KEYWORD_PATTERNS = {
        IntentType.NET_TRACE: [
            r'连接到?什么', r'网络', r'net', r'连接到?', r'trace', r'连接到',
            r'连到', r'接什么'
        ],
        IntentType.COMPONENT_LOOKUP: [
            r'器件', r'component', r'是什么', r'什么器件', r'U\d+',
        ],
        IntentType.POWER_ANALYSIS: [
            r'电源', r'power', r'供电', r'电压', r'voltage',
            r'电源树', r'power.tree', r'power.tree'
        ],
        IntentType.PINOUT_CHECK: [
            r'引脚', r'pinout', r'pin', r'配置', r'gpio'
        ],
        IntentType.RULE_REVIEW: [
            r'规则', r'rule', r'检查', r'review', r'审查',
            r'上拉', r'下拉', r'pull.?up', r'pull.?down',
            r'去耦', r'decoupling'
        ],
        IntentType.SPEC_SEARCH: [
            r'规格', r'spec', r'datasheet', r'数据手册',
            r'参数', r'rating', r'最大'
        ],
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def route(self, query: str) -> RoutingDecision:
        """
        路由用户查询。

        流程：
        1. 尝试 LLM 分类
        2. 如果 LLM 失败或置信度低，回退到关键词模式
        3. 复合意图拆解
        4. 生成路由决策
        """
        # 尝试 LLM 分类
        llm_result = self._llm_classify(query)

        if llm_result and llm_result.get("confidence", 0) >= 0.6:
            return self._parse_llm_result(query, llm_result)

        # LLM 失败或置信度低，回退到关键词模式
        logger.warning(f"LLM classification failed/low confidence, falling back to keywords: {query}")
        return self._keyword_fallback(query)

    def _llm_classify(self, query: str) -> Optional[dict]:
        """使用 LLM 进行意图分类（结构化 JSON 输出）"""
        prompt = _build_classification_prompt(query)

        # 使用 LLMClient 的 chat_json 方法，自动处理 JSON 解析
        try:
            result = self.llm.chat_json(
                prompt=prompt,
                temperature=0.1,
                max_tokens=1024,
            )
            if result and "primary_intent" in result:
                return result
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        return None

    def _parse_llm_result(self, query: str, result: dict) -> RoutingDecision:
        """解析 LLM 分类结果"""
        primary = result.get("primary_intent", "unknown")
        confidence = result.get("confidence", 0.5)
        entities = result.get("entities", {})
        is_composite = result.get("is_composite", False)
        sub_queries = result.get("sub_queries", [])

        # 标准化实体
        normalized_entities = self._normalize_entities(entities, query)

        if is_composite and sub_queries:
            # 复合意图：拆解为多个子意图
            sub_intents = []
            for sq in sub_queries:
                sub_intent = Intent(
                    intent_type=IntentType(sq.get("intent", "unknown")),
                    confidence=confidence * 0.9,  # 复合意图子任务置信度降低
                    entities=self._normalize_entities(sq.get("entities", {}), sq.get("query", "")),
                    sub_intents=[],
                    raw_query=sq.get("query", "")
                )
                sub_intents.append(sub_intent)

            return RoutingDecision(
                intents=[Intent(
                    intent_type=IntentType.COMPOSITE,
                    confidence=confidence,
                    entities=normalized_entities,
                    sub_intents=sub_intents,
                    raw_query=query
                )],
                strategy="composite",
                message=f"检测到复合意图，将拆分为 {len(sub_intents)} 个子任务处理。"
            )

        # 单一意图
        intent = Intent(
            intent_type=IntentType(primary) if primary in [i.value for i in IntentType] else IntentType.UNKNOWN,
            confidence=confidence,
            entities=normalized_entities,
            sub_intents=[],
            raw_query=query
        )

        if intent.intent_type == IntentType.CLARIFY or confidence < 0.5:
            return RoutingDecision(
                intents=[intent],
                strategy="clarify",
                message=self._generate_clarification(query, "意图不够明确")
            )

        return RoutingDecision(
            intents=[intent],
            strategy="direct"
        )

    def _keyword_fallback(self, query: str) -> RoutingDecision:
        """关键词回退模式"""
        query_lower = query.lower()
        scores = {}

        for intent_type, patterns in self.KEYWORD_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, query_lower, re.IGNORECASE)
                score += len(matches)
            if score > 0:
                scores[intent_type] = score

        if not scores:
            # 尝试提取实体（RefDes/Net/MPN）
            entities = self._extract_entities(query)
            if entities.get("refdes"):
                return RoutingDecision(
                    intents=[Intent(
                        intent_type=IntentType.COMPONENT_LOOKUP,
                        confidence=0.5,
                        entities=entities,
                        sub_intents=[],
                        raw_query=query
                    )],
                    strategy="direct"
                )
            return RoutingDecision(
                intents=[Intent(
                    intent_type=IntentType.CLARIFY,
                    confidence=0.3,
                    entities=entities,
                    sub_intents=[],
                    raw_query=query
                )],
                strategy="clarify",
                message="抱歉，我不太理解您的请求。请尝试描述：\n1. 要查询的器件位号（如 U1）\n2. 要检查的网络名（如 I2C_SDA）\n3. 或具体的问题类型（如电源分析、引脚检查）"
            )

        # 选择得分最高的意图
        best_intent = max(scores, key=scores.get)
        confidence = min(0.7, 0.4 + scores[best_intent] * 0.15)

        entities = self._extract_entities(query)

        return RoutingDecision(
            intents=[Intent(
                intent_type=best_intent,
                confidence=confidence,
                entities=entities,
                sub_intents=[],
                raw_query=query
            )],
            strategy="direct"
        )

    def _normalize_entities(self, entities: dict, query: str) -> dict:
        """标准化实体"""
        result = {}

        # RefDes 列表
        refdes = entities.get("refdes", [])
        if isinstance(refdes, str):
            refdes = [refdes]
        # 如果 LLM 没提取到，尝试正则提取
        if not refdes:
            refdes = re.findall(r'\b([URCLQFJ]\d+[A-Z0-9_]*)\b', query.upper())
        result["refdes"] = list(set(refdes))

        # Net 名
        net_name = entities.get("net_name", "")
        if not net_name:
            # 尝试提取大写的网络名
            nets = re.findall(r'\b([A-Z][A-Z0-9_]+)\b', query)
            # 过滤掉常见非网络词
            exclude = {"I2C", "SPI", "UART", "USB", "GPIO", "VDD", "VCC", "GND", "PCIE", "RGMII", "DDR"}
            # 保留包含这些关键词的或全大写的
            net_candidates = [n for n in nets if any(kw in n for kw in ["I2C", "SPI", "UART", "USB", "DDR", "RGMII", "PCIE", "CLK", "RST", "INT"])]
            if net_candidates:
                result["net_name"] = net_candidates[0]
        else:
            result["net_name"] = net_name

        # MPN
        mpn = entities.get("mpn", "")
        if not mpn:
            # 尝试提取型号（大写字母+数字组合）
            mpns = re.findall(r'\b([A-Z]+\d+[A-Z0-9-]*)\b', query)
            if mpns:
                result["mpn"] = mpns[0]
        else:
            result["mpn"] = mpn

        # 规则类型
        rule_type = entities.get("rule_type", "")
        if rule_type:
            result["rule_type"] = rule_type

        return result

    def _extract_entities(self, query: str) -> dict:
        """从查询中提取实体"""
        return self._normalize_entities({}, query)

    def _generate_clarification(self, query: str, issue: str) -> str:
        """生成澄清问题"""
        # 简单规则生成，不调用 LLM 以节省资源
        entities = self._extract_entities(query)
        hints = []

        if not entities.get("refdes"):
            hints.append("请指定器件位号（如 U1、R5）")
        if not entities.get("net_name"):
            hints.append("或网络名（如 I2C_SDA、VDD_1V8）")

        if hints:
            return f"请求不够明确。{'; '.join(hints)}。您想查询什么？"
        return "请求不够明确，请提供更多细节。"


# ============================================================
# LangChain Tool 封装
# ============================================================

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        return fn


@tool
def analyze_user_intent(query: str) -> str:
    """
    分析用户查询的意图。

    返回意图分类结果和提取的实体，用于 Agent 路由决策。

    Args:
        query: 用户查询文本

    Returns:
        JSON 格式的意图分析结果
    """
    router = LLMIntentRouter()
    decision = router.route(query)

    intent = decision.intents[0]
    result = {
        "strategy": decision.strategy,
        "primary_intent": intent.intent_type.value,
        "confidence": intent.confidence,
        "entities": intent.entities,
        "message": decision.message,
    }

    if intent.sub_intents:
        result["sub_intents"] = [
            {
                "intent": si.intent_type.value,
                "entities": si.entities,
                "query": si.raw_query
            }
            for si in intent.sub_intents
        ]

    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("LLM Intent Router Self-test")
    print("=" * 60)

    router = LLMIntentRouter()

    test_queries = [
        ("U50001 是什么器件？", IntentType.COMPONENT_LOOKUP),
        ("追踪 I2C_SDA 网络", IntentType.NET_TRACE),
        ("检查 U1 的电源树", IntentType.POWER_ANALYSIS),
        ("TPS5430 的电压规格是多少？", IntentType.SPEC_SEARCH),
        ("检查 U1 的电源网络和上拉电阻", IntentType.COMPOSITE),
        ("这个设计有问题吗？", IntentType.CLARIFY),
    ]

    for query, expected in test_queries:
        print(f"\nQuery: '{query}'")
        decision = router.route(query)
        intent = decision.intents[0]
        status = "✅" if intent.intent_type == expected else "⚠️"
        print(f"  {status} Intent: {intent.intent_type.value} (conf={intent.confidence:.2f})")
        print(f"     Entities: {intent.entities}")
        print(f"     Strategy: {decision.strategy}")
        if decision.message:
            print(f"     Message: {decision.message}")

    print("\n✅ LLM Intent Router test completed")


if __name__ == "__main__":
    _run_tests()
