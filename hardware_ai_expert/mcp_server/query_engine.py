"""批量 / 子图查询原语（供 `query_graph` 使用）。

存在理由：`agent_system.graph_tools` 的单对象工具（一次一个 refdes / 一个 net）
在故障诊断里迫使 Agent 逐层手工遍历，实测每次工具往返 ≈3.6s，20~70 次调用
就是 70~250s。这里把「一次查多个对象」「一次拿一层子图」做成单次调用。

约束：
- 只读 Cypher，且全部经 `graph_tools._run_cypher`（项目隔离、只读拦截、
  行数/超时上限走同一条路径，不绕过任何既有安全阀）。
- 每个结果集都有硬上限；被裁剪时显式给出 ``truncated`` 与统计数字，
  让模型知道「还有东西没返回」，而不是把缺失当成事实。
- 输出为紧凑 JSON（无重复字段说明），便于小上下文模型消费。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from agent_system import graph_tools as gt

# 单次调用最多处理的批量对象数（防止模型一次塞几百个）
MAX_BATCH_ITEMS = 50
# 批量查询的原始行上限
BULK_ROW_LIMIT = 2500
# 子图查询：邻居器件、邻居引脚、深度 3 的额外网络上限
MAX_PEERS = 200
MAX_PEER_PINS = 600
DEPTH3_NET_LIMIT = 240


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def norm_list(values: Optional[Iterable[Any]], cap: int = MAX_BATCH_ITEMS) -> tuple[list[str], bool]:
    """去重、去空、保序、限长。返回 (列表, 是否被截断)。"""
    out: list[str] = []
    seen: set[str] = set()
    clipped = False
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        if len(out) >= cap:
            clipped = True
            break
        seen.add(text)
        out.append(text)
    return out, clipped


def clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def pack(obj: dict) -> str:
    """紧凑 JSON（中文不转义，省字节）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _volts(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number not in out:
            out.append(number)
    return out


# ---------------------------------------------------------------------------
# 批量：多个器件的引脚-网络
# ---------------------------------------------------------------------------


def bulk_component_nets(refdes_list: list[str]) -> dict:
    """一次查多个器件的引脚-网络映射（每个器件结构同单值版本）。"""
    query = """
    MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
    WHERE c.RefDes IN $refdes_list AND c.project_id = $project_id
    RETURN c.RefDes AS refdes,
           p.Number AS pin_number,
           p.Type AS pin_type,
           n.Name AS net_name,
           n.VoltageLevel AS voltage,
           n.NetType AS net_type
    ORDER BY c.RefDes, p.Number
    LIMIT $limit
    """
    rows = gt._run_cypher(
        query,
        {"refdes_list": refdes_list, "limit": BULK_ROW_LIMIT + 1},
    )
    truncated = len(rows) > BULK_ROW_LIMIT
    if truncated:
        rows = rows[:BULK_ROW_LIMIT]

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("refdes")), []).append(row)

    components: list[dict] = []
    missing: list[str] = []
    for refdes in refdes_list:
        pins = grouped.get(refdes) or []
        if not pins:
            missing.append(refdes)
            components.append({"refdes": refdes, "found": False, "pin_count": 0, "net_count": 0, "pins": []})
            continue
        nets = {row.get("net_name") for row in pins}
        components.append(
            {
                "refdes": refdes,
                "found": True,
                "pin_count": len(pins),
                "net_count": len(nets),
                "pins": [
                    {
                        "pin": row.get("pin_number"),
                        "type": row.get("pin_type"),
                        "net": row.get("net_name"),
                        "v": row.get("voltage"),
                        "nt": row.get("net_type"),
                    }
                    for row in pins
                ],
            }
        )

    return {
        "query_type": "component_nets",
        "refdes_list": refdes_list,
        "count": len(refdes_list),
        "components": components,
        "not_found": missing,
        "truncated": truncated,
        "stats": {
            "pins": sum(item["pin_count"] for item in components),
            "nets": len({p["net"] for item in components for p in item["pins"]}),
        },
    }


# ---------------------------------------------------------------------------
# 批量：多个网络上的器件
# ---------------------------------------------------------------------------


def bulk_net_components(net_name_list: list[str], threshold: int = 100) -> dict:
    """一次查多个网络的连接器件；大网络按 PartType 聚合（与单值版本同策略）。"""
    count_query = """
    MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
    WHERE n.Name IN $net_name_list AND c.project_id = $project_id
    RETURN n.Name AS net,
           count(DISTINCT c) AS component_count,
           count(p) AS pin_count
    """
    count_rows = gt._run_cypher(count_query, {"net_name_list": net_name_list})
    counts = {str(row.get("net")): row for row in count_rows}

    detail_nets = [
        name
        for name in net_name_list
        if counts.get(name) and int(counts[name].get("component_count") or 0) <= threshold
    ]
    agg_nets = [
        name
        for name in net_name_list
        if counts.get(name) and int(counts[name].get("component_count") or 0) > threshold
    ]

    per_net_cap = threshold * 5
    detail_limit = max(1, min(BULK_ROW_LIMIT, per_net_cap * max(1, len(detail_nets))))
    detail_rows: list[dict] = []
    detail_truncated = False
    if detail_nets:
        detail_query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.Name IN $net_name_list AND c.project_id = $project_id
        RETURN n.Name AS net,
               c.RefDes AS refdes,
               c.PartType AS part_type,
               c.Value AS value,
               p.Number AS pin_number,
               p.Type AS pin_type
        ORDER BY n.Name, c.RefDes, p.Number
        LIMIT $limit
        """
        raw = gt._run_cypher(
            detail_query,
            {"net_name_list": detail_nets, "limit": detail_limit + 1},
        )
        detail_truncated = len(raw) > detail_limit
        detail_rows = raw[:detail_limit]

    detail_by_net: dict[str, list[dict]] = {}
    for row in detail_rows:
        detail_by_net.setdefault(str(row.get("net")), []).append(row)

    agg_rows: list[dict] = []
    if agg_nets:
        agg_query = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE n.Name IN $net_name_list AND c.project_id = $project_id
        RETURN n.Name AS net,
               c.PartType AS part_type,
               count(DISTINCT c) AS component_count,
               count(p) AS pin_count,
               collect(DISTINCT c.RefDes)[0..5] AS examples
        ORDER BY net, component_count DESC
        LIMIT $limit
        """
        agg_rows = gt._run_cypher(
            agg_query,
            {"net_name_list": agg_nets, "limit": BULK_ROW_LIMIT},
        )
    agg_by_net: dict[str, list[dict]] = {}
    for row in agg_rows:
        agg_by_net.setdefault(str(row.get("net")), []).append(row)

    nets: list[dict] = []
    missing: list[str] = []
    truncated_nets: list[str] = []
    for name in net_name_list:
        count_row = counts.get(name)
        if not count_row:
            missing.append(name)
            nets.append({"net": name, "found": False})
            continue
        item: dict[str, Any] = {
            "net": name,
            "found": True,
            "component_count": int(count_row.get("component_count") or 0),
            "pin_count": int(count_row.get("pin_count") or 0),
        }
        if name in agg_by_net:
            item["aggregated"] = True
            item["by_part_type"] = [
                {
                    "part_type": row.get("part_type"),
                    "components": int(row.get("component_count") or 0),
                    "pins": int(row.get("pin_count") or 0),
                    "examples": row.get("examples") or [],
                }
                for row in agg_by_net[name]
            ]
        else:
            rows = detail_by_net.get(name) or []
            item["aggregated"] = False
            item["components"] = [
                {
                    "refdes": row.get("refdes"),
                    "part_type": row.get("part_type"),
                    "value": row.get("value"),
                    "pin": row.get("pin_number"),
                    "type": row.get("pin_type"),
                }
                for row in rows
            ]
            if len(rows) < int(count_row.get("pin_count") or 0):
                item["truncated"] = True
                truncated_nets.append(name)
        nets.append(item)

    return {
        "query_type": "net_components",
        "net_name_list": net_name_list,
        "count": len(net_name_list),
        "nets": nets,
        "not_found": missing,
        "truncated": bool(detail_truncated or truncated_nets),
        "stats": {
            "components": sum(int(item.get("component_count") or 0) for item in nets),
            "pins": sum(int(item.get("pin_count") or 0) for item in nets),
        },
    }


# ---------------------------------------------------------------------------
# 子图：以器件为中心
# ---------------------------------------------------------------------------


def neighborhood(
    refdes: str,
    depth: int = 2,
    max_nets: int = 40,
    max_pins: int = 300,
    char_budget: int = 16000,
) -> dict:
    """以 refdes 为中心的子图：本器件引脚-网络 → 这些网络上的其它器件 → 器件关键属性。

    depth=1 只给网络与度数；depth=2 追加邻居器件属性（默认）；depth=3 再追加
    邻居器件的其它网络。任何一层超限都会裁剪并在 ``truncated`` 里说明。
    """
    depth = clamp_int(depth, 1, 3, 2)
    max_nets = clamp_int(max_nets, 1, 80, 40)
    max_pins = clamp_int(max_pins, 1, 600, 300)

    center_rows = gt._run_cypher(
        """
        MATCH (c:Component)
        WHERE c.RefDes = $refdes AND c.project_id = $project_id
        RETURN c.RefDes AS refdes, c.PartType AS part_type,
               c.Model AS model, c.Value AS value
        LIMIT 1
        """,
        {"refdes": refdes},
    )
    if not center_rows:
        return {
            "query_type": "neighborhood",
            "refdes": refdes,
            "found": False,
            "truncated": False,
        }
    center = center_rows[0]

    pin_rows = gt._run_cypher(
        """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE c.RefDes = $refdes AND c.project_id = $project_id
        RETURN p.Number AS pin_number, p.Type AS pin_type,
               n.Name AS net_name, n.VoltageLevel AS voltage, n.NetType AS net_type
        ORDER BY p.Number
        LIMIT $limit
        """,
        {"refdes": refdes, "limit": max_pins + 1},
    )
    pins_truncated = len(pin_rows) > max_pins
    pin_rows = pin_rows[:max_pins]

    pins = [
        {
            "pin": row.get("pin_number"),
            "type": row.get("pin_type"),
            "net": row.get("net_name"),
            "v": row.get("voltage"),
            "nt": row.get("net_type"),
        }
        for row in pin_rows
    ]

    all_nets: list[str] = []
    net_meta: dict[str, dict] = {}
    for row in pin_rows:
        name = row.get("net_name")
        if name is None:
            continue
        if name not in net_meta:
            net_meta[name] = {"v": row.get("voltage"), "nt": row.get("net_type")}
            all_nets.append(name)
    # 网络数超限时优先保留电源网络（诊断时最关键）
    ordered = sorted(
        all_nets,
        key=lambda name: 0 if (net_meta[name].get("nt") or "").upper() == "POWER" else 1,
    )
    kept_nets = ordered[:max_nets]
    nets_truncated = len(all_nets) > len(kept_nets)

    degrees: dict[str, int] = {}
    if kept_nets:
        degree_rows = gt._run_cypher(
            """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.Name IN $nets AND c.project_id = $project_id
            RETURN n.Name AS net, count(DISTINCT c) AS component_count
            """,
            {"nets": kept_nets},
        )
        degrees = {str(row.get("net")): int(row.get("component_count") or 0) for row in degree_rows}

    peers_by_net: dict[str, list[dict]] = {name: [] for name in kept_nets}
    peer_types_by_net: dict[str, dict[str, int]] = {}
    peers: list[str] = []
    peer_truncated = False
    # 每个网络最多带几个邻居：按剩余字符预算反推，保证每个网络都有代表，
    # 而不是让 GND 这类大网络吃光预算、把别的网络挤成空数组。
    per_net_cap = 0
    if depth >= 2 and kept_nets:
        # 每网络硬上限 12 个明细 peer（再多就靠 by_type 汇总）。预算够就用满 12，
        # 不够再按网络均分；最后还有 fit_budget 兑底。
        peer_budget = max(1, char_budget - 2500)
        peer_estimate = sum(min(12, max(0, degrees.get(name, 0) - 1)) for name in kept_nets)
        if peer_estimate * 110 <= peer_budget:
            per_net_cap = 12
        else:
            per_net_cap = max(
                2,
                min(
                    12,
                    (peer_budget - len(kept_nets) * 120) // max(1, len(kept_nets) * 110),
                ),
            )
        peer_rows = gt._run_cypher(
            """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.Name IN $nets AND c.project_id = $project_id AND c.RefDes <> $refdes
            WITH n.Name AS net, c.RefDes AS refdes, c.PartType AS part_type,
                 c.Model AS model, c.Value AS value, p.Number AS pin
            ORDER BY net, refdes, pin
            WITH net, refdes, part_type, model, value, collect(pin) AS pins
            WITH net, collect({refdes: refdes, part_type: part_type,
                               mpn: model, value: value,
                               pins: pins[0..6]})[0..$per_net] AS peers,
                 count(*) AS peer_total, collect(part_type) AS peer_types
            RETURN net, peers, peer_total, peer_types
            ORDER BY net
            LIMIT $limit
            """,
            {
                "nets": kept_nets,
                "refdes": refdes,
                "per_net": per_net_cap,
                "limit": MAX_PEERS + 1,
            },
        )
        for row in peer_rows:
            net = str(row.get("net"))
            items = [
                {
                    "refdes": peer.get("refdes"),
                    "part_type": peer.get("part_type"),
                    "mpn": peer.get("mpn"),
                    "value": peer.get("value"),
                    "pins": peer.get("pins") or [],
                }
                for peer in (row.get("peers") or [])
            ]
            peers_by_net[net] = items
            type_hist: dict[str, int] = {}
            for part_type in row.get("peer_types") or []:
                key = part_type or "Unknown"
                type_hist[key] = type_hist.get(key, 0) + 1
            if type_hist:
                peer_types_by_net[net] = type_hist
            for item in items:
                if item["refdes"] not in peers and len(peers) < MAX_PEERS:
                    peers.append(str(item["refdes"]))

    peer_totals: dict[str, int] = {}
    if depth >= 2 and kept_nets:
        peer_totals = {name: max(0, degrees.get(name, 0) - 1) for name in kept_nets}
        if any(
            peer_totals.get(name, 0) > len(peers_by_net.get(name) or [])
            for name in kept_nets
        ):
            peer_truncated = True

    peer_volts: dict[str, list[float]] = {}
    if depth >= 2 and peers:
        volt_rows = gt._run_cypher(
            """
            MATCH (c:Component)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(pn:Net)
            WHERE c.RefDes IN $peers AND c.project_id = $project_id
              AND pn.NetType = 'POWER' AND pn.VoltageLevel IS NOT NULL
            RETURN c.RefDes AS refdes, collect(DISTINCT pn.VoltageLevel) AS volts
            """,
            {"peers": peers[:MAX_PEERS]},
        )
        peer_volts = {str(row.get("refdes")): _volts(row.get("volts") or []) for row in volt_rows}
        for net in peers_by_net:
            for item in peers_by_net.get(net, []):
                item["voltage"] = peer_volts.get(item["refdes"], [])

    extra_nets: dict[str, list[str]] = {}
    if depth >= 3 and peers:
        extra_rows = gt._run_cypher(
            """
            MATCH (c:Component)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE c.RefDes IN $peers AND c.project_id = $project_id
            RETURN DISTINCT c.RefDes AS refdes, n.Name AS net
            ORDER BY refdes, net
            LIMIT $limit
            """,
            {"peers": peers[:MAX_PEERS], "limit": DEPTH3_NET_LIMIT + 1},
        )
        if len(extra_rows) > DEPTH3_NET_LIMIT:
            peer_truncated = True
            extra_rows = extra_rows[:DEPTH3_NET_LIMIT]
        for row in extra_rows:
            extra_nets.setdefault(str(row.get("refdes")), []).append(row.get("net"))

    center_volts = _volts(
        [meta.get("v") for meta in net_meta.values() if (meta.get("nt") or "").upper() == "POWER"]
    )

    nets_payload: list[dict] = []
    for name in kept_nets:
        item: dict[str, Any] = {
            "net": name,
            "v": net_meta.get(name, {}).get("v"),
            "nt": net_meta.get(name, {}).get("nt"),
            "degree": degrees.get(name, 0),
        }
        if depth >= 2:
            item["peers"] = peers_by_net.get(name, [])
            total = peer_totals.get(name, len(item["peers"]))
            if total > len(item["peers"]):
                item["peers_total"] = total
                # 明细被裁时给出全量的型号分布：模型仍能判断“这个网络上有哪些类型/多少个”
                item["by_type"] = dict(
                    sorted(
                        (peer_types_by_net.get(name) or {}).items(),
                        key=lambda kv: -kv[1],
                    )
                )
        nets_payload.append(item)

    if depth >= 3 and extra_nets:
        for net in nets_payload:
            for peer in net.get("peers", []):
                if peer["refdes"] in extra_nets:
                    peer["other_nets"] = extra_nets[peer["refdes"]][:20]

    result: dict[str, Any] = {
        "query_type": "neighborhood",
        "refdes": refdes,
        "found": True,
        "center": {
            "refdes": center.get("refdes"),
            "part_type": center.get("part_type"),
            "mpn": center.get("model"),
            "value": center.get("value"),
            "voltage": center_volts,
        },
        "depth": depth,
        "pins": pins if depth >= 1 else [],
        "nets": nets_payload,
        "stats": {
            "pin_total": len(pin_rows),
            "pin_returned": len(pins),
            "net_total": len(all_nets),
            "net_returned": len(kept_nets),
            "peers": len(peers),
            "peers_per_net_cap": per_net_cap,
        },
        "truncated": bool(pins_truncated or nets_truncated or peer_truncated),
    }
    if pins_truncated:
        result["stats"]["pins_clipped"] = 1
    if nets_truncated:
        result["stats"]["nets_clipped"] = len(all_nets) - len(kept_nets)
    if peer_truncated:
        result["stats"]["peers_clipped"] = True

    return fit_budget(result, char_budget)


def fit_budget(result: dict, char_budget: int) -> dict:
    """按字符预算裁剪邻居明细（从 peer 最多的网络开始削），并保持 JSON 合法。"""
    if char_budget <= 0 or len(pack(result)) <= char_budget:
        return result

    clipped = 0
    while len(pack(result)) > char_budget:
        nets = sorted(
            (net for net in result.get("nets", []) if net.get("peers")),
            key=lambda net: -len(net["peers"]),
        )
        if not nets:
            break
        victim = nets[0]
        # 每次削掉体积最大的那个网络的尾部 peer
        victim["peers"].pop()
        clipped += 1
        if not victim["peers"]:
            victim.pop("peers", None)

    if clipped:
        result["truncated"] = True
        result["stats"]["peers_trimmed_for_budget"] = clipped
    # 极端情况下仍超限：裁掉 nets 明细本身，只保统计，绝不让超长 payload 进上下文
    if len(pack(result)) > char_budget:
        result["nets"] = [
            {k: v for k, v in net.items() if k not in ("peers",)}
            for net in result.get("nets", [])
        ]
        result["truncated"] = True
        result["stats"]["nets_detail_dropped"] = True
    return result
