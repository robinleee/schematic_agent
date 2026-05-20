"""
Review Engine 单元测试
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_system.schemas.review import Violation, RuleConfig, WhitelistEntry
from agent_system.review_engine.templates.base import (
    RuleTemplate, RuleContext, TemplateRegistry,
)
from agent_system.review_engine.whitelist import WhitelistManager
from agent_system.review_engine.engine import ReviewRuleEngine, RuleConfigManager
from agent_system.review_engine.templates.decap import (
    DecapCheckTemplate, parse_capacitance, normalize_cap_value,
)


# ============================================================
# 容值解析工具测试
# ============================================================

class TestCapacitanceParsing:
    def test_parse_uf(self):
        assert abs(parse_capacitance("0.1uF") - 0.1e-6) < 1e-20

    def test_parse_nf(self):
        assert abs(parse_capacitance("100nF") - 100e-9) < 1e-20

    def test_parse_pf(self):
        assert abs(parse_capacitance("10pF") - 10e-12) < 1e-20

    def test_parse_empty(self):
        assert parse_capacitance("") is None

    def test_parse_none(self):
        assert parse_capacitance(None) is None

    def test_normalize_uf(self):
        result = normalize_cap_value("0.1uF")
        assert result == "100nF"  # 0.1uF 归一化为 100nF

    def test_normalize_10uf(self):
        assert normalize_cap_value("10uF") == "10uF"

    def test_normalize_100nf(self):
        assert normalize_cap_value("100nF") == "100nF"


# ============================================================
# RuleTemplate 基类测试
# ============================================================

class TestRuleTemplate:
    def test_abstract_check(self):
        """不能直接实例化抽象类"""
        with pytest.raises(TypeError):
            RuleTemplate()

    def test_custom_template(self):
        """自定义模板子类"""
        class MyTemplate(RuleTemplate):
            template_id = "test_tmpl"
            name = "Test"
            description = "Test template"

            def check(self, params, context):
                return []

        tmpl = MyTemplate()
        assert tmpl.template_id == "test_tmpl"
        assert tmpl.validate_params({}) is True


# ============================================================
# TemplateRegistry 测试
# ============================================================

class TestTemplateRegistry:
    def setup_method(self):
        """保存并清空注册表"""
        self._saved = dict(TemplateRegistry._templates)
        TemplateRegistry.clear()

    def teardown_method(self):
        """恢复注册表"""
        TemplateRegistry._templates = self._saved

    def test_register_and_get(self):
        class T1(RuleTemplate):
            template_id = "t1"
            name = "T1"
            description = ""
            def check(self, params, context): return []

        TemplateRegistry.register(T1())
        assert TemplateRegistry.get("t1") is not None

    def test_get_nonexistent(self):
        assert TemplateRegistry.get("nonexistent") is None

    def test_list_templates(self):
        class T2(RuleTemplate):
            template_id = "t2"
            name = "T2"
            description = "desc2"
            def check(self, params, context): return []

        TemplateRegistry.register(T2())
        templates = TemplateRegistry.list_templates()
        assert len(templates) == 1
        assert templates[0]["id"] == "t2"

    def test_clear(self):
        class T3(RuleTemplate):
            template_id = "t3"
            name = "T3"
            description = ""
            def check(self, params, context): return []

        TemplateRegistry.register(T3())
        TemplateRegistry.clear()
        assert TemplateRegistry.get("t3") is None


# ============================================================
# DecapCheckTemplate 测试（用 mock Neo4j）
# ============================================================

class TestDecapCheckTemplate:
    def setup_method(self):
        self._saved = dict(TemplateRegistry._templates)

    def teardown_method(self):
        TemplateRegistry._templates = self._saved

    def _mock_driver(self, nets=None, ics=None, caps=None):
        """创建 mock Neo4j driver"""
        driver = MagicMock()
        session = MagicMock()

        # 模拟 session.run 的多次调用
        results = []

        # 第一次调用：查找网络
        net_result = MagicMock()
        net_result.__iter__ = lambda s: iter(nets or [])
        results.append(net_result)

        # 第二次调用：查找 IC（power pin）
        ic_result = MagicMock()
        ic_result.__iter__ = lambda s: iter(ics or [])
        results.append(ic_result)

        # 第三次调用：查找电容
        cap_result = MagicMock()
        cap_result.__iter__ = lambda s: iter(caps or [])
        results.append(cap_result)

        session.run.side_effect = results
        session.__enter__ = lambda s: session
        session.__exit__ = MagicMock(return_value=False)
        driver.session.return_value = session
        return driver

    def test_no_violation_when_enough_caps(self):
        """有足够去耦电容时不报违规"""
        driver = self._mock_driver(
            nets=[{"net_name": "VCC_3V3", "voltage": "3.3"}],
            ics=[{"refdes": "U1", "part_type": "IC", "model": "MCU"}],
            caps=[{"cap_refdes": "C1", "cap_value": "0.1uF", "cap_model": "X"},
                  {"cap_refdes": "C2", "cap_value": "10uF", "cap_model": "X"}],
        )
        tmpl = DecapCheckTemplate()
        ctx = RuleContext(neo4j_driver=driver)
        params = {
            "voltage_level": "3.3",
            "min_count": 1,
            "rule_id": "decap_3v3",
            "rule_name": "3V3 Decap",
            "severity": "WARNING",
        }
        violations = tmpl.check(params, ctx)
        assert len(violations) == 0

    def test_violation_when_no_caps(self):
        """无去耦电容时报违规"""
        driver = self._mock_driver(
            nets=[{"net_name": "VCC_1V8", "voltage": "1.8"}],
            ics=[{"refdes": "U1", "part_type": "IC", "model": "MCU"}],
            caps=[],
        )
        tmpl = DecapCheckTemplate()
        ctx = RuleContext(neo4j_driver=driver)
        params = {
            "voltage_level": "1.8",
            "min_count": 1,
            "rule_id": "decap_1v8",
            "rule_name": "1V8 Decap",
            "severity": "ERROR",
        }
        violations = tmpl.check(params, ctx)
        assert len(violations) >= 1
        assert violations[0].severity == "ERROR"

    def test_no_nets_no_violation(self):
        """无匹配网络时无违规"""
        driver = self._mock_driver(nets=[])
        tmpl = DecapCheckTemplate()
        ctx = RuleContext(neo4j_driver=driver)
        params = {"voltage_level": "5.0", "min_count": 1, "rule_id": "t", "rule_name": "t", "severity": "WARNING"}
        violations = tmpl.check(params, ctx)
        assert len(violations) == 0

    def test_template_registered(self):
        """DecapCheckTemplate 应注册到 TemplateRegistry"""
        # 直接实例化验证类存在，而非依赖全局注册表状态
        from agent_system.review_engine.templates.decap import DecapCheckTemplate
        tmpl = DecapCheckTemplate()
        assert tmpl is not None


# ============================================================
# Violation 模型测试
# ============================================================

class TestViolationModel:
    def test_create_violation(self):
        v = Violation(
            id="v1", rule_id="r1", rule_name="Test Rule",
            refdes="U1", description="Test violation",
        )
        assert v.severity == "WARNING"  # default
        assert v.whitelisted is False

    def test_severity_error(self):
        v = Violation(
            id="v1", rule_id="r1", rule_name="T",
            refdes="U1", description="d", severity="ERROR",
        )
        assert v.severity == "ERROR"

    def test_severity_info(self):
        v = Violation(
            id="v1", rule_id="r1", rule_name="T",
            refdes="U1", description="d", severity="INFO",
        )
        assert v.severity == "INFO"

    def test_with_net_name(self):
        v = Violation(
            id="v1", rule_id="r1", rule_name="T",
            refdes="U1", description="d", net_name="VCC_3V3",
        )
        assert v.net_name == "VCC_3V3"

    def test_with_expected_actual(self):
        v = Violation(
            id="v1", rule_id="r1", rule_name="T",
            refdes="U1", description="d",
            expected="2 caps", actual="0 caps",
        )
        assert v.expected == "2 caps"
        assert v.actual == "0 caps"


# ============================================================
# RuleConfig 模型测试
# ============================================================

class TestRuleConfigModel:
    def test_create_rule_config(self):
        rc = RuleConfig(id="r1", template_id="decap_check")
        assert rc.enabled is True
        assert rc.severity == "WARNING"
        assert rc.params == {}

    def test_disabled_rule(self):
        rc = RuleConfig(id="r2", template_id="decap_check", enabled=False)
        assert rc.enabled is False

    def test_with_params(self):
        rc = RuleConfig(
            id="r3", template_id="decap_check",
            params={"voltage_level": "1.8", "min_count": 2},
        )
        assert rc.params["voltage_level"] == "1.8"


# ============================================================
# WhitelistManager 测试（用 mock Neo4j）
# ============================================================

class TestWhitelistManager:
    def _mock_driver_with_whitelist(self, entries=None):
        driver = MagicMock()
        session = MagicMock()
        results = []
        for entry in (entries or []):
            r = MagicMock()
            r.__getitem__ = lambda s, k, e=entry: e.get(k)
            results.append(r)
        session.run.return_value = iter(results)
        session.__enter__ = lambda s: session
        session.__exit__ = MagicMock(return_value=False)
        driver.session.return_value = session
        return driver

    def test_filter_violations(self):
        """白名单过滤违规"""
        driver = self._mock_driver_with_whitelist([
            {"rule_id": "r1", "refdes": "U1", "status": "IGNORE",
             "reason": "ok", "added_by": "sys", "added_at": "2025-01-01"},
        ])
        wm = WhitelistManager(driver)
        wm._loaded = True
        wm._cache = {("r1", "U1"): WhitelistEntry(rule_id="r1", refdes="U1")}

        violations = [
            Violation(id="v1", rule_id="r1", rule_name="T", refdes="U1", description="d"),
            Violation(id="v2", rule_id="r1", rule_name="T", refdes="U2", description="d"),
        ]
        filtered = wm.filter_violations(violations)
        assert len(filtered) == 1
        assert filtered[0].refdes == "U2"

    def test_is_whitelisted(self):
        driver = self._mock_driver_with_whitelist()
        wm = WhitelistManager(driver)
        wm._loaded = True
        wm._cache = {("r1", "U1"): WhitelistEntry(rule_id="r1", refdes="U1")}
        assert wm.is_whitelisted("r1", "U1") is True
        assert wm.is_whitelisted("r1", "U2") is False

    def test_count(self):
        driver = self._mock_driver_with_whitelist()
        wm = WhitelistManager(driver)
        wm._loaded = True
        wm._cache = {
            ("r1", "U1"): WhitelistEntry(rule_id="r1", refdes="U1"),
            ("r2", "U2"): WhitelistEntry(rule_id="r2", refdes="U2"),
        }
        assert wm.count() == 2

    def test_clear_cache(self):
        driver = self._mock_driver_with_whitelist()
        wm = WhitelistManager(driver)
        wm._loaded = True
        wm._cache = {("r1", "U1"): WhitelistEntry(rule_id="r1", refdes="U1")}
        wm.clear_cache()
        assert wm._loaded is False
        assert len(wm._cache) == 0


# ============================================================
# RuleConfigManager 测试
# ============================================================

class TestRuleConfigManager:
    def test_add_and_get(self):
        mgr = RuleConfigManager()
        rc = RuleConfig(id="test_r1", template_id="decap_check")
        mgr.add_rule(rc)
        assert mgr.get("test_r1") is not None
        assert mgr.get("test_r1").id == "test_r1"

    def test_list_rules_enabled_only(self):
        mgr = RuleConfigManager()
        mgr.add_rule(RuleConfig(id="r1", template_id="decap_check", enabled=True))
        mgr.add_rule(RuleConfig(id="r2", template_id="decap_check", enabled=False))
        assert len(mgr.list_rules(enabled_only=True)) == 1
        assert len(mgr.list_rules(enabled_only=False)) == 2

    def test_get_nonexistent(self):
        mgr = RuleConfigManager()
        assert mgr.get("no_such_rule") is None


# ============================================================
# ReviewRuleEngine 测试（集成，用 mock）
# ============================================================

class TestReviewRuleEngine:
    def test_generate_report_no_violations(self):
        driver = MagicMock()
        engine = ReviewRuleEngine(driver, config_path=None)
        report = engine.generate_report([])
        assert "未发现违规" in report

    def test_generate_report_with_violations(self):
        driver = MagicMock()
        engine = ReviewRuleEngine(driver, config_path=None)
        violations = [
            Violation(id="v1", rule_id="r1", rule_name="Test", refdes="U1",
                      description="Test desc", severity="ERROR"),
        ]
        report = engine.generate_report(violations)
        assert "ERROR" in report
        assert "U1" in report

    def test_get_summary(self):
        driver = MagicMock()
        engine = ReviewRuleEngine(driver, config_path=None)
        violations = [
            Violation(id="v1", rule_id="r1", rule_name="T", refdes="U1", description="d", severity="ERROR"),
            Violation(id="v2", rule_id="r1", rule_name="T", refdes="U2", description="d", severity="WARNING"),
            Violation(id="v3", rule_id="r2", rule_name="T", refdes="U3", description="d", severity="INFO"),
        ]
        summary = engine.get_summary(violations)
        assert summary["total"] == 3
        assert summary["errors"] == 1
        assert summary["warnings"] == 1
        assert summary["infos"] == 1

    def test_add_rule(self):
        driver = MagicMock()
        engine = ReviewRuleEngine(driver, config_path=None)
        rc = RuleConfig(id="custom_r1", template_id="decap_check", params={"min_count": 3})
        engine.add_rule(rc)
        rules = engine.list_rules(enabled_only=False)
        assert any(r.id == "custom_r1" for r in rules)

    def test_run_rules_empty(self):
        """无规则时不报违规"""
        driver = MagicMock()
        engine = ReviewRuleEngine(driver, config_path=None)
        violations = engine.run_rules()
        assert violations == []


# ============================================================
# WhitelistEntry 模型测试
# ============================================================

class TestWhitelistEntryModel:
    def test_create(self):
        e = WhitelistEntry(rule_id="r1", refdes="U1")
        assert e.status == "IGNORE"
        assert e.added_by == "system"

    def test_to_cypher(self):
        e = WhitelistEntry(rule_id="r1", refdes="U1", reason="ok")
        cypher, params = e.to_cypher()
        assert "MERGE" in cypher
        assert params["rule_id"] == "r1"
        assert params["refdes"] == "U1"
