"""
集成测试 — 端到端链路验证

测试范围：
a. ETL→Neo4j 链路
b. 审查引擎链路
c. ReAct Agent 工具链路
d. KnowledgeRouter 链路

所有测试使用 mock 替代真实 Neo4j/Ollama/ChromaDB 连接。
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# ============================================================
# a. ETL → Neo4j 链路
# ============================================================

class TestETLNeo4jPipeline:
    """ETL 解析 → Cypher 生成链路测试"""

    def test_net_parser_output_format(self):
        """验证 pstxnet parser 输出三元组格式正确"""
        from etl_pipeline.net_parser import CadenceNetlistParser

        mock_data = """
NET_NAME
'VDD_1V8'
 some_path:
 C_SIGNAL='sig';
NODE_NAME\tU30004 C4
 path:
 'W#/DQ2':;
NODE_NAME\tR30001 1
 path:
 '1':;
NET_NAME
'GND'
 another_path:
 C_SIGNAL='sig2';
NODE_NAME\tU30004 A1
 path:
 'VSS':;
"""
        parser = CadenceNetlistParser()
        result = parser.parse_pstxnet(mock_data)

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]['Net_Name'] == 'VDD_1V8'
        assert result[0]['Component_RefDes'] == 'U30004'
        assert result[0]['Pin_Number'] == 'C4'
        assert result[1]['Net_Name'] == 'VDD_1V8'
        assert result[1]['Component_RefDes'] == 'R30001'
        assert result[2]['Net_Name'] == 'GND'

    def test_net_parser_empty_input(self):
        """空输入返回空列表"""
        from etl_pipeline.net_parser import CadenceNetlistParser

        parser = CadenceNetlistParser()
        result = parser.parse_pstxnet("")
        assert result == []

    def test_topology_triplet_cypher_generation(self):
        """验证 TopologyTriplet 生成正确的 Cypher 语句"""
        from agent_system.schemas.graph import TopologyTriplet

        triplet = TopologyTriplet(
            net_name="VDD_1V8",
            component_refdes="U30004",
            pin_number="C4",
            pin_type="POWER",
            voltage_level="1.8V",
        )
        cypher, params = triplet.to_cypher()

        assert "MERGE" in cypher
        assert "Component" in cypher
        assert "Pin" in cypher
        assert "Net" in cypher
        assert "HAS_PIN" in cypher
        assert "CONNECTS_TO" in cypher
        assert params["refdes"] == "U30004"
        assert params["pin_number"] == "C4"
        assert params["net_name"] == "VDD_1V8"
        assert params["voltage_level"] == "1.8V"

    def test_component_node_cypher_properties(self):
        """验证 ComponentNode 属性映射正确"""
        from agent_system.schemas.graph import ComponentNode

        comp = ComponentNode(
            refdes="U30004",
            model="MT25QL02GCBB8E12_TPBGA24",
            value="N/A",
            part_type="IC",
            mpn="MT25QU256ABA8E12",
        )
        props = comp.to_cypher_properties()
        assert props["RefDes"] == "U30004"
        assert props["Model"] == "MT25QL02GCBB8E12_TPBGA24"
        assert props["PartType"] == "IC"
        assert props["MPN"] == "MT25QU256ABA8E12"

    def test_net_node_cypher_properties(self):
        """验证 NetNode 属性映射正确"""
        from agent_system.schemas.graph import NetNode

        net = NetNode(name="VDD_1V8", voltage_level="1.8V", net_type="POWER")
        props = net.to_cypher_properties()
        assert props["Name"] == "VDD_1V8"
        assert props["VoltageLevel"] == "1.8V"
        assert props["NetType"] == "POWER"

    def test_pin_node_id_generation(self):
        """验证 PinNode 全局 ID 生成规则"""
        from agent_system.schemas.graph import PinNode

        pin = PinNode(number="C4", component_refdes="U30004", pin_type="POWER")
        assert pin.pin_id == "U30004_C4"
        props = pin.to_cypher_properties()
        assert props["Id"] == "U30004_C4"
        assert props["Number"] == "C4"
        assert props["Type"] == "POWER"


# ============================================================
# b. 审查引擎链路
# ============================================================

class TestReviewEnginePipeline:
    """审查引擎集成测试（mock Neo4j driver）"""

    def _make_mock_driver(self, query_results=None):
        """构造 mock Neo4j driver"""
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        if query_results:
            session.run.return_value = iter(query_results)
        else:
            session.run.return_value = iter([])

        return driver

    def test_engine_run_rules_no_violations(self):
        """无规则配置时引擎返回空违规列表"""
        from agent_system.review_engine.engine import ReviewRuleEngine

        driver = self._make_mock_driver()
        engine = ReviewRuleEngine(driver, config_path=None)

        # 没有加载任何规则，应为空
        violations = engine.run_rules()
        assert isinstance(violations, list)
        assert len(violations) == 0

    def test_engine_add_rule_and_execute(self):
        """动态添加规则并执行，验证违规输出"""
        from agent_system.review_engine.engine import ReviewRuleEngine
        from agent_system.schemas import RuleConfig, Violation
        from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry

        # 注册一个测试模板
        class DummyTemplate(RuleTemplate):
            template_id = "test_dummy"
            name = "Dummy Test"
            description = "Test template that always violates"

            def check(self, params, context):
                return [Violation(
                    id="v1",
                    rule_id=params.get("rule_id", "test_rule"),
                    rule_name=params.get("rule_name", "Dummy"),
                    refdes="U99999",
                    description="Test violation",
                    severity="WARNING",
                    expected="OK",
                    actual="FAIL",
                )]

        # 注册模板
        TemplateRegistry.register(DummyTemplate())

        driver = self._make_mock_driver()
        engine = ReviewRuleEngine(driver, config_path=None)

        rule = RuleConfig(
            id="test_rule_001",
            template_id="test_dummy",
            name="Test Rule",
            severity="WARNING",
            params={},
        )
        engine.add_rule(rule)

        violations = engine.run_rules()
        assert len(violations) == 1
        assert violations[0].refdes == "U99999"
        assert violations[0].rule_id == "test_rule_001"

        # 清理注册
        TemplateRegistry.clear()

    def test_whitelist_filter_violations(self):
        """白名单过滤机制：白名单中的违规被过滤"""
        from agent_system.review_engine.whitelist import WhitelistManager
        from agent_system.schemas import Violation, WhitelistEntry

        driver = self._make_mock_driver()
        wl = WhitelistManager(driver)
        # 手动添加白名单缓存（跳过 Neo4j 查询）
        wl._cache[("rule_A", "U1")] = WhitelistEntry(
            rule_id="rule_A", refdes="U1", status="IGNORE", reason="test"
        )
        wl._loaded = True

        violations = [
            Violation(id="v1", rule_id="rule_A", rule_name="R", refdes="U1", description="bad"),
            Violation(id="v2", rule_id="rule_B", rule_name="R", refdes="U2", description="bad"),
        ]
        filtered = wl.filter_violations(violations)
        assert len(filtered) == 1
        assert filtered[0].refdes == "U2"

    def test_generate_report_markdown(self):
        """验证报告生成输出 Markdown 格式"""
        from agent_system.review_engine.engine import ReviewRuleEngine
        from agent_system.schemas import Violation

        driver = self._make_mock_driver()
        engine = ReviewRuleEngine(driver, config_path=None)

        violations = [
            Violation(id="v1", rule_id="decap_001", rule_name="Decap Check",
                      refdes="U1", description="Missing decap", severity="ERROR"),
            Violation(id="v2", rule_id="pullup_001", rule_name="Pullup Check",
                      refdes="R1", description="Wrong pullup", severity="WARNING",
                      net_name="I2C_SDA"),
        ]
        report = engine.generate_report(violations)
        assert "# 原理图审查报告" in report
        assert "ERROR" in report
        assert "WARNING" in report
        assert "U1" in report
        assert "I2C_SDA" in report

    def test_get_summary_statistics(self):
        """验证摘要统计正确性"""
        from agent_system.review_engine.engine import ReviewRuleEngine
        from agent_system.schemas import Violation

        driver = self._make_mock_driver()
        engine = ReviewRuleEngine(driver, config_path=None)

        violations = [
            Violation(id="v1", rule_id="r1", rule_name="R", refdes="U1", description="", severity="ERROR"),
            Violation(id="v2", rule_id="r1", rule_name="R", refdes="U2", description="", severity="WARNING"),
            Violation(id="v3", rule_id="r2", rule_name="R", refdes="U3", description="", severity="INFO"),
        ]
        summary = engine.get_summary(violations)
        assert summary["total"] == 3
        assert summary["errors"] == 1
        assert summary["warnings"] == 1
        assert summary["infos"] == 1
        assert summary["by_rule"]["r1"] == 2
        assert summary["by_rule"]["r2"] == 1


# ============================================================
# c. ReAct Agent 工具链路
# ============================================================

class TestAgentToolsPipeline:
    """Graph Tools 与 Agent 工具集成测试"""

    def test_get_graph_tools_returns_all_tools(self):
        """验证 get_graph_tools() 返回所有工具"""
        from agent_system.graph_tools import get_graph_tools

        tools = get_graph_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 14  # 至少 14 个工具（持续增长）

        tool_names = set()
        for t in tools:
            tool_names.add(getattr(t, 'name', None) or getattr(t, '__name__', None))

        # 必须包含的核心工具
        expected = {
            "get_component_nets", "get_net_components", "get_power_domain",
            "get_power_tree", "get_i2c_devices", "get_signal_path",
            "find_common_cause", "analyze_power_sequence",
            "trace_signal_path", "trace_power_chain", "trace_fault_root",
            "trace_differential_pair", "get_graph_summary",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"

    def test_tool_args_schema_complete(self):
        """验证每个工具的参数 schema 完整"""
        from agent_system.graph_tools import get_graph_tools

        tools = get_graph_tools()
        for t in tools:
            name = getattr(t, 'name', None) or getattr(t, '__name__', str(t))
            # @tool 装饰的有 args_schema；普通函数没有
            if hasattr(t, 'args_schema'):
                schema = t.args_schema
                assert schema is not None, f"Tool {name} missing args_schema"
                # Pydantic v1 兼容
                fields = getattr(schema, 'model_fields', None) or getattr(schema, '__fields__', None)
                assert fields is not None, f"Tool {name} schema has no fields"

    def test_tool_has_description(self):
        """验证每个工具有描述信息"""
        from agent_system.graph_tools import get_graph_tools

        tools = get_graph_tools()
        for t in tools:
            name = getattr(t, 'name', None) or getattr(t, '__name__', str(t))
            desc = getattr(t, 'description', None) or getattr(t, '__doc__', None)
            assert desc, f"Tool {name} missing description"

    def test_mock_tool_call_get_component_nets(self):
        """mock 调用 get_component_nets 验证返回格式"""
        from agent_system.graph_tools import get_component_nets

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.return_value = [
                {"pin_number": "C4", "pin_type": "POWER", "net_name": "VDD_1V8", "voltage_level": "1.8V"},
                {"pin_number": "A1", "pin_type": "GND", "net_name": "GND", "voltage_level": None},
            ]
            result = get_component_nets.invoke({"refdes": "U30004"})
            assert "U30004" in result
            assert "VDD_1V8" in result
            assert "GND" in result

    def test_mock_tool_call_get_component_nets_not_found(self):
        """mock 调用返回空结果时给出提示"""
        from agent_system.graph_tools import get_component_nets

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.return_value = []
            result = get_component_nets.invoke({"refdes": "UXXXXX"})
            assert "未找到" in result

    def test_mock_tool_call_get_net_components_detailed(self):
        """mock 调用小网络返回详细列表"""
        from agent_system.graph_tools import get_net_components

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            # 第一次调用：计数
            # 第二次调用：详细数据
            mock_run.side_effect = [
                [{"total_components": 3, "total_pins": 5}],
                [
                    {"refdes": "U1", "part_type": "IC", "value": "N/A", "pin_number": "1", "pin_type": "POWER"},
                    {"refdes": "R1", "part_type": "RES", "value": "10K", "pin_number": "2", "pin_type": "PASSIVE"},
                    {"refdes": "C1", "part_type": "CAP", "value": "100nF", "pin_number": "1", "pin_type": "PASSIVE"},
                ],
            ]
            result = get_net_components.invoke({"net_name": "VDD_1V8"})
            assert "VDD_1V8" in result
            assert "3 个器件" in result

    def test_mock_tool_call_get_graph_summary(self):
        """mock 调用图谱摘要工具"""
        from agent_system.graph_tools import get_graph_summary

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.side_effect = [
                [{"cnt": 500}],   # total_nodes
                [{"cnt": 200}],   # comp_count
                [{"cnt": 150}],   # net_count
                [{"cnt": 150}],   # pin_count
                [{"part_type": "IC", "cnt": 50}, {"part_type": "RES", "cnt": 100}],
            ]
            result = get_graph_summary.invoke({})
            assert "500" in result
            assert "IC" in result


# ============================================================
# d. KnowledgeRouter 链路
# ============================================================

class TestKnowledgeRouterPipeline:
    """KnowledgeRouter 三级降级路由集成测试"""

    def test_tier1_hit_returns_success(self):
        """Tier0 未命中，Tier1 命中时返回成功结果"""
        from agent_system.knowledge_router import KnowledgeRouter, RetrievalResult, TierLevel

        router = KnowledgeRouter()
        # mock tier0 (GraphRAG) 未命中
        router._graphrag = MagicMock()
        router.graphrag.query = MagicMock(return_value=[])
        # mock tier1 search
        router.tier1.search = MagicMock(return_value=[
            RetrievalResult(
                status="success",
                tier=TierLevel.TIER_1,
                content="MT25QU256 pin C4 is VCC 1.8V",
                source="local:general",
                confidence=0.85,
                mpn="MT25QU256ABA8E12",
            )
        ])

        result = router.search("MT25QU256ABA8E12", "pinout voltage")
        assert result.status == "success"
        assert result.confidence >= 0.3

    def test_tier1_miss_tier2_hit(self):
        """Tier0/1 未命中，Tier2 命中时降级并缓存"""
        from agent_system.knowledge_router import KnowledgeRouter, RetrievalResult, TierLevel

        router = KnowledgeRouter()
        router._graphrag = MagicMock()
        router.graphrag.query = MagicMock(return_value=[])
        router.tier1.search = MagicMock(return_value=[])
        router.tier2.search = MagicMock(return_value=RetrievalResult(
            status="success",
            tier=TierLevel.TIER_2,
            content="ChromaDB knowledge result",
            source="chromadb",
            confidence=0.7,
            mpn="MPN123",
        ))
        router.tier1.add_chunk = MagicMock(return_value=True)

        result = router.search("MPN123", "spec")
        assert result.status == "success"
        # 应该缓存到 tier1
        router.tier1.add_chunk.assert_called_once()

    def test_tier1_tier2_miss_not_found(self):
        """Tier0/1/2 都未命中，Tier3 禁用或未命中，返回 not_found"""
        from agent_system.knowledge_router import KnowledgeRouter

        router = KnowledgeRouter()
        router._graphrag = MagicMock()
        router.graphrag.query = MagicMock(return_value=[])
        router.tier1.search = MagicMock(return_value=[])
        router.tier2.search = MagicMock(return_value=None)
        router.tier3 = MagicMock()
        router.tier3.search = MagicMock(return_value=None)

        result = router.search("UNKNOWN_MPN", "voltage")
        assert result.status == "not_found"
        assert "UNKNOWN_MPN" in result.content

    def test_tier0_hit_skips_lower_tiers(self):
        """Tier0 GraphRAG 命中时跳过 Tier1/2"""
        from agent_system.knowledge_router import KnowledgeRouter
        from agent_system.graph_rag_bridge import GraphRAGResult

        router = KnowledgeRouter()
        # mock GraphRAG 返回高分结果
        mock_result = MagicMock()
        mock_result.score = 0.85
        mock_result.text = "TPS7A47 output voltage is 1A LDO"
        mock_result.retrieval_type = "local"
        router._graphrag = MagicMock()
        router.graphrag.query = MagicMock(return_value=[mock_result])

        result = router.search("TPS7A47", "output voltage")
        assert result.status == "success"
        assert result.tier == "Tier0"
        assert result.confidence >= 0.3

    def test_tier1_low_confidence_fallback(self):
        """Tier0 未命中，Tier1 置信度低于阈值时降级到 Tier2"""
        from agent_system.knowledge_router import KnowledgeRouter, RetrievalResult, TierLevel

        router = KnowledgeRouter()
        router._graphrag = MagicMock()
        router.graphrag.query = MagicMock(return_value=[])
        # Tier1 有结果但置信度太低
        router.tier1.search = MagicMock(return_value=[
            RetrievalResult(
                status="success",
                tier=TierLevel.TIER_1,
                content="low quality match",
                source="local",
                confidence=0.1,  # 低于 0.3 阈值
                mpn="MPN456",
            )
        ])
        router.tier2.search = MagicMock(return_value=RetrievalResult(
            status="success",
            tier=TierLevel.TIER_2,
            content="Better result from Tier2",
            source="chromadb",
            confidence=0.8,
            mpn="MPN456",
        ))
        router.tier1.add_chunk = MagicMock(return_value=True)

        result = router.search("MPN456", "specs")
        assert result.status == "success"
        assert result.confidence == 0.8

    def test_import_text_knowledge_and_search(self):
        """验证导入文本知识后可被搜索到（mock embedding）"""
        from agent_system.knowledge_router import KnowledgeRouter

        router = KnowledgeRouter()
        # mock embed 函数和 collection
        router.tier1._col = MagicMock()
        router.tier1._col.add = MagicMock(return_value=None)
        router.tier1._col.count = MagicMock(return_value=3)

        with patch("agent_system.knowledge_router.embed", return_value=[0.0] * 768):
            imported = router.import_text_knowledge("MPN_TEST", {
                "1": "Test datasheet page 1 content",
                "2": "Test datasheet page 2 content",
                "3": "Test datasheet page 3 content",
            })
            assert imported == 3

    def test_get_stats(self):
        """验证统计信息返回正确"""
        from agent_system.knowledge_router import KnowledgeRouter

        router = KnowledgeRouter()
        router.tier1.count = MagicMock(return_value=42)

        stats = router.get_stats()
        assert stats["tier1_chunks"] == 42
        assert stats["tier2_enabled"] is True
        # tier3_enabled 取决于环境变量，不强断言 False
        assert isinstance(stats["tier3_enabled"], bool)


# ============================================================
# e. 新增工具链路测试
# ============================================================

class TestNewToolsPipeline:
    """trace_power_chain / trace_fault_root 集成测试"""

    def test_trace_power_chain_downstream(self):
        """mock 调用 trace_power_chain 下游追踪"""
        from agent_system.graph_tools import trace_power_chain

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.side_effect = [
                # info query
                [{"rd": "U1", "pt": "PMIC", "model": "TPS65987"}],
                # downstream query (2 children)
                [
                    {"rd": "L1", "pt": "LDO", "model": "TLV733", "voltage": "3.3"},
                    {"rd": "U2", "pt": "BUCK", "model": "TPS63070", "voltage": "1.8"},
                ],
                # L1's downstream (1 child)
                [{"rd": "U3", "pt": "IC", "model": "MCU", "voltage": "3.3"}],
                # U2's downstream (empty)
                [],
                # U3's downstream (empty)
                [],
            ]
            result = trace_power_chain.invoke({"refdes": "U1", "direction": "downstream"})
            assert "U1" in result
            assert "L1" in result
            assert "下游" in result

    def test_trace_fault_root_with_upstream(self):
        """mock 调用 trace_fault_root 有上游供电"""
        from agent_system.graph_tools import trace_fault_root

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.side_effect = [
                # info query
                [{"rd": "L1", "pt": "LDO", "model": "TLV733", "value": "3.3V"}],
                # upstream query
                [{"rd": "U1", "pt": "PMIC", "model": "TPS65987", "voltage": "3.3"}],
                # up2 query
                [{"rd": "U0", "pt": "DCDC", "voltage": "12.0"}],
                # EN nets query
                [],
                # VIN nets query
                [],
                # common cause query
                [],
            ]
            result = trace_fault_root.invoke({"refdes": "L1", "symptom": "无输出"})
            assert "L1" in result
            assert "根因排查" in result
            assert "U1" in result

    def test_trace_fault_root_not_found(self):
        """器件不存在时返回提示"""
        from agent_system.graph_tools import trace_fault_root

        with patch("agent_system.graph_tools._run_cypher") as mock_run:
            mock_run.return_value = []
            result = trace_fault_root.invoke({"refdes": "UXXXXX", "symptom": "不工作"})
            assert "未找到" in result
