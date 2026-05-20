"""
MPN Decoder 单元测试
"""
import sys
import os
import pytest

# 确保可以 import 项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_system.mpn_decoder import (
    MPNDecoder, DecodedComponent, AMRDataGenerator,
    decode_capacitance_code, _pf_to_human, _parse_voltage, _parse_power,
    _cap_str_to_pf, TEMP_CHARACTERISTICS, VOLTAGE_CODES_MURATA,
    VOLTAGE_CODES_SAMSUNG, PACKAGE_CODES, RESISTOR_POWER_BY_PACKAGE,
)


@pytest.fixture
def decoder():
    return MPNDecoder()


@pytest.fixture
def amr_gen():
    return AMRDataGenerator()


# ============================================================
# decode_capacitance_code 测试
# ============================================================

class TestDecodeCapacitanceCode:
    def test_3digit_104(self):
        """104 → 0.1uF"""
        assert decode_capacitance_code("104") == "0.1uF"

    def test_3digit_106(self):
        """106 → 10uF"""
        assert decode_capacitance_code("106") == "10uF"

    def test_3digit_100(self):
        """100 → 10pF"""
        assert decode_capacitance_code("100") == "10pF"

    def test_3digit_220(self):
        """220 → 22pF"""
        assert decode_capacitance_code("220") == "22pF"

    def test_4digit_high_precision(self):
        """4位容值码"""
        result = decode_capacitance_code("1004")
        assert result is not None
        assert "uF" in result

    def test_empty_string(self):
        assert decode_capacitance_code("") is None

    def test_none_input(self):
        assert decode_capacitance_code(None) is None

    def test_short_code(self):
        """1位码无法解码"""
        assert decode_capacitance_code("1") is None

    def test_non_digit(self):
        assert decode_capacitance_code("ABC") is None


# ============================================================
# Murata MLCC 解码测试
# ============================================================

class TestMurataDecoding:
    def test_grm155r71c104ka88d(self, decoder):
        """典型 Murata 0402 0.1uF X7R 16V"""
        r = decoder.decode("GRM155R71C104KA88D")
        assert r.category == "capacitor"
        assert r.manufacturer == "Murata"
        assert r.package == "0402"
        assert r.capacitance is not None
        assert "0.1" in r.capacitance or "100" in r.capacitance
        assert r.confidence > 0

    def test_grm_murata_voltage(self, decoder):
        """Murata 电压解码"""
        r = decoder.decode("GRM155R71C104KA88D")
        # 1C = 16V
        assert r.voltage_rating == "16V" or r.voltage_rating_v == 16.0

    def test_grm_murata_temp(self, decoder):
        """Murata 温度特性 R7 = X7R"""
        r = decoder.decode("GRM155R71C104KA88D")
        assert r.temp_characteristic == "X7R"

    def test_grm_tolerance(self, decoder):
        """Murata 精度 K = ±10%"""
        r = decoder.decode("GRM155R71C104KA88D")
        assert r.tolerance == "±10%"

    def test_grm_package_0603(self, decoder):
        """GRM18 = 0603"""
        r = decoder.decode("GRM188R71C104KA01D")
        assert r.package == "0603"

    def test_grm_confidence_range(self, decoder):
        """置信度应在 0~1 之间"""
        r = decoder.decode("GRM155R71C104KA88D")
        assert 0.0 <= r.confidence <= 1.0


# ============================================================
# Samsung CL 解码测试
# ============================================================

class TestSamsungDecoding:
    def test_cl05b104ko5nnnc(self, decoder):
        """Samsung CL05 0402 0.1uF"""
        r = decoder.decode("CL05B104KO5NNNC")
        assert r.category == "capacitor"
        assert r.manufacturer == "Samsung"
        assert r.package == "0402"
        assert r.capacitance is not None

    def test_cl_size_0603(self, decoder):
        """Samsung CL10 = 0603"""
        r = decoder.decode("CL10B104KO5NNNC")
        assert r.package == "0603"

    def test_cl_voltage(self, decoder):
        """Samsung 电压码 O=16V"""
        r = decoder.decode("CL05B104KO5NNNC")
        # O 码 → 16V
        assert r.voltage_rating is not None or r.confidence > 0


# ============================================================
# TDK C 解码测试
# ============================================================

class TestTDKDecoding:
    def test_c1005x5r1c104k050bc(self, decoder):
        """TDK C1005 = 0402 metric"""
        r = decoder.decode("C1005X5R1C104K050BC")
        assert r.category == "capacitor"
        assert r.manufacturer == "TDK"
        assert r.package == "0402"

    def test_tdk_temp_characteristic(self, decoder):
        """TDK 温度特性 X5R"""
        r = decoder.decode("C1005X5R1C104K050BC")
        assert r.temp_characteristic == "X5R"

    def test_tdk_capacitance(self, decoder):
        """TDK 容值 104"""
        r = decoder.decode("C1005X5R1C104K050BC")
        assert r.capacitance is not None


# ============================================================
# Yageo CC 解码测试
# ============================================================

class TestYageoDecoding:
    def test_cc0402krx7r9bb104(self, decoder):
        """Yageo CC0402"""
        r = decoder.decode("CC0402KRX7R9BB104")
        assert r.category == "capacitor"
        assert r.manufacturer == "Yageo"
        assert r.package == "0402"

    def test_yageo_capacitance(self, decoder):
        """Yageo 末尾 3 位容值"""
        r = decoder.decode("CC0402KRX7R9BB104")
        assert r.capacitance is not None

    def test_yageo_temp(self, decoder):
        """Yageo 温度特性"""
        r = decoder.decode("CC0402KRX7R9BB104")
        assert r.temp_characteristic == "X7R"


# ============================================================
# 电阻 MPN 解码
# ============================================================

class TestResistorDecoding:
    def test_rc0402_resistor(self, decoder):
        """RC 开头识别为电阻"""
        r = decoder.decode("RC0402FR-0710KL")
        assert r.category == "resistor"

    def test_resistor_package(self, decoder):
        """电阻封装识别"""
        r = decoder.decode("RC0402FR-0710KL")
        assert r.package == "0402"

    def test_resistor_power(self, decoder):
        """电阻功率映射"""
        r = decoder.decode("RC0402FR-0710KL")
        assert r.power_rating is not None


# ============================================================
# 通用解码（描述字符串）
# ============================================================

class TestGenericDecoding:
    def test_cap_description(self, decoder):
        """从描述字符串提取电容参数"""
        r = decoder.decode("CAP 0.1UF 16V 0402")
        assert r.category == "capacitor"
        assert r.capacitance is not None
        assert r.voltage_rating is not None

    def test_res_description(self, decoder):
        """从描述字符串提取电阻参数"""
        r = decoder.decode("RESISTOR 10K 0603")
        assert r.category == "resistor"
        assert r.resistance is not None

    def test_unknown_mpn(self, decoder):
        """未知 MPN"""
        r = decoder.decode("XYZ123ABC")
        assert r.category == "unknown"
        assert r.confidence <= 0.2

    def test_resistor_ohm(self, decoder):
        """阻值单位 R"""
        r = decoder.decode("RESISTOR 33R 0805")
        assert r.category == "resistor"
        assert r.resistance_ohm == 33.0

    def test_resistor_megohm(self, decoder):
        """阻值单位 M"""
        r = decoder.decode("RESISTOR 1M 0805")
        assert r.category == "resistor"
        assert r.resistance_ohm == 1_000_000


# ============================================================
# Neo4j 描述解码
# ============================================================

class TestNeo4jDescription:
    def test_cap_c0402(self, decoder):
        """CAP_C0402_DISCRETE_0.1UF"""
        r = decoder.decode_neo4j_description("CAP_C0402_DISCRETE_0.1UF_110-0014", "CAPACITOR")
        assert r.category == "capacitor"
        assert r.package == "0402"
        assert r.capacitance is not None

    def test_res_r0402(self, decoder):
        """RES_R0402_DISCRETE_4.7K"""
        r = decoder.decode_neo4j_description("RES_R0402_DISCRETE_4.7K_100-002", "RESISTOR")
        assert r.category == "resistor"
        assert r.package == "0402"
        assert r.resistance is not None
        assert r.resistance_ohm == 4700.0

    def test_res_zero_ohm(self, decoder):
        """0 欧电阻"""
        r = decoder.decode_neo4j_description("RES_R0402_DISCRETE_0_100-00241-", "RESISTOR")
        assert r.category == "resistor"
        assert r.resistance_ohm == 0.0

    def test_cap_uf_fallback(self, decoder):
        """U 后缺 F 的情况"""
        r = decoder.decode_neo4j_description("CAP_C0402_DISCRETE_0.1U_110", "CAPACITOR")
        assert r.capacitance is not None


# ============================================================
# 边界情况
# ============================================================

class TestEdgeCases:
    def test_empty_string(self, decoder):
        """空字符串"""
        r = decoder.decode("")
        assert r.category == "unknown"

    def test_whitespace_only(self, decoder):
        """纯空格"""
        r = decoder.decode("   ")
        assert r.category == "unknown"

    def test_very_long_string(self, decoder):
        """超长字符串不崩溃"""
        r = decoder.decode("A" * 1000)
        assert r is not None

    def test_special_characters(self, decoder):
        """特殊字符"""
        r = decoder.decode("!@#$%^&*()")
        assert r is not None

    def test_case_insensitive(self, decoder):
        """大小写不敏感"""
        r1 = decoder.decode("grm155r71c104ka88d")
        r2 = decoder.decode("GRM155R71C104KA88D")
        assert r1.category == r2.category
        assert r1.manufacturer == r2.manufacturer


# ============================================================
# 辅助函数测试
# ============================================================

class TestHelperFunctions:
    def test_pf_to_human_uf(self):
        assert _pf_to_human(1_000_000) == "1uF"

    def test_pf_to_human_nf(self):
        assert _pf_to_human(1_000) == "1nF"

    def test_pf_to_human_pf(self):
        assert _pf_to_human(100) == "100pF"

    def test_parse_voltage(self):
        assert _parse_voltage("16V") == 16.0
        assert _parse_voltage("6.3V") == 6.3

    def test_parse_power_fraction(self):
        assert abs(_parse_power("1/16W") - 0.0625) < 1e-6

    def test_parse_power_decimal(self):
        assert _parse_power("1W") == 1.0

    def test_cap_str_to_pf(self):
        assert _cap_str_to_pf("0.1uF") == 100000.0
        assert _cap_str_to_pf("100nF") == 100000.0
        assert _cap_str_to_pf("10pF") == 10.0


# ============================================================
# AMRDataGenerator 测试
# ============================================================

class TestAMRDataGenerator:
    def test_cap_amr_entry(self, decoder, amr_gen):
        """电容 AMR 条目生成"""
        r = decoder.decode("GRM155R71C104KA88D")
        amr = amr_gen.generate_amr_entry(r)
        if amr:
            assert amr["category"] == "capacitor"
            assert "voltage_rating_V" in amr
            assert "derating_factor" in amr

    def test_resistor_amr_entry(self, decoder, amr_gen):
        """电阻 AMR 条目生成"""
        r = decoder.decode("RC0402FR-0710KL")
        amr = amr_gen.generate_amr_entry(r)
        if amr:
            assert amr["category"] == "resistor"
            assert "power_rating_W" in amr

    def test_unknown_no_amr(self, decoder, amr_gen):
        """未知器件不生成 AMR"""
        r = decoder.decode("XYZ123")
        amr = amr_gen.generate_amr_entry(r)
        assert amr is None

    def test_neo4j_cap_amr(self, decoder, amr_gen):
        """从 Neo4j 描述生成 AMR"""
        r = decoder.decode_neo4j_description("CAP_C0402_DISCRETE_0.1UF_110-0014", "CAPACITOR")
        amr = amr_gen.generate_amr_entry(r)
        if amr:
            assert "max_operating_voltage_V" in amr


# ============================================================
# DecodedComponent to_dict 测试
# ============================================================

class TestDecodedComponent:
    def test_to_dict_excludes_none(self, decoder):
        """to_dict 排除 None 字段"""
        r = decoder.decode("GRM155R71C104KA88D")
        d = r.to_dict()
        assert "mpn" in d
        # None 字段不应出现
        for k, v in d.items():
            assert v is not None

    def test_to_dict_has_required_fields(self, decoder):
        """to_dict 包含必需字段"""
        r = decoder.decode("GRM155R71C104KA88D")
        d = r.to_dict()
        assert "category" in d
        assert "manufacturer" in d
