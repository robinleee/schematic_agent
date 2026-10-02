"""
Quality Guard - 数据质量守门员

在 ETL 完成后、Neo4j 注入前执行拦截检查：
1. PartType 标准化覆盖率 >= 90%
2. 核心网络（VCC/GND/3V3 等）识别率 = 100%（网络级校验）

任一不达标则抛出 QualityGuardException 阻断运行。

V5.1 变更: 核心网络识别从「类型级」（4 类电压各出现一次即 100%）
改为「网络级」（逐个核心网络校验连通性），修复审计发现的代理指标过宽问题。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


class QualityGuardException(Exception):
    """数据质量不达标异常，阻断后续流程"""
    pass


class QualityGuard:
    """数据质量守门员"""

    # PRD V5.0 规定的质量阈值
    MIN_PARTTYPE_COVERAGE = 90.0  # 百分比
    MIN_CORE_NET_RECOGNITION = 100.0  # 百分比

    # 核心电源网络名模式（不区分大小写，包含匹配）
    CORE_NET_PATTERNS = [
        r"(?i)VCC", r"(?i)GND", r"(?i)VDD", r"(?i)VSS",
        r"(?i)3V3", r"(?i)3\.3V", r"(?i)1V8", r"(?i)1\.8V",
        r"(?i)1V0", r"(?i)1V2", r"(?i)1V35", r"(?i)0V675",
        r"(?i)0V85", r"(?i)0V9", r"(?i)\b5V(?:0)?\b",
        r"(?i)\b12V(?:0)?\b", r"(?i)VBAT", r"(?i)VIN",
        r"(?i)VOUT", r"(?i)AVDD", r"(?i)DVDD", r"(?i)IOVDD",
    ]

    def __init__(self, components: Optional[dict] = None,
                 topology: Optional[list] = None,
                 component_models: Optional[dict] = None,
                 chip_library: Optional[dict] = None,
                 metadata: Optional[dict] = None):
        """
        Args:
            components: graph_components 字典 {refdes: {...}}
            topology: topology_triplets 列表
            component_models: 可选的 refdes/模型结构索引（兼容旧调用）
            chip_library: 可选的 pstchip 解析结果，用于引脚语义判断
            metadata: 可选的桥接元数据，如 refdes -> primitive
        """
        self.components = components or {}
        self.topology = topology or []
        self.component_models = component_models or {}
        self.chip_library = chip_library or {}
        self.metadata = metadata or {}
        self.report: dict = {}

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def validate(self, raise_on_fail: bool = True) -> dict:
        """
        执行质量检查

        Args:
            raise_on_fail: 不达标时是否抛出异常阻断

        Returns:
            检查报告字典
        """
        self.report = {
            "passed": True,
            "checks": [],
            "summary": {},
        }

        # 检查 1: PartType 标准化覆盖率
        pt_check = self._check_parttype_coverage()
        self.report["checks"].append(pt_check)
        if not pt_check["passed"]:
            self.report["passed"] = False

        # 检查 2: 核心网络识别率
        net_check = self._check_core_nets()
        self.report["checks"].append(net_check)
        if not net_check["passed"]:
            self.report["passed"] = False

        # 汇总
        self.report["summary"] = {
            "total_components": len(self.components),
            "total_triplets": len(self.topology),
            "passed": self.report["passed"],
        }

        if not self.report["passed"] and raise_on_fail:
            messages = [c["message"] for c in self.report["checks"] if not c["passed"]]
            raise QualityGuardException(
                f"[QualityGuard] 数据质量检查未通过:\n" + "\n".join(f"  - {m}" for m in messages)
            )

        return self.report

    def print_report(self):
        """打印检查报告"""
        if not self.report:
            print("[QualityGuard] 请先调用 validate()")
            return

        print("\n" + "=" * 60)
        print("Quality Guard 检查报告")
        print("=" * 60)

        for check in self.report["checks"]:
            status = "✅ PASS" if check["passed"] else "❌ FAIL"
            print(f"\n  [{status}] {check['name']}")
            print(f"    指标: {check['metric']:.1f}% (阈值: {check['threshold']:.1f}%)")
            print(f"    说明: {check['message']}")

        print(f"\n  总计: {'✅ 通过' if self.report['passed'] else '❌ 未通过'}")
        print(f"  器件数: {self.report['summary']['total_components']}")
        print(f"  拓扑数: {self.report['summary']['total_triplets']}")
        print("=" * 60)

    # --------------------------------------------------------
    # 具体检查项
    # --------------------------------------------------------

    def _check_parttype_coverage(self) -> dict:
        """检查 PartType 标准化覆盖率"""
        total = len(self.components)
        if total == 0:
            return {
                "name": "PartType 标准化覆盖率",
                "passed": False,
                "metric": 0.0,
                "threshold": self.MIN_PARTTYPE_COVERAGE,
                "message": "无器件数据",
            }

        unknown = sum(1 for c in self.components.values()
                      if not c.get("PartType") or c["PartType"] == "UNKNOWN")
        known = total - unknown
        coverage = known / total * 100

        passed = coverage >= self.MIN_PARTTYPE_COVERAGE

        return {
            "name": "PartType 标准化覆盖率",
            "passed": passed,
            "metric": coverage,
            "threshold": self.MIN_PARTTYPE_COVERAGE,
            "message": (
                f"覆盖率 {coverage:.1f}% ({known}/{total} 已知), "
                f"{'通过' if passed else f'低于阈值 {self.MIN_PARTTYPE_COVERAGE}%' }"
            ),
        }

    def _check_core_nets(self) -> dict:
        """
        检查核心电源网络识别率（网络级校验，V5.1）。

        V5.0 实现（类型级）：检查 4 类电压 {VCC/VDD, GND/VSS, 3.3V, 1.8V}
        各出现至少一次即判 100%，过于宽松——只要每种电压类型出现过一次就算通过，
        与「每个核心网络都被识别」完全不是一回事。

        V5.1 实现（网络级）：逐个枚举匹配 CORE_NET_PATTERNS 的具体网络名，
        校验每个核心网络均具有有效连通性（≥2 pin 连接，排除 stub/解析伪影）。
        recognition = 有效核心网络数 / 核心网络总数 × 100%
        """
        if not self.topology:
            return {
                "name": "核心网络识别率（网络级）",
                "passed": False,
                "metric": 0.0,
                "threshold": self.MIN_CORE_NET_RECOGNITION,
                "message": "无拓扑数据，无法验证核心网络",
            }

        # 1. 统计每个网络的 pin 连接数（从 topology triplets）
        net_pin_counts: dict[str, int] = {}
        for triplet in self.topology:
            net_name = triplet.get("Net_Name", "")
            if net_name:
                net_pin_counts[net_name] = net_pin_counts.get(net_name, 0) + 1

        # 2. 逐个枚举匹配核心网络模式的具体网络名（网络级，非类型级）
        core_nets: dict[str, int] = {}  # net_name -> pin_count
        for pattern in self.CORE_NET_PATTERNS:
            regex = re.compile(pattern)
            for net, pin_count in net_pin_counts.items():
                if regex.search(net) and net not in core_nets:
                    core_nets[net] = pin_count

        # 3. 网络级校验：每个核心网络须具有有效连通性（≥2 pin）
        #    单 pin 的"核心网络"通常是 stub 或解析伪影，不应计为已识别
        MIN_PINS_FOR_VALID_NET = 2
        recognized_nets = {}
        legitimate_single_pin_nets = {}
        for net, cnt in core_nets.items():
            if cnt >= MIN_PINS_FOR_VALID_NET:
                recognized_nets[net] = cnt
                continue
            if cnt == 1:
                evidence = self._recognize_single_pin_structure(net)
                if evidence:
                    recognized_nets[net] = cnt
                    legitimate_single_pin_nets[net] = evidence
        suspicious_nets = {
            net: cnt for net, cnt in core_nets.items()
            if cnt < MIN_PINS_FOR_VALID_NET and net not in legitimate_single_pin_nets
        }

        if core_nets:
            recognition = len(recognized_nets) / len(core_nets) * 100
        else:
            recognition = 0.0

        # 4. 硬性门槛：必须存在电源类和接地类核心网络（有效连通的）
        has_power = any(
            re.search(r"VCC|VDD|5V|12V|VIN|VOUT|AVDD|DVDD|IOVDD|VBAT", net.upper())
            for net in recognized_nets
        )
        has_ground = any(
            "GND" in net.upper() or "VSS" in net.upper()
            for net in recognized_nets
        )
        essential_ok = has_power and has_ground

        passed = recognition >= self.MIN_CORE_NET_RECOGNITION and essential_ok

        # 5. 构建透明报告（列出每个核心网络及其 pin 数）
        detail_lines = []
        for net in sorted(recognized_nets, key=lambda n: (-recognized_nets[n], n)):
            suffix = "，结构化单引脚合法结构" if net in legitimate_single_pin_nets else ""
            detail_lines.append(f"      ✅ {net} ({recognized_nets[net]} pins){suffix}")
        for net in sorted(suspicious_nets):
            detail_lines.append(f"      ⚠️  {net} ({suspicious_nets[net]} pin, 疑似 stub)")
        detail = "\n".join(detail_lines) if detail_lines else "      (无)"

        message_parts = [
            f"网络级校验: {len(recognized_nets)}/{len(core_nets)} 核心网络有效连通 (≥{MIN_PINS_FOR_VALID_NET} pins)",
            f"电源类={'有' if has_power else '无'}, 接地类={'有' if has_ground else '无'}",
            f"{'通过' if passed else '未通过'}",
        ]
        if suspicious_nets:
            message_parts.append(
                f"警告: {len(suspicious_nets)} 个核心网络连通性不足 (疑似 stub)"
            )

        return {
            "name": "核心网络识别率（网络级）",
            "passed": passed,
            "metric": recognition,
            "threshold": self.MIN_CORE_NET_RECOGNITION,
            "message": " | ".join(message_parts) + "\n" + detail,
            "structured_details": {
                "core_nets": dict(sorted(core_nets.items())),
                "recognized_nets": dict(sorted(recognized_nets.items())),
                "suspicious_nets": dict(sorted(suspicious_nets.items())),
                "legitimate_single_pin_nets": legitimate_single_pin_nets,
                "required_pin_count": MIN_PINS_FOR_VALID_NET,
                "fail_closed": True,
            },
        }

    def _recognize_single_pin_structure(self, net_name: str) -> Optional[dict]:
        """Recognize a real one-pin rail only from component topology and attributes.

        A singleton is accepted when it is one side of a two-terminal resistor and
        the other resistor side reaches a semantically identifiable IC pin:
        - a zero-ohm link to an enable/control pin; or
        - a 1 kOhm sensor link to an ADC-capable BMC pin or a named sensor input.

        No refdes or net-name allowlist is used.  Missing structure stays failed.
        """
        pins = [
            triplet for triplet in self.topology
            if triplet.get("Net_Name") == net_name
        ]
        if len(pins) != 1:
            return None
        resistor_ref = pins[0].get("Component_RefDes")
        resistor = self.components.get(resistor_ref, {})
        if not self._is_resistor(resistor):
            return None

        resistor_nets = self._nets_for_component(resistor_ref)
        if len(resistor_nets) != 2 or net_name not in resistor_nets:
            return None
        other_net = next(iter(resistor_nets - {net_name}))
        other_pins = [
            triplet for triplet in self.topology
            if triplet.get("Net_Name") == other_net
            and triplet.get("Component_RefDes") != resistor_ref
        ]
        if not other_pins:
            return None

        value_ohms = self._resistance_ohms(resistor.get("Value"))
        for endpoint in other_pins:
            endpoint_ref = endpoint.get("Component_RefDes")
            endpoint_comp = self.components.get(endpoint_ref, {})
            if self._is_passive(endpoint_comp):
                continue
            pin_semantics = self._pin_semantics(endpoint)
            if value_ohms == 0 and "EN" in pin_semantics:
                return {
                    "kind": "zero_ohm_control_link",
                    "resistor": resistor_ref,
                    "resistance_ohms": value_ohms,
                    "other_net": other_net,
                    "endpoint": endpoint_ref,
                    "pin": endpoint.get("Pin_Number"),
                    "pin_semantics": sorted(pin_semantics),
                }
            if value_ohms == 1000:
                adc_link = "ADC" in pin_semantics and self._has_bmc_identity(endpoint_comp)
                named_sensor_link = (
                    "SENSOR" in other_net.upper()
                    and self._has_sensor_endpoint(endpoint_comp)
                )
                if adc_link or named_sensor_link:
                    return {
                        "kind": "one_k_sensor_adc_link" if adc_link else "one_k_sensor_measurement_link",
                        "resistor": resistor_ref,
                        "resistance_ohms": value_ohms,
                        "other_net": other_net,
                        "endpoint": endpoint_ref,
                        "pin": endpoint.get("Pin_Number"),
                        "pin_semantics": sorted(pin_semantics),
                    }
        return None

    def _nets_for_component(self, refdes: str) -> set[str]:
        return {
            triplet.get("Net_Name")
            for triplet in self.topology
            if triplet.get("Component_RefDes") == refdes and triplet.get("Net_Name")
        }

    @staticmethod
    def _is_passive(component: dict) -> bool:
        return str(component.get("PartType", "")).upper() in {
            "PASSIVE", "RESISTOR", "CAPACITOR", "INDUCTOR"
        }

    @classmethod
    def _is_resistor(cls, component: dict) -> bool:
        part_type = str(component.get("PartType", "")).upper()
        model = str(component.get("Model", ""))
        return part_type == "RESISTOR" or (
            part_type == "PASSIVE" and (
                bool(re.search(r"(?i)(?:resistor|^res[_-]|^r\d)", model))
                or cls._resistance_ohms(component.get("Value")) is not None
            )
        )

    @staticmethod
    def _resistance_ohms(value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip().replace("Ω", "").replace("Ω", "").upper()
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMG]?)(?:OHM|R)?", text)
        if not match:
            return None
        multiplier = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}[match.group(2)]
        return float(match.group(1)) * multiplier

    def _pin_semantics(self, triplet: dict) -> set[str]:
        values = [
            triplet.get(key)
            for key in (
                "Pin_Name", "PinName", "pin_name", "Pin_Number",
                "Function", "function", "Role", "role",
            )
        ]
        refdes = triplet.get("Component_RefDes")
        pin_number = str(triplet.get("Pin_Number", ""))
        component = self.components.get(refdes, {})
        pin_maps = [
            component.get("Pins", {}),
            component.get("pin_map", {}),
        ]
        primitive = self.metadata.get("ref_to_prim", {}).get(refdes)
        library_part = self.chip_library.get(primitive, {})
        pin_maps.append(library_part.get("Pins", {}))
        for pin_map in pin_maps:
            if isinstance(pin_map, dict):
                for pin_key, pin_data in pin_map.items():
                    if (str(pin_key) == pin_number
                            or (isinstance(pin_data, dict)
                                and str(pin_data.get("PIN_NUMBER", "")) == pin_number)):
                        if isinstance(pin_data, dict):
                            values.extend(pin_data.get(key) for key in (
                                "Pin_Name", "PIN_NAME", "NAME", "Function", "FUNCTION",
                                "Role", "ROLE", "Signal", "SIGNAL",
                            ))
                        values.append(pin_key)
        text = " ".join(str(value) for value in values if value).upper()
        semantics = set()
        if re.search(r"(^|[^A-Z])EN(?:ABLE)?([^A-Z]|$)", text):
            semantics.add("EN")
        if re.search(r"\bADC(?:IN|\d+)?\b|ANALOG[_ ]?IN", text):
            semantics.add("ADC")
        return semantics

    @staticmethod
    def _has_bmc_identity(component: dict) -> bool:
        text = " ".join(str(component.get(key, "")) for key in (
            "Model", "MPN", "Description", "Manufacturer", "RawPartType"
        )).upper()
        return "BMC" in text or "BASEBOARD MANAGEMENT" in text

    @classmethod
    def _has_sensor_endpoint(cls, component: dict) -> bool:
        """Require a management/processing endpoint for named sensor rails."""
        text = " ".join(str(component.get(key, "")) for key in (
            "Model", "MPN", "Description", "PartType", "RawPartType"
        )).upper()
        return (
            cls._has_bmc_identity(component)
            or "MANAGEMENT" in text
            or "PROCESSOR" in text
            or str(component.get("PartType", "")).upper() in {"CPU", "MCU"}
        )

    # --------------------------------------------------------
    # 工厂方法
    # --------------------------------------------------------

    @classmethod
    def from_files(cls, components_file: str, topology_file: str) -> "QualityGuard":
        """从 JSON 文件加载数据创建 Guard"""
        comps = {}
        topo = []

        if Path(components_file).exists():
            with open(components_file, "r", encoding="utf-8") as f:
                comps = json.load(f)

        if Path(topology_file).exists():
            with open(topology_file, "r", encoding="utf-8") as f:
                topo = json.load(f)

        return cls(components=comps, topology=topo)


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("QualityGuard Self-test")
    print("=" * 60)

    # 测试 1: 覆盖率达标
    comps_pass = {
        "C1": {"PartType": "PASSIVE"},
        "R1": {"PartType": "PASSIVE"},
        "U1": {"PartType": "MCU"},
        "U2": {"PartType": "UNKNOWN"},  # 1/4 = 25% unknown, 75% known
    }
    # 需要更多数据才能达到 90%
    # 创建 100 个器件，10 个 UNKNOWN
    comps_good = {f"C{i}": {"PartType": "PASSIVE"} for i in range(90)}
    comps_bad = {f"U{i}": {"PartType": "UNKNOWN"} for i in range(10)}
    comps_good.update(comps_bad)

    baseline_topo = [
        {"Net_Name": net, "Component_RefDes": ref, "Pin_Number": pin}
        for net, pin in (("VCC_3V3", "1"), ("GND", "2"))
        for ref in ("C0", "C1")
    ]
    guard = QualityGuard(components=comps_good, topology=baseline_topo)
    report = guard.validate(raise_on_fail=False)
    assert report["passed"] is True, "应该通过"
    print("  ✅ 覆盖率达标测试通过")

    # 测试 2: 覆盖率不达标
    comps_fail = {f"C{i}": {"PartType": "PASSIVE"} for i in range(50)}
    comps_fail.update({f"U{i}": {"PartType": "UNKNOWN"} for i in range(50)})
    guard = QualityGuard(components=comps_fail, topology=baseline_topo)
    try:
        guard.validate(raise_on_fail=True)
        assert False, "应该抛出异常"
    except QualityGuardException:
        print("  ✅ 覆盖率不达标阻断测试通过")

    # 测试 3: 核心网络检查（网络级，每个核心网络需 ≥2 pin 有效连通）
    topo = [
        {"Component_RefDes": "U1", "Pin_Number": "1", "Net_Name": "VCC_3V3"},
        {"Component_RefDes": "U2", "Pin_Number": "1", "Net_Name": "VCC_3V3"},
        {"Component_RefDes": "U1", "Pin_Number": "2", "Net_Name": "GND"},
        {"Component_RefDes": "U2", "Pin_Number": "2", "Net_Name": "GND"},
        {"Component_RefDes": "U1", "Pin_Number": "3", "Net_Name": "1V8_DDR"},
        {"Component_RefDes": "U2", "Pin_Number": "3", "Net_Name": "1V8_DDR"},
    ]
    guard = QualityGuard(components=comps_good, topology=topo)
    report = guard.validate(raise_on_fail=False)
    assert report["passed"] is True, "应该通过（3 个核心网络均 ≥2 pin）"
    print("  ✅ 核心网络检查测试通过（网络级）")

    # 测试 3b: 核心网络 stub 检测（单 pin 网络应判定为未识别）
    topo_stub = [
        {"Component_RefDes": "U1", "Pin_Number": "1", "Net_Name": "VCC_3V3"},
        {"Component_RefDes": "U1", "Pin_Number": "2", "Net_Name": "VCC_3V3"},
        {"Component_RefDes": "U1", "Pin_Number": "3", "Net_Name": "GND"},  # 单 pin stub
    ]
    guard = QualityGuard(components=comps_good, topology=topo_stub)
    report = guard.validate(raise_on_fail=False)
    # GND 仅 1 pin → suspicious，且接地类无有效网络 → 应不通过
    assert report["passed"] is False, "单 pin 核心网络应判定为未通过"
    print("  ✅ 核心网络 stub 检测测试通过（网络级）")

    # 测试 4: 从文件加载
    guard = QualityGuard.from_files(
        "/data/schematic_agent/hardware_ai_expert/data/output/graph_components.json",
        "/data/schematic_agent/hardware_ai_expert/data/output/topology_triplets.json",
    )
    report = guard.validate(raise_on_fail=False)
    guard.print_report()

    print("\n✅ QualityGuard All tests passed")


if __name__ == "__main__":
    _run_tests()
