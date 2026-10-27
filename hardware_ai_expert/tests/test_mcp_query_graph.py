"""MCP `query_graph` 批量 / 子图扩展的单元测试（全部离线，mock Cypher）。

覆盖：
1. 旧单值参数行为不变（文本格式、逐字对比）
2. refdes_list / net_name_list 批量（结构、去重、缺失对象、聚合阈值）
3. neighborhood 的体量裁剪与 truncated 语义
4. 传入非法/超范围参数时的收敛
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_system import graph_tools as gt
from mcp_server import query_engine, tools


CENTER_NETS = [
    {"pin_number": "1", "pin_type": "POWER", "net_name": "VIN_12V", "voltage": 12.0, "net_type": "POWER"},
    {"pin_number": "2", "pin_type": "SIGNAL", "net_name": "SW1", "voltage": 12.0, "net_type": "POWER"},
    {"pin_number": "3", "pin_type": "SIGNAL", "net_name": "FB1", "voltage": None, "net_type": "SIGNAL"},
]

PEER_ROWS = [
    {"net": "VIN_12V", "peers": [
        {"refdes": "C1", "part_type": "CAPACITOR", "mpn": "CAP_0603", "value": "10uF", "pins": ["1"]},
        {"refdes": "C2", "part_type": "CAPACITOR", "mpn": "CAP_0603", "value": "1uF", "pins": ["1"]},
    ]},
    {"net": "SW1", "peers": [
        {"refdes": "L1", "part_type": "INDUCTOR", "mpn": "IND_4020", "value": "2.2uH", "pins": ["1"]},
    ]},
    {"net": "FB1", "peers": []},
]


def _router(rows_by_marker):
    """按查询里的关键片段路由 mock 结果。"""

    def fake(query, params=None, **kwargs):
        for marker, rows in rows_by_marker.items():
            if marker in query:
                if callable(rows):
                    return rows(params or {})
                return rows
        return []

    return fake


@pytest.fixture
def bound_project(monkeypatch):
    monkeypatch.setenv("SCHEMATIC_PROJECT_ID", "testproj")
    return "testproj"


# ---------------------------------------------------------------------------
# 1. 向后兼容
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_component_nets_keeps_legacy_text_format(bound_project, monkeypatch):
    rows = [
        {"pin_number": "1", "pin_type": "POWER", "net_name": "VIN_12V",
         "voltage_level": 12.0, "net_type": "POWER"},
        {"pin_number": "2", "pin_type": "SIGNAL", "net_name": "FB1",
         "voltage_level": None, "net_type": "SIGNAL"},
    ]
    monkeypatch.setattr(gt, "_run_cypher", _router({"CONNECTS_TO" : rows}))
    out = tools.query_graph(query_type="component_nets", refdes="U1")
    assert out == (
        "[project=testproj | tool=query_graph]\n"
        "器件 U1 的网络连接:\n"
        "  Pin 1 (POWER) -> Net 'VIN_12V' [12.0]\n"
        "  Pin 2 (SIGNAL) -> Net 'FB1' [?]"
    )


@pytest.mark.unit
def test_single_net_components_keeps_legacy_text_format(bound_project, monkeypatch):
    def by_marker(params):
        return None

    monkeypatch.setattr(
        gt,
        "_run_cypher",
        _router(
            {
                "count(DISTINCT c) AS total_components": [
                    {"total_components": 1, "total_pins": 1}
                ],
                "ORDER BY c.RefDes, p.Number": [
                    {"refdes": "C1", "part_type": "CAPACITOR", "value": "10uF",
                     "pin_number": "1", "pin_type": "POWER"}
                ],
            }
        ),
    )
    out = tools.query_graph(query_type="net_components", net_name="VIN_12V")
    assert out.startswith("[project=testproj | tool=query_graph]\n网络 'VIN_12V' 的连接器件")
    assert "C1 (CAPACITOR, 10uF)" in out


@pytest.mark.unit
def test_missing_arguments_still_error_in_legacy_shape(bound_project):
    out = tools.query_graph(query_type="component_nets")
    assert "| error] ValueError" in out
    out = tools.query_graph(query_type="net_components")
    assert "| error] ValueError" in out


# ---------------------------------------------------------------------------
# 2. 批量
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bulk_component_nets_returns_each_device_structure(bound_project, monkeypatch):
    rows = [
        {"refdes": "U1", "pin_number": "1", "pin_type": "POWER", "net_name": "VIN",
         "voltage": 12.0, "net_type": "POWER"},
        {"refdes": "U1", "pin_number": "2", "pin_type": "SIGNAL", "net_name": "FB",
         "voltage": None, "net_type": "SIGNAL"},
        {"refdes": "U2", "pin_number": "1", "pin_type": "POWER", "net_name": "VIN",
         "voltage": 12.0, "net_type": "POWER"},
    ]
    monkeypatch.setattr(gt, "_run_cypher", _router({"c.RefDes IN $refdes_list": rows}))

    out = tools.query_graph(
        query_type="component_nets", refdes_list=["U1", "U2", "U404", "U1"]
    )
    payload = json.loads(out.split("\n", 1)[1])
    assert payload["refdes_list"] == ["U1", "U2", "U404"]
    assert payload["not_found"] == ["U404"]
    assert payload["truncated"] is False
    by_ref = {item["refdes"]: item for item in payload["components"]}
    assert by_ref["U1"]["pin_count"] == 2
    assert by_ref["U1"]["net_count"] == 2
    assert by_ref["U1"]["pins"][0] == {
        "pin": "1", "type": "POWER", "net": "VIN", "v": 12.0, "nt": "POWER"
    }
    assert by_ref["U2"]["pin_count"] == 1
    assert by_ref["U404"]["found"] is False and by_ref["U404"]["pins"] == []
    assert payload["stats"]["pins"] == 3


@pytest.mark.unit
def test_bulk_net_components_aggregates_large_nets(bound_project, monkeypatch):
    counts = [
        {"net": "SMALL", "component_count": 2, "pin_count": 2},
        {"net": "GND", "component_count": 500, "pin_count": 900},
    ]
    detail = [
        {"net": "SMALL", "refdes": "C1", "part_type": "CAPACITOR", "value": "1uF",
         "pin_number": "1", "pin_type": "POWER"},
        {"net": "SMALL", "refdes": "C2", "part_type": "CAPACITOR", "value": "1uF",
         "pin_number": "1", "pin_type": "POWER"},
    ]
    agg = [
        {"net": "GND", "part_type": "CAPACITOR", "component_count": 400,
         "pin_count": 700, "examples": ["C1", "C2"]},
        {"net": "GND", "part_type": "RESISTOR", "component_count": 100,
         "pin_count": 200, "examples": ["R1"]},
    ]
    monkeypatch.setattr(
        gt,
        "_run_cypher",
        _router(
            {
                "count(DISTINCT c) AS component_count,\n           count(p) AS pin_count\n": counts,
                "ORDER BY n.Name, c.RefDes, p.Number": detail,
                "collect(DISTINCT c.RefDes)[0..5] AS examples": agg,
            }
        ),
    )
    out = tools.query_graph(
        query_type="net_components", net_name_list=["SMALL", "GND", "NOPE"]
    )
    payload = json.loads(out.split("\n", 1)[1])
    nets = {item["net"]: item for item in payload["nets"]}
    assert nets["SMALL"]["aggregated"] is False
    assert len(nets["SMALL"]["components"]) == 2
    assert "truncated" not in nets["SMALL"]
    assert nets["GND"]["aggregated"] is True
    assert nets["GND"]["by_part_type"][0]["components"] == 400
    assert payload["not_found"] == ["NOPE"]
    assert payload["stats"] == {"components": 502, "pins": 902}


@pytest.mark.unit
def test_batch_capped_at_max_items(bound_project, monkeypatch):
    monkeypatch.setattr(gt, "_run_cypher", _router({"c.RefDes IN $refdes_list": []}))
    refdes = [f"U{i}" for i in range(query_engine.MAX_BATCH_ITEMS + 5)]
    payload = json.loads(
        tools.query_graph(query_type="component_nets", refdes_list=refdes).split("\n", 1)[1]
    )
    assert payload["count"] == query_engine.MAX_BATCH_ITEMS
    assert payload["input_truncated"] is True


# ---------------------------------------------------------------------------
# 3. neighborhood
# ---------------------------------------------------------------------------


def _neighborhood_router(extra_peer_rows=None, extra_volts=None):
    peer_rows = extra_peer_rows if extra_peer_rows is not None else PEER_ROWS
    volts = extra_volts if extra_volts is not None else [
        {"refdes": "C1", "volts": [12.0]},
        {"refdes": "C2", "volts": [12.0]},
        {"refdes": "L1", "volts": [12.0]},
    ]
    return _router(
        {
            "c.Model AS model, c.Value AS value\n        LIMIT 1": [
                {"refdes": "U1", "part_type": "PMIC", "model": "MPN_X", "value": "VAL_X"}
            ],
            "ORDER BY p.Number": [
                {"pin_number": row["pin_number"], "pin_type": row["pin_type"],
                 "net_name": row["net_name"], "voltage": row["voltage"],
                 "net_type": row["net_type"]}
                for row in CENTER_NETS
            ],
            "count(DISTINCT c) AS component_count": [
                {"net": "VIN_12V", "component_count": 3},
                {"net": "SW1", "component_count": 2},
                {"net": "FB1", "component_count": 1},
            ],
            "peer_total": peer_rows,
            "collect(DISTINCT pn.VoltageLevel) AS volts": volts,
            "RETURN DISTINCT c.RefDes AS refdes, n.Name AS net": [],
        }
    )


@pytest.mark.unit
def test_neighborhood_returns_center_nets_and_peers(bound_project, monkeypatch):
    monkeypatch.setattr(gt, "_run_cypher", _neighborhood_router())
    out = tools.query_graph(query_type="neighborhood", refdes="U1")
    payload = json.loads(out.split("\n", 1)[1])
    assert payload["found"] is True
    assert payload["center"]["mpn"] == "MPN_X"
    assert payload["center"]["voltage"] == [12.0]
    nets = {item["net"]: item for item in payload["nets"]}
    assert set(nets) == {"VIN_12V", "SW1", "FB1"}
    assert nets["VIN_12V"]["degree"] == 3
    assert nets["VIN_12V"]["peers"][0]["refdes"] == "C1"
    assert nets["VIN_12V"]["peers"][0]["voltage"] == [12.0]
    # 2 个 peer 是 VIN 的全部邻居，不算裁剪
    assert "peers_total" not in nets["VIN_12V"]
    assert payload["truncated"] is False


@pytest.mark.unit
def test_neighborhood_truncates_nets_and_pins(bound_project, monkeypatch):
    monkeypatch.setattr(gt, "_run_cypher", _neighborhood_router())
    out = tools.query_graph(
        query_type="neighborhood", refdes="U1", max_nets=2, max_pins=3
    )
    payload = json.loads(out.split("\n", 1)[1])
    assert payload["truncated"] is True
    assert payload["stats"]["pin_returned"] == 3
    assert payload["stats"]["net_returned"] == 2
    assert payload["stats"]["nets_clipped"] == 1
    assert len(payload["nets"]) == 2
    # 电源网络优先保留（VIN_12V 必须在被保留的两个里）
    assert "VIN_12V" in {item["net"] for item in payload["nets"]}

    out = tools.query_graph(
        query_type="neighborhood", refdes="U1", max_nets=3, max_pins=2
    )
    payload = json.loads(out.split("\n", 1)[1])
    assert payload["stats"]["pin_returned"] == 2
    assert payload["stats"].get("pins_clipped") == 1
    assert payload["truncated"] is True


@pytest.mark.unit
def test_neighborhood_marks_partial_peer_lists(bound_project, monkeypatch):
    peer_rows = [
        {"net": "VIN_12V", "peers": [{"refdes": "C1", "part_type": "CAPACITOR",
                                      "mpn": "X", "value": "1uF", "pins": ["1"]}],
         "peer_total": 18},
        {"net": "SW1", "peers": [], "peer_total": 1},
        {"net": "FB1", "peers": [], "peer_total": 0},
    ]
    monkeypatch.setattr(gt, "_run_cypher", _neighborhood_router(extra_peer_rows=peer_rows))
    payload = json.loads(
        tools.query_graph(query_type="neighborhood", refdes="U1").split("\n", 1)[1]
    )
    nets = {item["net"]: item for item in payload["nets"]}
    assert nets["VIN_12V"]["peers_total"] == 2  # degree 3 - center
    assert payload["truncated"] is True  # VIN 只给了 1 个，17 个被裁


@pytest.mark.unit
def test_neighborhood_missing_center(bound_project, monkeypatch):
    monkeypatch.setattr(gt, "_run_cypher", lambda *a, **k: [])
    payload = json.loads(
        tools.query_graph(query_type="neighborhood", refdes="U999").split("\n", 1)[1]
    )
    assert payload["found"] is False
    assert payload["truncated"] is False


@pytest.mark.unit
def test_neighborhood_clamps_depth(monkeypatch):
    calls = {}

    def fake(*args, **kwargs):
        return []

    monkeypatch.setattr(gt, "_run_cypher", fake)
    assert query_engine.clamp_int(9, 1, 3, 2) == 3
    assert query_engine.clamp_int(0, 1, 3, 2) == 1
    assert query_engine.clamp_int("abc", 1, 3, 2) == 2
    assert calls == {}


@pytest.mark.unit
def test_neighborhood_requires_refdes(bound_project):
    out = tools.query_graph(query_type="neighborhood")
    assert "| error] ValueError" in out


# ---------------------------------------------------------------------------
# 4. 预算裁剪
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fit_budget_trims_peers_but_keeps_valid_json():
    big = {
        "query_type": "neighborhood",
        "nets": [
            {"net": f"N{i}", "peers": [
                {"refdes": f"C{i}_{j}", "part_type": "CAPACITOR", "mpn": "M" * 40}
                for j in range(30)
            ]}
            for i in range(6)
        ],
        "stats": {},
        "truncated": False,
    }
    out = query_engine.fit_budget(big, 3000)
    assert out["truncated"] is True
    assert len(query_engine.pack(out)) <= 3000
    json.loads(query_engine.pack(out))  # 仍是合法 JSON
