"""
Graph Tools 单元测试（用 mock 替代 Neo4j 连接）
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_system.graph_tools import (
    get_component_nets,
    get_net_components,
    get_power_domain,
    get_power_tree,
    get_i2c_devices,
    get_signal_path,
    find_common_cause,
    analyze_power_sequence,
    trace_signal_path,
    trace_differential_pair,
    get_graph_summary,
    get_graph_tools,
    DEFAULT_AGGREGATION_THRESHOLD,
)


# ============================================================
# 工具集完整性测试
# ============================================================

class TestToolRegistry:
    def test_get_graph_tools_returns_list(self):
        tools = get_graph_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 9

    def test_tool_names(self):
        # Only StructuredTool has .name; trace_differential_pair is plain function
        tools = [t for t in get_graph_tools() if hasattr(t, 'name')]
        names = {t.name for t in tools}
        expected = {
            "get_component_nets", "get_net_components", "get_power_domain",
            "get_power_tree", "get_i2c_devices", "get_signal_path",
            "find_common_cause", "analyze_power_sequence", "get_graph_summary",
        }
        assert expected.issubset(names)

    def test_default_aggregation_threshold(self):
        assert DEFAULT_AGGREGATION_THRESHOLD == 100


# ============================================================
# 工具参数 Schema 测试
# ============================================================

class TestToolSchemas:
    def test_get_component_nets_args(self):
        schema = get_component_nets.args_schema
        assert "refdes" in schema.__fields__

    def test_get_net_components_args(self):
        schema = get_net_components.args_schema
        assert "net_name" in schema.__fields__
        assert "threshold" in schema.__fields__

    def test_get_power_domain_args(self):
        schema = get_power_domain.args_schema
        assert "voltage_level" in schema.__fields__
        assert "detail" in schema.__fields__

    def test_get_signal_path_args(self):
        schema = get_signal_path.args_schema
        assert "from_refdes" in schema.__fields__
        assert "to_refdes" in schema.__fields__

    def test_trace_signal_path_args(self):
        schema = trace_signal_path.args_schema
        assert "start_pin" in schema.__fields__
        assert "max_depth" in schema.__fields__

    def test_find_common_cause_args(self):
        schema = find_common_cause.args_schema
        assert "refdes_list" in schema.__fields__

    def test_analyze_power_sequence_args(self):
        schema = analyze_power_sequence.args_schema
        assert "refdes" in schema.__fields__

    def test_get_power_tree_args(self):
        schema = get_power_tree.args_schema
        assert "root_refdes" in schema.__fields__
        assert "voltage" in schema.__fields__


# ============================================================
# 工具描述测试
# ============================================================

class TestToolDescriptions:
    def test_structured_tools_have_description(self):
        for tool in get_graph_tools():
            if not hasattr(tool, 'name'):
                continue
            assert tool.description, f"{tool.name} missing description"

    def test_structured_tools_have_name(self):
        for tool in get_graph_tools():
            if not hasattr(tool, 'name'):
                continue
            assert tool.name, "Tool missing name"


# ============================================================
# get_component_nets 测试
# ============================================================

class TestGetComponentNets:
    @patch("agent_system.graph_tools._run_cypher")
    def test_found_component(self, mock_run):
        mock_run.return_value = [
            {"pin_number": "1", "pin_type": "POWER", "net_name": "VCC_3V3", "voltage_level": "3.3", "net_type": "POWER"},
            {"pin_number": "2", "pin_type": "IO", "net_name": "SDA", "voltage_level": None, "net_type": "SIGNAL"},
        ]
        result = get_component_nets.invoke({"refdes": "U1"})
        assert "U1" in result
        assert "VCC_3V3" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_not_found(self, mock_run):
        mock_run.return_value = []
        result = get_component_nets.invoke({"refdes": "U9999"})
        assert "未找到" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_error_handling(self, mock_run):
        mock_run.side_effect = Exception("connection error")
        result = get_component_nets.invoke({"refdes": "U1"})
        assert "Error" in result


# ============================================================
# get_net_components 测试
# ============================================================

class TestGetNetComponents:
    @patch("agent_system.graph_tools._run_cypher")
    def test_small_net(self, mock_run):
        """小网络返回详细列表"""
        mock_run.side_effect = [
            [{"total_components": 3, "total_pins": 5}],
            [
                {"refdes": "U1", "part_type": "IC", "value": "MCU", "pin_number": "1", "pin_type": "POWER"},
                {"refdes": "C1", "part_type": "CAP", "value": "0.1uF", "pin_number": "1", "pin_type": "PASSIVE"},
            ],
        ]
        result = get_net_components.invoke({"net_name": "VCC_3V3"})
        assert "U1" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_not_found(self, mock_run):
        mock_run.return_value = [{"total_components": 0, "total_pins": 0}]
        result = get_net_components.invoke({"net_name": "NONEXIST"})
        assert "未找到" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_large_net_aggregation(self, mock_run):
        """大网络启用聚合模式"""
        mock_run.side_effect = [
            [{"total_components": 200, "total_pins": 300}],
            [
                {"part_type": "CAP", "component_count": 150, "pin_count": 200, "examples": ["C1", "C2", "C3", "C4", "C5"]},
                {"part_type": "IC", "component_count": 50, "pin_count": 100, "examples": ["U1", "U2"]},
            ],
        ]
        result = get_net_components.invoke({"net_name": "GND", "threshold": 100})
        assert "聚合" in result


# ============================================================
# get_power_domain 测试
# ============================================================

class TestGetPowerDomain:
    @patch("agent_system.graph_tools._run_cypher")
    def test_overview(self, mock_run):
        mock_run.return_value = [
            {"voltage": "1V8", "nets": ["VDD_1V8"], "component_count": 20},
        ]
        result = get_power_domain.invoke({})
        assert "1V8" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_not_found(self, mock_run):
        mock_run.return_value = []
        result = get_power_domain.invoke({"voltage_level": "99V"})
        assert "未找到" in result


# ============================================================
# trace_differential_pair 测试（预留接口）
# ============================================================

class TestDifferentialPair:
    def test_returns_placeholder(self):
        result = trace_differential_pair("U1_A4")
        assert "预留接口" in result
        assert "Phase 3" in result


# ============================================================
# get_graph_summary 测试
# ============================================================

class TestGetGraphSummary:
    @patch("agent_system.graph_tools._run_cypher")
    def test_summary(self, mock_run):
        mock_run.side_effect = [
            [{"cnt": 100}],
            [{"cnt": 30}],
            [{"cnt": 40}],
            [{"cnt": 30}],
            [{"part_type": "IC", "cnt": 20}, {"part_type": "CAP", "cnt": 10}],
        ]
        result = get_graph_summary.invoke({})
        assert "100" in result
        assert "IC" in result


# ============================================================
# find_common_cause 测试
# ============================================================

class TestFindCommonCause:
    @patch("agent_system.graph_tools._run_cypher")
    def test_too_few_refdes(self, mock_run):
        result = find_common_cause.invoke({"refdes_list": "U1"})
        assert "至少需要 2" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_no_power_info(self, mock_run):
        mock_run.return_value = []
        result = find_common_cause.invoke({"refdes_list": "U1,U2"})
        assert "未找到" in result


# ============================================================
# 错误处理测试
# ============================================================

class TestErrorHandling:
    @patch("agent_system.graph_tools._run_cypher")
    def test_get_power_domain_error(self, mock_run):
        mock_run.side_effect = Exception("Neo4j down")
        result = get_power_domain.invoke({"voltage_level": "3V3"})
        assert "Error" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_get_i2c_error(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        result = get_i2c_devices.invoke({})
        assert "Error" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_get_signal_path_error(self, mock_run):
        mock_run.side_effect = Exception("fail")
        result = get_signal_path.invoke({"from_refdes": "U1", "from_pin": "1", "to_refdes": "U2", "to_pin": "2"})
        assert "Error" in result

    @patch("agent_system.graph_tools._run_cypher")
    def test_get_graph_summary_error(self, mock_run):
        mock_run.side_effect = Exception("err")
        result = get_graph_summary.invoke({})
        assert "Error" in result