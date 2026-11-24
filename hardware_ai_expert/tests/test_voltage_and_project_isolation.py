import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert" / "etl_pipeline"))
sys.path.insert(0, str(ROOT))

from load_topology import infer_net_properties
from expand_voltage_annotation import extract_voltage_from_name
from scripts.check_data_quality import _expected_voltage, _quality_details, _rail_family


def test_voltage_patterns_cover_ddr_and_core_rails():
    cases = {
        "VDDQ_DDR": "1.2V",
        "VTT_DDR": "0.6V",
        "VPP_DDR": "2.5V",
        "1V0_DDR": "1.0V",
        "VDD_CORE_0V85": "0.85V",
        "PVCC_3V3": "3.3V",
        "FB_V1V0": "1.0V",
    }
    for net, expected in cases.items():
        props = infer_net_properties(net)
        assert props["VoltageLevel"] == expected, (net, props)
        if not net.startswith("FB_"):
            assert props["NetType"] == "POWER", (net, props)


def test_non_power_bus_classification_preserved():
    props = infer_net_properties("I2C0_SCL")
    assert props["VoltageLevel"] is None
    assert props["NetType"] == "BUS"


def test_voltage_annotation_expansion_covers_compact_and_decimal_tokens():
    cases = {
        "VDD_CORE_0V85": "0.85",
        "PVCC_3V3": "3.3",
        "FB_V1V0": "1.0",
        "VDDQ_1P2_DDR": "1.2",
        "VTT_0P675": "0.675",
        "DDR_DQ0": None,
    }
    for net, expected in cases.items():
        voltage, _rule = extract_voltage_from_name(net)
        assert voltage == expected, (net, voltage)


def test_quality_rails_require_grounded_voltage():
    for rail in ("VDDQ_1V2_DDR", "VPP_2V5_DDR", "VTT_0V675",
                 "1V0_DDR", "1V2_LPDDR", "1V5_DDR"):
        assert _rail_family(rail) is not None
        assert _expected_voltage(rail) is not None
    for rail in ("VTT_DDR", "VDDQ_DDR", "VPP_DDR"):
        assert _rail_family(rail) is not None
        assert _expected_voltage(rail) is None
    assert _rail_family("DDR_DQ0") is None
    assert _rail_family("LPDDR_CLK") is None


def test_post_injection_quality_details_are_project_scoped():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def data(self):
            return self.rows

    class Session:
        def run(self, query, **params):
            assert params == {"pid": "board_a"}
            assert "project_id: $pid" in query
            if "MATCH (n:Net" in query:
                assert "Pin {project_id: $pid}" in query
                return Result([
                    {"name": "VTT_DDR", "voltage": None, "pin_count": 1},
                    {"name": "VDDQ_1V2_DDR", "voltage": "1.2V", "pin_count": 2},
                    {"name": "DDR_DQ0", "voltage": None, "pin_count": 2},
                ])
            return Result([
                {"refdes": "C1", "mpn": "ABC", "package": "0402",
                 "manufacturer": "M", "parttype": "CAPACITOR", "rating": None},
                {"refdes": "C2", "mpn": "ABC", "package": "0402",
                 "manufacturer": "M", "parttype": "CAPACITOR", "rating": "16V"},
            ])

    d = _quality_details(Session(), "board_a")
    assert d["core_total"] == 2
    assert d["missing_connectivity"] == ["VTT_DDR"]
    assert d["missing_voltage"] == ["VTT_DDR"]
    assert d["cap_total"] == 2
    assert len(d["missing_caps"]) == 1
    assert d["cap_groups"][("ABC", "0402", "M")] == 1
    assert d["existence"] == {"numerator": 2, "denominator": 3, "missing": []}
    assert d["connectivity"] == {"numerator": 1, "denominator": 2,
                                  "missing": ["VTT_DDR"]}
    assert d["annotation"] == {"numerator": 1, "denominator": 2,
                               "missing": ["VTT_DDR"]}
