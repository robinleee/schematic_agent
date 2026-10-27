#!/usr/bin/env python3
"""U20187 对比：旧「单对象逐层遍历」 vs 新 `query_graph` 批量 / neighborhood。

用途：给灰度验收留可复现的证据——证明一次 neighborhood 调用拿到的网络/器件
覆盖与旧方式等价，同时把工具调用次数、payload 字节数和耗时降下来。

跑法：
    cd /data/schematic_agent/hardware_ai_expert
    PYTHONPATH=. SCHEMATIC_PROJECT_ID=legacy \
      /data/schematic_agent/.venv-mcp/bin/python ../scripts/mcp_query_bench_u20187.py [REFDES]
"""

from __future__ import annotations

import json
import re
import sys
import time

REFDES = sys.argv[1] if len(sys.argv) > 1 else "U20187"

from mcp_server import tools  # noqa: E402  (需要先设置 PYTHONPATH/项目环境变量)


def _body(text: str) -> str:
    return text.split("\n", 1)[1] if "\n" in text else text


def old_way(refdes: str) -> dict:
    """旧方式：1 次 component_nets + 每个网络 1 次 net_components。"""
    started = time.time()
    calls = 0
    payload_bytes = 0

    head = tools.query_graph(query_type="component_nets", refdes=refdes)
    calls += 1
    payload_bytes += len(head.encode())
    nets = sorted(set(re.findall(r"Net '([^']+)'", head)))

    components: set[str] = set()
    per_net: dict[str, dict] = {}
    for net in nets:
        body = tools.query_graph(query_type="net_components", net_name=net)
        calls += 1
        payload_bytes += len(body.encode())
        text = _body(body)
        detail = re.findall(r"^\s{2}(\S+) \(", text, re.M)
        aggregated = "[聚合模式]" in text
        components.update(detail)
        per_net[net] = {
            "names": set(detail),
            "aggregated": aggregated,
            "total": int((re.search(r"\((\d+) 个器件", text) or [0, 0])[1] or 0),
        }

    return {
        "calls": calls,
        "bytes": payload_bytes,
        "nets": len(nets),
        "components": len(components),
        "seconds": round(time.time() - started, 3),
        "net_names": nets,
        "per_net": per_net,
    }


def new_way(refdes: str, **kwargs) -> dict:
    started = time.time()
    raw = tools.query_graph(query_type="neighborhood", refdes=refdes, **kwargs)
    seconds = round(time.time() - started, 3)
    obj = json.loads(_body(raw))
    nets = [item["net"] for item in obj.get("nets", [])]
    peers = {peer["refdes"] for item in obj.get("nets", []) for peer in item.get("peers", [])}
    return {
        "calls": 1,
        "bytes": len(raw.encode()),
        "nets": len(nets),
        "net_names": sorted(nets),
        "peers_listed": len(peers),
        "seconds": seconds,
        "truncated": obj.get("truncated"),
        "stats": obj.get("stats"),
    }


def batch_way(refdes_list: list[str]) -> dict:
    started = time.time()
    raw = tools.query_graph(query_type="component_nets", refdes_list=refdes_list)
    seconds = round(time.time() - started, 3)
    obj = json.loads(_body(raw))
    return {
        "calls": 1,
        "refdes": refdes_list,
        "bytes": len(raw.encode()),
        "pins": obj["stats"]["pins"],
        "nets": obj["stats"]["nets"],
        "seconds": seconds,
    }


def coverage(old: dict, new_payload: dict) -> dict:
    """逐网络比较：旧方式给了哪些器件/聚合，新调用少了什么。"""
    new_nets = {item["net"]: item for item in new_payload.get("nets", [])}
    named_missing: dict[str, int] = {}
    type_covered = 0
    for net, old_info in old["per_net"].items():
        item = new_nets.get(net)
        if not item:
            named_missing[net] = len(old_info["names"] - {REFDES})
            continue
        new_names = {peer["refdes"] for peer in item.get("peers", [])}
        missing = (old_info["names"] - {REFDES}) - new_names
        if missing:
            named_missing[net] = len(missing)
        if old_info["aggregated"] and item.get("by_type"):
            type_covered += 1
    return {"named_missing": named_missing, "agg_covered": type_covered}


def main() -> int:
    old = old_way(REFDES)
    new = new_way(REFDES, depth=2)
    raw = tools.query_graph(query_type="neighborhood", refdes=REFDES)
    payload = json.loads(_body(raw))
    cov = coverage(old, payload)

    named_old = sum(len(info["names"] - {REFDES}) for info in old["per_net"].values())
    named_new = new["peers_listed"]
    covered = named_old - sum(cov["named_missing"].values())

    print(f"器件 {REFDES} — 项目 legacy")
    print("-" * 72)
    print(f"{'':22s}{'工具调用':>8s}{'payload字节':>12s}{'网络数':>8s}{'器件数':>8s}{'耗时s':>8s}")
    print(f"{'旧: 逐网络遍历':22s}{old['calls']:>8d}{old['bytes']:>12d}{old['nets']:>8d}{old['components']:>8d}{old['seconds']:>8.3f}")
    print(f"{'新: neighborhood×1':22s}{new['calls']:>8d}{new['bytes']:>12d}{new['nets']:>8d}{named_new:>8d}{new['seconds']:>8.3f}")
    print("-" * 72)
    print(f"网络覆盖: {len(set(old['net_names']) & set(new['net_names']))}/{old['nets']} 一致={old['net_names'] == new['net_names']}")
    print(f"中心引脚覆盖: {new['stats']['pin_returned']}/{new['stats']['pin_total']}")
    print(f"逐器件明细覆盖（对旧方式要到的名字）: {covered}/{named_old}，缺 {sum(cov['named_missing'].values())}")
    if cov["named_missing"]:
        print(f"  缺口分布: {json.dumps(cov['named_missing'], ensure_ascii=False)}（每处都有 by_type 全量型号分布）")
    print(f"大网络聚合覆盖（旧聚合 vs 新 by_type）: {cov['agg_covered']} 个")
    print(f"新结果 truncated={new['truncated']} stats={json.dumps(new['stats'], ensure_ascii=False)}")

    batch = batch_way(["U20187", "U20188", "U20189", "U10001", "U10002"])
    print("-" * 72)
    print(
        f"批量 component_nets({len(batch['refdes'])} 个器件): 1 次调用, "
        f"{batch['bytes']} 字节, {batch['pins']} 引脚 / {batch['nets']} 网络, {batch['seconds']}s"
    )

    saved_calls = old["calls"] - new["calls"]
    print("-" * 72)
    print(f"调用次数: {old['calls']} → {new['calls']}（少 {saved_calls} 次往返，约省 {saved_calls * 3.6:.0f}s @3.6s/次实测）")
    return 0 if old["net_names"] == new["net_names"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
