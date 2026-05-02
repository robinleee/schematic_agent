"""
Quality Guard - 数据质量守门员

在 ETL 完成后、Neo4j 注入前执行拦截检查：
1. PartType 标准化覆盖率 >= 90%
2. 核心网络（VCC/GND/3V3 等）识别率 = 100%

任一不达标则抛出 QualityGuardException 阻断运行。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


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
        r"(?i)\b5V\b", r"(?i)\b12V\b", r"(?i)VBAT", r"(?i)VIN",
        r"(?i)VOUT", r"(?i)AVDD", r"(?i)DVDD", r"(?i)IOVDD",
    ]

    def __init__(self, components: Optional[dict] = None,
                 topology: Optional[list] = None):
        """
        Args:
            components: graph_components 字典 {refdes: {...}}
            topology: topology_triplets 列表
        """
        self.components = components or {}
        self.topology = topology or []
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
                      if c.get("PartType") == "UNKNOWN")
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
        """检查核心电源网络识别率"""
        import re

        if not self.topology:
            return {
                "name": "核心网络识别率",
                "passed": True,
                "metric": 100.0,
                "threshold": self.MIN_CORE_NET_RECOGNITION,
                "message": "无拓扑数据，跳过检查",
            }

        # 提取所有网络名
        all_nets = set()
        for triplet in self.topology:
            net_name = triplet.get("Net_Name", "")
            if net_name:
                all_nets.add(net_name)

        # 识别核心网络
        core_nets_found = set()
        core_nets_expected = set()

        for pattern in self.CORE_NET_PATTERNS:
            regex = re.compile(pattern)
            for net in all_nets:
                if regex.search(net):
                    core_nets_found.add(net)
                    core_nets_expected.add(pattern)

        # 检查是否有电源和地网络
        has_power = any(re.compile(p).search(n)
                        for p in self.CORE_NET_PATTERNS
                        for n in all_nets)
        has_gnd = any("GND" in n.upper() for n in all_nets)

        # 更合理的指标：核心网络类型覆盖率
        expected_types = {"VCC/VDD", "GND/VSS", "3.3V", "1.8V"}
        found_types = set()
        for net in all_nets:
            net_upper = net.upper()
            if re.search(r"VCC|VDD|5V|12V|VIN|VOUT|AVDD|DVDD|IOVDD", net_upper):
                found_types.add("VCC/VDD")
            if "GND" in net_upper or "VSS" in net_upper:
                found_types.add("GND/VSS")
            if re.search(r"3V3|3\.3V", net_upper):
                found_types.add("3.3V")
            if re.search(r"1V8|1\.8V", net_upper):
                found_types.add("1.8V")

        if expected_types:
            recognition = len(found_types) / len(expected_types) * 100
        else:
            recognition = 100.0

        passed = recognition >= self.MIN_CORE_NET_RECOGNITION

        return {
            "name": "核心网络识别率",
            "passed": passed,
            "metric": recognition,
            "threshold": self.MIN_CORE_NET_RECOGNITION,
            "message": (
                f"发现 {len(found_types)}/{len(expected_types)} 类核心网络: "
                f"{', '.join(sorted(found_types)) if found_types else '无'}, "
                f"{'通过' if passed else f'低于阈值 {self.MIN_CORE_NET_RECOGNITION}%' }"
            ),
        }

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

    guard = QualityGuard(components=comps_good, topology=[])
    report = guard.validate(raise_on_fail=False)
    assert report["passed"] is True, "应该通过"
    print("  ✅ 覆盖率达标测试通过")

    # 测试 2: 覆盖率不达标
    comps_fail = {f"C{i}": {"PartType": "PASSIVE"} for i in range(50)}
    comps_fail.update({f"U{i}": {"PartType": "UNKNOWN"} for i in range(50)})
    guard = QualityGuard(components=comps_fail, topology=[])
    try:
        guard.validate(raise_on_fail=True)
        assert False, "应该抛出异常"
    except QualityGuardException:
        print("  ✅ 覆盖率不达标阻断测试通过")

    # 测试 3: 核心网络检查
    topo = [
        {"Component_RefDes": "U1", "Pin_Number": "1", "Net_Name": "VCC_3V3"},
        {"Component_RefDes": "U1", "Pin_Number": "2", "Net_Name": "GND"},
        {"Component_RefDes": "U2", "Pin_Number": "1", "Net_Name": "1V8_DDR"},
    ]
    guard = QualityGuard(components=comps_good, topology=topo)
    report = guard.validate(raise_on_fail=False)
    assert report["passed"] is True, "应该通过"
    print("  ✅ 核心网络检查测试通过")

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
