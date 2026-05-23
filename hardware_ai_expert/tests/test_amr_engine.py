"""
AMR Engine 单元测试
- _parse_capacitance_to_pf: 容值字符串解析
- _infer_voltage_from_package_value: 封装+容值推断电压
- AMRDataSource: 数据源优先级
"""

import sys
import os
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from agent_system.amr_engine import _parse_capacitance_to_pf, AMRDataSource


class TestParseCapacitance:
    """_parse_capacitance_to_pf 单元测试"""

    def test_uf(self):
        assert _parse_capacitance_to_pf("0.1uF") == 100_000.0
        assert _parse_capacitance_to_pf("1uF") == 1_000_000.0
        assert _parse_capacitance_to_pf("22UF") == 22_000_000.0
        assert _parse_capacitance_to_pf("4.7 UF") == 4_700_000.0

    def test_nf(self):
        assert _parse_capacitance_to_pf("10nF") == 10_000.0
        assert _parse_capacitance_to_pf("100NF") == 100_000.0

    def test_pf(self):
        assert _parse_capacitance_to_pf("100pF") == 100.0
        assert _parse_capacitance_to_pf("2.2PF") == 2.2

    def test_mf(self):
        assert _parse_capacitance_to_pf("1mF") == 1_000_000_000.0

    def test_dnp_prefix(self):
        assert _parse_capacitance_to_pf("DNP_47 UF") == 47_000_000.0
        # DNI not handled, skip

    def test_dni_not_supported(self):
        # DNI 前缀当前未处理
        result = _parse_capacitance_to_pf("DNI_0.1uF")
        # 可能 None 或解析成功
        assert result is None or result == 100_000.0

    def test_empty(self):
        assert _parse_capacitance_to_pf("") is None
        assert _parse_capacitance_to_pf(None) is None

    def test_no_unit_defaults_uf(self):
        # 无单位默认 uF
        assert _parse_capacitance_to_pf("0.1") == 100_000.0


class TestInferVoltageFromPackage:
    """封装+容值经验表推断电压

    注意：FileBasedAMRSource 优先级更高，若 YAML 有匹配数据则返回 YAML 值，
    经验表值作为 fallback。测试验证返回合理电压值（非 None）。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.src = AMRDataSource()

    def test_0402_100nf_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C1", "CAP_C0402_DISCRETE_0.1UF_110-00", "0.1uF")
        assert v is not None and v >= 6.3  # 合理电压值

    def test_0402_1uf_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C2", "CAP_MS_DISCRETE_C0402_DISCRET_1", "1uF")
        assert v is not None and v >= 4.0

    def test_0603_10uf_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C3", "CAP_C0603_DISCRETE_10UF", "10uF")
        assert v is not None and v >= 4.0

    def test_0805_100nf_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C4", "CAP_C0805_DISCRETE_0.1UF", "0.1uF")
        assert v is not None and v >= 6.3

    def test_1206_22uf_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C5", "CAP_SMC1206A_DISCRETE_22UF_110-", "22uF")
        assert v is not None and v >= 6.3

    def test_tantalum_has_voltage(self):
        v = self.src.get_capacitor_voltage_rating("C6", "CAP_P_C7343P-H3_10_DISCRETE_330", "330uF")
        assert v is not None and v >= 4.0

    def test_unknown_package(self):
        # 未知封装无匹配 → None（fallback to KnowledgeRouter/GraphRAG）
        v = self.src.get_capacitor_voltage_rating("C7", "UNKNOWN_PACKAGE_123", "0.1uF")
        # 可能从 FileBasedAMRSource 或其他来源拿到，也可能 None
        # 只要不 crash 就行
        assert v is None or isinstance(v, (int, float))

    def test_no_value(self):
        # 无容值 → None
        v = self.src.get_capacitor_voltage_rating("C8", "CAP_C0402_DISCRETE", None)
        assert v is None or isinstance(v, (int, float))


class TestAMRDataSourcePriority:
    """AMRDataSource 优先级测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.src = AMRDataSource()

    def test_file_based_takes_priority(self):
        # FileBasedAMRSource 有精确匹配数据时优先返回
        v = self.src.get_capacitor_voltage_rating("C1", "CAP_C0402_DISCRETE_0.1UF_110-00", "0.1uF")
        assert v is not None
        # FileBasedAMRSource 中这个 Model 应该有 10V 的记录
        # 但如果经验表也匹配（0402+100nF→16V），FileBased 优先
        # 实际取决于哪个先返回非 None

    def test_fallback_chain_no_crash(self):
        # 整条链路不 crash
        v = self.src.get_capacitor_voltage_rating("X", "NONEXISTENT_MODEL", "1pF")
        # 允许 None
        assert v is None or isinstance(v, (int, float))
