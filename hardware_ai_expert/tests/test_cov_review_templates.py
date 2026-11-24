"""Offline tests for review rule templates (pullup / diff_pair / pinmux / esd / amr).

A fake Neo4j driver answers each Cypher query from a test-provided responder,
so no real database is ever contacted.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))                   # hardware_ai_expert/
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # repo root

from agent_system.review_engine.templates.base import (  # noqa: E402
    RuleContext, TemplateRegistry, _ScopedDriver,
)
from agent_system.review_engine.templates import pullup, diff_pair, pinmux, esd, amr  # noqa: E402


class FakeResult(list):
    def single(self):
        return self[0] if self else None


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, parameters=None, **kwargs):
        params = dict(parameters or {}, **kwargs)
        self.driver.calls.append((query, params))
        return FakeResult(self.driver.responder(query, params) or [])


class FakeDriver:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def session(self, *args, **kwargs):
        return FakeSession(self)


def ctx(responder, project_id=None):
    driver = FakeDriver(responder)
    return RuleContext(neo4j_driver=driver, project_id=project_id), driver


def by_id(violations):
    return {v.id: v for v in violations}


def test_templates_are_registered():
    for tid in ("pullup_check", "diff_pair_check", "pinmux_check", "esd_check", "amr_check"):
        assert TemplateRegistry.get(tid) is not None


# ====================================================================== pullup
@pytest.mark.parametrize("raw,expected", [
    ("10k", 10000.0), ("4.7K", 4700.0), ("1M", 1e6), ("2G", 2e9), ("120", 120.0),
    ("DNP_10k", 10000.0), ("NC_1k", 1000.0), ("0", None), ("", None), (None, None),
    ("abc", None), ("1.2.3k", None), ("1.2.3", None), ("K", None),
])
def test_pullup_parse_resistance(raw, expected):
    assert pullup.parse_resistance(raw) == expected


def test_pullup_format_ohm():
    assert pullup.format_ohm(2.2e6) == "2.20MΩ"
    assert pullup.format_ohm(4700) == "4.7kΩ"
    assert pullup.format_ohm(120) == "120.0Ω"


def test_pullup_no_patterns_runs_no_query():
    context, driver = ctx(lambda q, p: [])
    assert pullup.PullupCheckTemplate().check({}, context) == []
    assert driver.calls == []


def _pullup_responder(nets, resistors, series=None, series_error=False):
    def responder(query, params):
        if "ANY(pattern IN $patterns" in query:
            return [{"net_name": n} for n in nets]
        if "n2 <> n1" in query:
            if series_error:
                raise RuntimeError("db down")
            return (series or {}).get(params["net_name"], [])
        if "CONTAINS 'RES'" in query:
            return resistors.get(params["net_name"], [])
        raise AssertionError(query)
    return responder


def _res(refdes, value):
    return {"res_refdes": refdes, "res_value": value, "res_model": "RES"}


def test_pullup_mode_violations():
    resistors = {
        "I2C_SDA": [_res("R1", "4.7k")],
        "I2C_SCL": [_res("R2", "100")],
        "I3C_SDA": [],
        "I2C_INT": [_res("R5", "DNP_4.7k"), _res("R6", "470")],
    }
    series = {"I2C_SCL": [{"res_value": "DNP_10k"}, {"res_value": "10k", "power_net": "VDD_3V3"}]}
    context, driver = ctx(_pullup_responder(list(resistors), resistors, series))
    params = {"net_patterns": ["I2C", "I3C"], "rule_id": "R_PU", "severity": "ERROR",
              "min_ohm": 1000, "max_ohm": 47000}
    found = by_id(pullup.PullupCheckTemplate().check(params, context))

    assert set(found) == {"R_PU_I3C_SDA", "R_PU_I2C_INT"}
    i3c = found["R_PU_I3C_SDA"]
    assert i3c.severity == "INFO"          # I3C needs no classic pull-up
    assert i3c.actual == "无上拉电阻"
    assert i3c.expected == "阻值在 1.0kΩ ~ 47.0kΩ 之间"
    i2c = found["R_PU_I2C_INT"]
    assert i2c.severity == "ERROR" and i2c.refdes == "总线" and i2c.net_name == "I2C_INT"
    assert i2c.actual == "R5(DNP_4.7k), R6(470)"
    assert ["I2C", "I3C"] == driver.calls[0][1]["patterns"]


def test_pullup_series_lookup_failure_is_treated_as_missing():
    resistors = {"I2C_SDA": []}
    context, _ = ctx(_pullup_responder(["I2C_SDA"], resistors, series_error=True))
    out = pullup.PullupCheckTemplate().check({"net_patterns": ["I2C"]}, context)
    assert [v.id for v in out] == ["pullup_check_I2C_SDA"]
    assert out[0].severity == "WARNING" and out[0].rule_name == "上拉/终端电阻检查"


def test_pullup_termination_mode():
    resistors = {
        "CAN_H": [_res("R10", "120")],
        "CAN_L": [_res("R11", "60"), _res("R12", "bad")],
        "CAN_X": [],
    }
    context, _ = ctx(_pullup_responder(list(resistors), resistors))
    params = {"net_patterns": ["CAN"], "check_mode": "termination", "rule_id": "T"}
    found = by_id(pullup.PullupCheckTemplate().check(params, context))
    assert set(found) == {"T_CAN_L", "T_CAN_X"}
    assert found["T_CAN_L"].expected == "120Ω ± 5% (114.0Ω ~ 126.0Ω)"
    assert found["T_CAN_L"].actual == "R11(60), R12(bad)"
    assert found["T_CAN_X"].actual == "无终端电阻"


def test_pullup_project_scope_adds_predicates():
    resistors = {"I2C_SDA": [_res("R1", "4.7k")]}
    context, driver = ctx(_pullup_responder(["I2C_SDA"], resistors), project_id="board-a")
    assert pullup.PullupCheckTemplate().check({"net_patterns": ["I2C"]}, context) == []
    for query, params in driver.calls:
        assert params["project_id"] == "board-a"
        assert "n.project_id = $project_id" in query


# ====================================================================== diff_pair
@pytest.mark.parametrize("name,std", [
    ("PCIE_TX0_P", "PCIe"), ("MIPI_CSI_D0P", "MIPI"), ("USB3_SSTX_P", "USB3"),
    ("USB_DP", "USB2"), ("LVDS_A_P", "LVDS"), ("RGMII_TX_P", "Ethernet"),
    ("HDMI_CLK_P", "HDMI"), ("SATA_RX_P", "SATA"), ("JESD_LANE_P", "JESD204"),
    ("LANE0_TXP", "SerDes"), ("GPIO_P", "Unknown"),
])
def test_infer_signal_standard(name, std):
    assert diff_pair.infer_signal_standard(name) == std


@pytest.mark.parametrize("name,expected", [
    ("REF_CLKP", ("REF_CLKN", "REF_")),
    ("LANE_TXP", ("LANE_TXN", "LANE_")),
    ("LANE_RXP", ("LANE_RXN", "LANE_")),
    ("USB_DP", ("USB_DN", "USB_")),
    ("MIPI_D0P", ("MIPI_D0N", "MIPI_D0")),
    ("PCIE_TX_P", ("PCIE_TX_N", "PCIE_TX")),
    ("PCIE_TX_N", ("PCIE_TX_P", "PCIE_TX")),
    ("ETH_POS", ("ETH_NEG", "ETH")),
    ("ETH_NEG", ("ETH_POS", "ETH")),
    ("LVDS+", ("LVDS-", "LVDS")),
    ("LVDS-", ("LVDS+", "LVDS")),
    ("GPIO1", (None, None)),
])
def test_find_diff_pair(name, expected):
    assert diff_pair.find_diff_pair(name) == expected


def _diff_responder(p_nets, existing=(), counts=None, caps=None, res=None, cmcs=None,
                    drivers=None, driver_error=False):
    counts, caps, res, cmcs, drivers = counts or {}, caps or {}, res or {}, cmcs or {}, drivers or {}

    def responder(query, params):
        if "RETURN n.Name AS net_name" in query:
            return [{"net_name": n} for n in p_nets]
        if "RETURN n.Name AS name" in query:
            return [{"name": params["name"]}] if params["name"] in existing else []
        if "count(DISTINCT c) AS cnt" in query:
            return [{"cnt": counts.get(params["name"], 0)}]
        if "c.PartType IN ['IC'" in query:
            if driver_error:
                raise RuntimeError("db down")
            ref = drivers.get(params["name"])
            return [{"refdes": ref}] if ref else []
        if "CONTAINS 'CAP'" in query:
            return caps.get(params["net_name"], [])
        if "CONTAINS 'RES'" in query:
            return res.get(params["net_name"], [])
        if "CONTAINS 'IND'" in query:
            return cmcs.get(params["p_name"], [])
        raise AssertionError(query)
    return responder


def test_diff_pair_matching():
    responder = _diff_responder(
        ["USB_DP", "PCIE_RX_P", "FOO_P", "HDMI_D0_P", "USB_X_DP"],
        existing={"USB_DN", "USB_X_DN"},
        counts={"USB_DP": 2, "USB_DN": 1, "USB_X_DP": 1, "USB_X_DN": 1},
        drivers={"USB_DP": "U1"},
    )
    context, _ = ctx(responder)
    params = {"check_type": "matching", "signal_standards": ["USB2", "PCIe"], "rule_id": "DP"}
    found = by_id(diff_pair.DiffPairCheckTemplate().check(params, context))
    assert set(found) == {"DP_USB__asymmetric", "DP_PCIE_RX_P_unmatched"}
    asym = found["DP_USB__asymmetric"]
    assert asym.severity == "INFO" and asym.refdes == "U1"
    assert asym.net_name == "USB_DP/USB_DN"
    assert asym.actual == "P端: 2 个器件, N端: 1 个器件"
    unmatched = found["DP_PCIE_RX_P_unmatched"]
    assert unmatched.severity == "WARNING"
    assert unmatched.refdes == "PCIE_RX_P"     # no driver IC: falls back to the net name
    assert "PCIE_RX_N" in unmatched.description


def test_diff_pair_matching_without_filter_reports_unknown_standard():
    context, _ = ctx(_diff_responder(["FOO_P", "GPIO7"], driver_error=True))
    out = diff_pair.DiffPairCheckTemplate().check({"check_type": "matching"}, context)
    assert [v.id for v in out] == ["diff_pair_check_FOO_P_unmatched"]
    assert "(Unknown)" in out[0].description
    assert out[0].refdes == "FOO_P"            # driver lookup error is swallowed


def test_diff_pair_termination():
    responder = _diff_responder(
        ["PCIE_TX_P", "PCIE_REFCLK_P", "PCIE_REFCLK2_P", "USB3_TX_P", "USB_DP", "GPIO9"],
        caps={"USB3_TX_N": [{"refdes": "C1", "value": "100nF"}]},
        res={"PCIE_REFCLK2_P": [{"refdes": "R1", "value": "49.9"}]},
        drivers={"PCIE_TX_P": "U5"},
    )
    context, driver = ctx(responder)
    params = {"check_type": "termination", "rule_id": "T", "severity": "ERROR"}
    found = by_id(diff_pair.DiffPairCheckTemplate().check(params, context))
    assert set(found) == {"T_PCIE_TX_no_ac_cap", "T_PCIE_REFCLK_refclk_term"}
    assert found["T_PCIE_TX_no_ac_cap"].refdes == "U5"
    assert found["T_PCIE_TX_no_ac_cap"].severity == "ERROR"
    assert found["T_PCIE_REFCLK_refclk_term"].actual == "未找到端接电阻"
    assert "(?i)(PCIe|USB3)" in driver.calls[0][0]


def test_diff_pair_termination_and_cmc_disabled_by_empty_lists():
    context, driver = ctx(_diff_responder([]))
    params = {"check_type": "all", "require_ac_coupling": [], "require_cmc": []}
    assert diff_pair.DiffPairCheckTemplate().check(params, context) == []
    assert len(driver.calls) == 1               # only the matching scan ran


def test_diff_pair_cmc():
    responder = _diff_responder(
        ["USB_DP", "RGMII_TX_P", "PCIE_X_P", "USB_OTG_DP"],
        cmcs={"USB_DN": [{"refdes": "L1", "model": "CMC_90R", "pt": "FILTER"}],
              "USB_OTG_DP": [{"refdes": "L2", "model": "CMC", "pt": "IND"}]},
    )
    context, _ = ctx(responder)
    out = diff_pair.DiffPairCheckTemplate().check({"check_type": "cmc", "rule_id": "C"}, context)
    assert [v.id for v in out] == ["C_RGMII_TX_no_cmc"]
    assert out[0].severity == "INFO"
    assert out[0].description.startswith("Ethernet 差分对")


def test_diff_pair_unknown_check_type_runs_nothing():
    context, driver = ctx(_diff_responder([]))
    assert diff_pair.DiffPairCheckTemplate().check({"check_type": "bogus"}, context) == []
    assert driver.calls == []


# ====================================================================== pinmux
def test_pinmux_helpers():
    assert pinmux.is_od_component("ODWR", None) is True
    assert pinmux.is_od_component(None, "open_drain_buf") is True
    assert pinmux.is_od_component("REG", "VOUT") is False
    assert pinmux.is_power_net("VDD_3V3") and not pinmux.is_power_net(None)
    assert pinmux.is_gnd_net("AGND") and not pinmux.is_gnd_net("") and not pinmux.is_gnd_net("SDA")
    assert pinmux.is_signal_net("SDA") and not pinmux.is_signal_net("GND") and not pinmux.is_signal_net(None)
    assert pinmux.is_nc_net("NC") and pinmux.is_nc_net("NC_1") and pinmux.is_nc_net("GPIO_NC")
    assert not pinmux.is_nc_net("GPIO_A0") and not pinmux.is_nc_net(None)


def test_is_pullup_on_net():
    def responder(query, params):
        return {"A": [{"value": "DNP"}, {"value": None}], "B": [{"value": "DNP_1k"}]}.get(params["net_name"], [])
    driver = FakeDriver(responder)
    assert pinmux.is_pullup_on_net(driver, "A") is True      # second resistor counts
    assert pinmux.is_pullup_on_net(driver, "B") is False
    assert pinmux.is_pullup_on_net(driver, "") is False

    def boom(query, params):
        raise RuntimeError("down")
    assert pinmux.is_pullup_on_net(FakeDriver(boom), "A") is False


def _pinmux_responder(od=(), pullups=None, ic=(), nc=(), fail=()):
    pullups = pullups or {}

    def responder(query, params):
        if "c.Model CONTAINS 'OD'" in query:
            if "od" in fail:
                raise RuntimeError("od failed")
            return list(od)
        if "LIMIT 10" in query and "CONTAINS 'RES'" in query:
            return pullups.get(params["net_name"], [])
        if "ANY(pt IN" in query:
            if "ic" in fail:
                raise RuntimeError("ic failed")
            return list(ic)
        if "STARTS WITH 'NC_'" in query:
            if "nc" in fail:
                raise RuntimeError("nc failed")
            return list(nc)
        raise AssertionError(query)
    return responder


def test_pinmux_od_pullup():
    od = [
        {"refdes": "U1", "part_type": "OD", "net_name": "I2C_INT"},
        {"refdes": "U1", "part_type": "OD", "net_name": "I2C_INT"},
        {"refdes": None, "part_type": "OD", "net_name": None},
        {"refdes": "U3", "part_type": "OD", "net_name": "ALERT"},
    ]
    pullups = {"I2C_INT": [{"refdes": "R1", "value": "DNP"}], "ALERT": [{"refdes": "R2", "value": "10k"}]}
    context, _ = ctx(_pinmux_responder(od=od, pullups=pullups))
    params = {"check_power_gnd": False, "rule_id": "PM"}
    found = by_id(pinmux.PinMuxCheckTemplate().check(params, context))
    assert set(found) == {"PM_OD_PULLUP_I2C_INT", "PM_OD_PULLUP_"}
    assert found["PM_OD_PULLUP_I2C_INT"].severity == "ERROR"
    assert found["PM_OD_PULLUP_I2C_INT"].refdes == "U1"
    assert found["PM_OD_PULLUP_"].refdes == "UNKNOWN"


def test_pinmux_power_gnd():
    ic = [
        {"refdes": "U1", "part_type": "IC", "net_name": "VDD_3V3"},
        {"refdes": "U1", "part_type": "IC", "net_name": "GND"},
        {"refdes": "U2", "part_type": "MCU", "net_name": "SIG"},
        {"refdes": "U3", "part_type": "LDO", "net_name": "VCC_5V"},
        {"refdes": None, "part_type": "IC", "net_name": "DGND"},
    ]
    context, _ = ctx(_pinmux_responder(ic=ic))
    params = {"check_od_pullup": False, "rule_id": "PM"}
    found = by_id(pinmux.PinMuxCheckTemplate().check(params, context))
    assert set(found) == {"PM_PWR_MISSING_U2", "PM_GND_MISSING_U2",
                          "PM_GND_MISSING_U3", "PM_PWR_MISSING_UNKNOWN"}
    assert all(v.severity == "WARNING" for v in found.values())


def test_pinmux_nc_pins():
    nc = [
        {"net_name": "NC_1", "connected_refdes": ["U1A", "U1B"], "component_count": 2},
        {"net_name": "NC_SHORT", "connected_refdes": ["U1", "U2", "u9"], "component_count": 3},
        {"net_name": "NC_VDD", "connected_refdes": ["U3"], "component_count": 1},
        {"net_name": "GND_NC", "connected_refdes": [], "component_count": 1},
        {"net_name": None, "connected_refdes": ["U4"], "component_count": 1},
    ]
    context, _ = ctx(_pinmux_responder(nc=nc))
    params = {"check_od_pullup": False, "check_power_gnd": False, "check_nc": True, "rule_id": "PM"}
    found = by_id(pinmux.PinMuxCheckTemplate().check(params, context))
    assert set(found) == {"PM_NC_SHORT_NC_SHORT", "PM_NC_POWER_NC_VDD", "PM_NC_POWER_GND_NC"}
    assert found["PM_NC_SHORT_NC_SHORT"].refdes == "U1,U2,u9"
    assert found["PM_NC_SHORT_NC_SHORT"].actual == "连接了 3 个器件"
    assert found["PM_NC_POWER_NC_VDD"].actual == "网络名含 电源 标识"
    assert found["PM_NC_POWER_GND_NC"].refdes == "UNKNOWN"
    assert found["PM_NC_POWER_GND_NC"].actual == "网络名含 地 标识"


def test_pinmux_query_failures_return_no_violations(capsys):
    context, _ = ctx(_pinmux_responder(fail=("od", "ic", "nc")))
    out = pinmux.PinMuxCheckTemplate().check({"check_nc": True}, context)
    assert out == []
    printed = capsys.readouterr().out
    assert "OD 器件查询失败" in printed and "IC 引脚查询失败" in printed and "NC 网络查询失败" in printed


# ====================================================================== esd
def test_esd_helpers():
    T = esd.ESDCheckTemplate
    assert T._is_power_or_gnd("NC") and T._is_power_or_gnd("NC_3") and T._is_power_or_gnd("PGND")
    assert not T._is_power_or_gnd("") and not T._is_power_or_gnd("USB_DP")
    assert T._is_low_risk_signal("JTAG_TCK") and T._is_low_risk_signal("DATA_R_1")
    assert T._is_low_risk_signal("SIG_LVC") and not T._is_low_risk_signal("USB_DP")
    assert not T._is_low_risk_signal("")

    def boom(query, params):
        raise RuntimeError("down")
    assert T._has_series_resistor(FakeDriver(boom), "X") is False
    driver = FakeDriver(lambda q, p: [{"value": None}, {"value": "1k"}])
    assert T._has_series_resistor(driver, "X") is True
    assert T._has_series_resistor(FakeDriver(lambda q, p: [{"value": "33"}]), "X") is False


def _esd_responder(pattern_nets=(), conn_nets=(), esd_devices=None, series=None, connectors=None):
    esd_devices, series, connectors = esd_devices or {}, series or {}, connectors or {}

    def responder(query, params):
        if "ANY(pattern IN $patterns" in query:
            return [{"net_name": n} for n in pattern_nets]
        if "RETURN DISTINCT n.Name AS net_name" in query:
            return [{"net_name": n} for n in conn_nets]
        if "CONTAINS 'TVS'" in query:
            return esd_devices.get(params["net_name"], [])
        if "conn_refdes" in query:
            return connectors.get(params["net_name"], [])
        if "CONTAINS 'RES'" in query:
            return series.get(params["net_name"], [])
        raise AssertionError(query)
    return responder


def test_esd_check_reports_unprotected_nets():
    responder = _esd_responder(
        pattern_nets=["USB_DP", "USB_DN", "USB_VCC", "UART_TX"],
        conn_nets=["USB_ID", "HDMI_X", "USB_DP"],
        esd_devices={"USB_DP": [{"esd_refdes": "D1", "esd_value": "", "esd_model": "TVS"}]},
        series={"USB_DN": [{"value": "10K"}]},
        connectors={"USB_DN": [{"conn_refdes": "J1", "conn_type": "USB_CONN"}]},
    )
    context, driver = ctx(responder)
    params = {"net_patterns": ["USB", "UART"], "rule_id": "E", "max_capacitance_pf": 1.0}
    found = by_id(esd.ESDCheckTemplate().check(params, context))
    assert set(found) == {"E_USB_DN", "E_USB_ID"}
    dn = found["E_USB_DN"]
    assert dn.severity == "INFO"                       # series resistor downgrades
    assert dn.refdes == "J1"
    assert dn.description == "连接器 J1(USB_CONN) 的信号网络 'USB_DN' 缺少 ESD/TVS 保护"
    assert dn.actual == "未找到 ESD/TVS 保护器件 (有串联电阻)"
    assert dn.expected == "应配置 ESD/TVS 保护器件 (电容 < 1.0pF)"
    usb_id = found["E_USB_ID"]
    assert usb_id.severity == "WARNING" and usb_id.refdes == "网络"
    assert usb_id.actual == "未找到 ESD/TVS 保护器件"
    conn_call = [p for q, p in driver.calls if "RETURN DISTINCT" in q][0]
    assert conn_call["prefixes"] == ["J", "P", "CON"]


def test_esd_connector_only_mode_takes_all_connector_nets():
    responder = _esd_responder(conn_nets=["HDMI_HPD"])
    context, driver = ctx(responder)
    out = esd.ESDCheckTemplate().check({"connector_prefixes": ["CN"]}, context)
    assert [v.id for v in out] == ["esd_check_HDMI_HPD"]
    assert not any("ANY(pattern IN $patterns" in q for q, _ in driver.calls)


def test_esd_no_targets():
    context, driver = ctx(_esd_responder())
    assert esd.ESDCheckTemplate().check({"connector_prefixes": []}, context) == []
    assert driver.calls == []


# ====================================================================== amr
class _Annotator:
    calls = []

    @classmethod
    def batch_annotate_neo4j(cls, driver):
        cls.calls.append(driver)
        return 3


@pytest.fixture
def annotator(monkeypatch):
    _Annotator.calls = []
    monkeypatch.setattr(amr, "VoltageLevelExtractor", _Annotator)
    return _Annotator


def _amr_responder(resistors, voltages):
    def responder(query, params):
        if "LIMIT 2000" in query:
            return list(resistors)
        if "v_num AS voltage" in query:
            v = voltages.get(params["refdes"], "missing")
            return [] if v == "missing" else [{"voltage": v}]
        raise AssertionError(query)
    return responder


AMR_RESISTORS = [
    {"refdes": "R1", "value": "10", "model": "RES_R0402_10R"},     # 2.5 W on 62.5 mW: fail
    {"refdes": "R2", "value": "10k", "model": "RES_R0402_10K"},    # 1.7 %: pass
    {"refdes": "R3", "value": "abc", "model": "RES_R0402"},        # unparsable value
    {"refdes": "R4", "value": "1k", "model": None},                # no package
    {"refdes": "R5", "value": "1k", "model": "CAP_C0402_X"},       # no power rating
    {"refdes": "R6", "value": "100", "model": "R0603"},            # no voltage rows
    {"refdes": "R7", "value": "100", "model": "R0603"},            # below min voltage
    {"refdes": "R8", "value": "100", "model": "R0603"},            # voltage None
]
AMR_VOLTAGES = {"R1": 5.0, "R2": 3.3, "R7": 0.05, "R8": None}


def test_amr_resistor_power_violation(annotator):
    context, driver = ctx(_amr_responder(AMR_RESISTORS, AMR_VOLTAGES))
    out = amr.AMRCheckTemplate().check({"rule_id": "A", "severity": "ERROR"}, context)
    assert [v.id for v in out] == ["A_R1"]
    v = out[0]
    assert v.refdes == "R1" and v.severity == "ERROR" and v.net_name == ""
    assert v.expected == "降额率 ≤ 50%"
    assert v.actual == "降额率 4000.0%"
    assert "功率降额超标" in v.description
    assert len(annotator.calls) == 1
    assert isinstance(annotator.calls[0], _ScopedDriver)   # aggregate review annotates via the driver
    voltage_lookups = [p["refdes"] for q, p in driver.calls if "v_num" in q]
    assert voltage_lookups == ["R1", "R2", "R6", "R7", "R8"]


def test_amr_standard_selection(annotator):
    resistors = [{"refdes": "R1", "value": "1k", "model": "RES_R0402_1K"}]
    # unknown standard falls back to industry: 3.3^2/1000 = 10.9 mW on 62.5 mW = 17.4 % <= 50 %
    context, _ = ctx(_amr_responder(resistors, {"R1": 3.3}))
    assert amr.AMRCheckTemplate().check({"standard": "bogus"}, context) == []

    # 5^2/1000 = 25 mW on 62.5 mW = 40 %: passes industry, fails GJB (30 %)
    context, _ = ctx(_amr_responder(resistors, {"R1": 5.0}))
    assert amr.AMRCheckTemplate().check({"standard": "industry"}, context) == []
    context, _ = ctx(_amr_responder(resistors, {"R1": 5.0}))
    out = amr.AMRCheckTemplate().check({"standard": "gjb_z_35"}, context)
    assert [v.expected for v in out] == ["降额率 ≤ 30%"]
    assert out[0].actual == "降额率 40.0%"


def test_amr_resistor_check_disabled(annotator):
    context, driver = ctx(lambda q, p: pytest.fail("no query expected"))
    assert amr.AMRCheckTemplate().check({"check_resistor_power": False}, context) == []
    assert driver.calls == []
    assert len(annotator.calls) == 1


def test_amr_project_scope_skips_global_annotation(annotator):
    context, driver = ctx(_amr_responder(AMR_RESISTORS[:1], {"R1": 5.0}), project_id="board-a")
    out = amr.AMRCheckTemplate().check({"check_capacitor_voltage": False}, context)
    assert [v.id for v in out] == ["amr_check_R1"]
    assert annotator.calls == []
    for query, params in driver.calls:
        assert params["project_id"] == "board-a"
        assert "c.project_id = $project_id" in query
