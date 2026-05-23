"""
LLM Client JSON 解析单元测试
- 括号平衡提取
- thinking 残留清洗
- 截断 JSON 修复
- markdown 代码块提取
"""

import sys
import os
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from agent_system.llm_client import LLMClient


class TestExtractJson:
    """LLMClient._extract_json 单元测试"""

    # --- 正常 JSON ---

    def test_plain_json(self):
        text = '{"action": "test", "value": 42}'
        r = LLMClient._extract_json(text)
        assert r == {"action": "test", "value": 42}

    def test_nested_json(self):
        text = '{"action": "test", "data": {"key": "val"}, "is_final": false}'
        r = LLMClient._extract_json(text)
        assert r["data"]["key"] == "val"

    # --- Markdown 代码块 ---

    def test_json_code_block(self):
        text = '```json\n{"action": "test", "value": 1}\n```'
        r = LLMClient._extract_json(text)
        assert r == {"action": "test", "value": 1}

    def test_plain_code_block(self):
        text = '```\n{"action": "test"}\n```'
        r = LLMClient._extract_json(text)
        assert r == {"action": "test"}

    # --- Thinking 残留 ---

    def test_thinking_prefix(self):
        text = 'Let me analyze... {"action": "analyze_power_sequence", "action_input": {"component": "U60140"}, "is_final": false}'
        r = LLMClient._extract_json(text)
        assert r["action"] == "analyze_power_sequence"

    # --- Gemma 标签 ---

    def test_gemma_tags(self):
        text = '<|start_of_turn|>model\n{"action": "final_answer", "final_answer": "test", "is_final": true}<|end_of_turn|>'
        r = LLMClient._extract_json(text)
        assert r["action"] == "final_answer"

    # --- 截断 JSON ---

    def test_truncated_json(self):
        text = '{"action": "analyze_power_sequence", "action_input": {"component": "U60140"'
        r = LLMClient._extract_json(text)
        assert r is not None
        assert r["action"] == "analyze_power_sequence"

    # --- 嵌套括号在值中 ---

    def test_braces_in_value(self):
        text = 'Here: {"action": "final_answer", "final_answer": "结果含{括号}", "is_final": true} end'
        r = LLMClient._extract_json(text)
        assert r["final_answer"] == "结果含{括号}"

    # --- 边界情况 ---

    def test_empty_input(self):
        assert LLMClient._extract_json("") is None
        assert LLMClient._extract_json(None) is None

    def test_no_json(self):
        assert LLMClient._extract_json("Hello world, no JSON here") is None

    def test_multiple_json_objects(self):
        # 应提取第一个完整 JSON
        text = '{"action": "first"} and {"action": "second"}'
        r = LLMClient._extract_json(text)
        assert r["action"] == "first"

    def test_escaped_quotes(self):
        text = '{"action": "test", "value": "hello \\"world\\""}'
        r = LLMClient._extract_json(text)
        assert r["value"] == 'hello "world"'

    def test_unicode_content(self):
        text = '{"action": "final_answer", "final_answer": "电压值为3.3V，未超过额定值"}'
        r = LLMClient._extract_json(text)
        assert "3.3V" in r["final_answer"]

    def test_array_value(self):
        text = '{"action": "test", "items": [1, 2, 3]}'
        r = LLMClient._extract_json(text)
        assert r["items"] == [1, 2, 3]
