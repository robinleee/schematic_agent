"""
被动器件 MPN 解码器 — 从型号/描述字符串提取电气参数

支持：
  - Murata GRM/GRM_MLCC 系列电容
  - Samsung CL 系列电容
  - TDK C 系列电容
  - Yageo CC 系列电容
  - 通用电阻值解析（从描述字符串提取）

输出：标准化的参数字典，可直接写入 AMR 数据源或知识库

用法：
    from mpn_decoder import MPNDecoder
    decoder = MPNDecoder()
    result = decoder.decode("GRM155R71C104KA88D")
    # -> {"category": "capacitor", "capacitance": "0.1uF", "voltage_rating": "16V", ...}
"""

from __future__ import annotations

import re
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


# ============================================================
# 电容温度特性 → 材质等级
# ============================================================
TEMP_CHARACTERISTICS = {
    "X5R": {"temp_range": "-55~85°C", "delta": "±15%", "class": "Class II"},
    "X7R": {"temp_range": "-55~125°C", "delta": "±15%", "class": "Class II"},
    "X7S": {"temp_range": "-55~125°C", "delta": "±22%", "class": "Class II"},
    "Y5V": {"temp_range": "-30~85°C", "delta": "+22/-82%", "class": "Class III"},
    "C0G": {"temp_range": "-55~125°C", "delta": "±30ppm/°C", "class": "Class I"},
    "NP0": {"temp_range": "-55~125°C", "delta": "±30ppm/°C", "class": "Class I"},
    "X6S": {"temp_range": "-55~105°C", "delta": "±22%", "class": "Class II"},
    "X7T": {"temp_range": "-55~125°C", "delta": "+22/-33%", "class": "Class II"},
}

# ============================================================
# 电容容值编码（3位 EIA 代码）
# ============================================================
def decode_capacitance_code(code: str) -> Optional[str]:
    """解析 3 位容值代码，如 104 -> 0.1uF, 106 -> 10uF"""
    if not code or len(code) < 2:
        return None
    try:
        # 标准 3 位: 前两位是有效数字，第三位是 10 的幂
        if len(code) == 3 and code.isdigit():
            sig = int(code[:2])
            power = int(code[2])
            pf = sig * (10 ** power)
            return _pf_to_human(pf)
        # 4 位高精度: 前 3 位有效数字，第 4 位是幂
        if len(code) == 4 and code.isdigit():
            sig = int(code[:3])
            power = int(code[3])
            pf = sig * (10 ** power)
            return _pf_to_human(pf)
    except (ValueError, OverflowError):
        pass
    return None


def _pf_to_human(pf: float) -> str:
    """pF 转人类可读字符串"""
    if pf >= 1_000_000:
        val = pf / 1_000_000
        return f"{val:g}uF"
    elif pf >= 1_000:
        val = pf / 1_000
        return f"{val:g}nF"
    else:
        return f"{pf:g}pF"


# ============================================================
# 电容耐压编码（Murata/Samsung/TDK 字母代码）
# ============================================================
VOLTAGE_CODES_MURATA = {
    "0G": "4V", "0J": "6.3V", "1A": "10V", "1C": "16V", "1E": "25V",
    "1H": "50V", "2A": "100V", "2C": "160V", "2E": "250V", "YA": "4V",
    "YB": "6.3V", "YC": "10V", "YE": "16V", "0K": "16V",
    # 单字母简化
    "C": "16V", "E": "25V", "J": "6.3V", "A": "10V", "H": "50V",
}

VOLTAGE_CODES_SAMSUNG = {
    "3": "2.5V", "5": "6.3V", "6": "10V", "7": "16V", "8": "25V",
    "9": "50V", "A": "100V", "B": "4V", "C": "16V", "D": "2V",
    "E": "25V", "F": "3.15V", "G": "4V", "J": "6.3V", "K": "80V",
    "V": "35V", "W": "450V", "Y": "500V",
}

# ============================================================
# 封装编码
# ============================================================
PACKAGE_CODES = {
    "0402": {"metric": "1005", "imperial": "0402", "power": None},
    "0603": {"metric": "1608", "imperial": "0603", "power": "1/10W"},
    "0805": {"metric": "2012", "imperial": "0805", "power": "1/8W"},
    "1206": {"metric": "3216", "imperial": "1206", "power": "1/4W"},
    "1210": {"metric": "3225", "imperial": "1210", "power": "1/3W"},
    "1812": {"metric": "4532", "imperial": "1812", "power": "1/2W"},
    # Murata 尺寸编码
    "15": {"imperial": "0402", "metric": "1005"},
    "18": {"imperial": "0603", "metric": "1608"},
    "21": {"imperial": "0805", "metric": "2012"},
    "31": {"imperial": "1206", "metric": "3216"},
    "32": {"imperial": "1210", "metric": "3225"},
}

# ============================================================
# 电阻封装 → 额定功率映射
# ============================================================
RESISTOR_POWER_BY_PACKAGE = {
    "0201": "1/20W",
    "0402": "1/16W",
    "0603": "1/10W",
    "0805": "1/8W",
    "1206": "1/4W",
    "1210": "1/3W",
    "1812": "1/2W",
    "2010": "3/4W",
    "2512": "1W",
}


# ============================================================
# 解码结果数据类
# ============================================================
@dataclass
class DecodedComponent:
    category: str          # "capacitor" / "resistor" / "unknown"
    manufacturer: str      # "Murata" / "Samsung" / "TDK" / "Yageo" / "Generic"
    mpn: str              # 原始 MPN
    package: Optional[str] = None         # "0402"
    capacitance: Optional[str] = None     # "0.1uF"
    capacitance_pf: Optional[float] = None
    voltage_rating: Optional[str] = None  # "16V"
    voltage_rating_v: Optional[float] = None
    tolerance: Optional[str] = None       # "±10%"
    temp_characteristic: Optional[str] = None  # "X7R"
    temp_class: Optional[str] = None      # "Class II"
    resistance: Optional[str] = None      # "10K"
    resistance_ohm: Optional[float] = None
    power_rating: Optional[str] = None    # "1/16W"
    power_rating_w: Optional[float] = None
    inductance: Optional[str] = None      # "1.5uH"
    inductance_uh: Optional[float] = None
    current_rating: Optional[str] = None  # "500mA"
    current_rating_a: Optional[float] = None
    diode_type: Optional[str] = None      # "schottky"/"zener"/"tvs"/"general"/"led"
    led_color: Optional[str] = None       # "GRN"/"BLU"/"RED"
    frequency: Optional[str] = None       # "25MHz"
    frequency_hz: Optional[float] = None
    confidence: float = 0.0               # 0.0~1.0 解码置信度
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ============================================================
# MPN 解码器主体
# ============================================================
class MPNDecoder:
    """被动器件 MPN 解码器"""

    def decode(self, mpn: str) -> DecodedComponent:
        """解码 MPN，返回 DecodedComponent"""
        mpn = mpn.strip().upper()

        # 1. Murata MLCC (GRM / GRM_MLCC)
        if mpn.startswith("GRM"):
            return self._decode_murata_mlc(mpn)

        # 2. Samsung (CL)
        if mpn.startswith("CL"):
            return self._decode_samsung_cap(mpn)

        # 3. TDK (C 系列大写)
        if re.match(r"^C\d{4}", mpn):
            return self._decode_tdk_cap(mpn)

        # 4. Yageo (CC)
        if mpn.startswith("CC"):
            return self._decode_yageo_cap(mpn)

        # 5. 电阻型号 (RC / CRC / RL)
        if mpn.startswith(("RC", "CRC", "RL", "RK")):
            return self._decode_resistor_mpn(mpn)

        # 6. Ferrite bead / Inductor MPN prefixes
        if mpn.startswith(("BLM", "GZ", "HZ", "CBM", "MPZ", "NFM", "DLP")):
            return self._decode_ferrite_mpn(mpn)

        # 7. Inductor MPN prefixes (Murata LQH/LQM/MLZ, TDK TLP/MLF, Würth 7427)
        if mpn.startswith(("LQH", "LQM", "MLZ", "LQG", "DFE", "VLS", "SRN", "SRR", "SRU", "7427", "7440")):
            return self._decode_inductor_mpn(mpn)

        # 8. Diode MPN prefixes
        if mpn.startswith(("1N", "BAV", "BAS", "BAT", "BZX", "BZV", "MMBD", "MMBA", "SZ", "SM", "RS1", "US1", "MSS", "B05", "B13", "B54", "B58", "ESD", "RCL")):
            return self._decode_diode_mpn(mpn)

        # 9. LED MPN prefixes
        if mpn.startswith(("SML", "XZV", "598", "LTST", "KP", "APTD", "ACDA")):
            return self._decode_led_mpn(mpn)

        # 10. 通用 - 从描述字符串提取参数
        return self._decode_generic(mpn)

    # --------------------------------------------------------
    # Murata MLCC: GRM155R71C104KA88D
    #   GRM = MLCC SMD
    #   15 = 0402, 18 = 0603, 21 = 0805, 31 = 1206, 32 = 1210
    #   5 = thickness code
    #   R7 = X7R, 5C = C0G, 1C = X7S, R6 = X5R, 2E = X7T, 3U = Y5V
    #   1C = 16V (voltage code)
    #   104 = 0.1uF (capacitance)
    #   K = ±10% (tolerance)
    #   A88D = packaging/special
    # --------------------------------------------------------
    def _decode_murata_mlc(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="capacitor",
            manufacturer="Murata",
            mpn=mpn,
        )

        # 尺寸码 (2 digits after GRM)
        m = re.match(r"^GRM(\d{2})(\d)", mpn)
        if m:
            size_code = m.group(1)
            pkg = PACKAGE_CODES.get(size_code, {})
            result.package = pkg.get("imperial", f"size_{size_code}")

        # 温度特性
        temp_map = {
            "R7": "X7R", "5C": "C0G", "1C": "X7S", "R6": "X5R",
            "2E": "X7T", "3U": "Y5V", "6S": "X6S", "7U": "X7R",
            "B7": "X7R", "7R": "X7R", "F5": "X5R",
        }
        # 在 MPN 中找温度特性码
        for code, temp in temp_map.items():
            if code in mpn[6:10] if len(mpn) > 10 else "":
                result.temp_characteristic = temp
                tc_info = TEMP_CHARACTERISTICS.get(temp, {})
                result.temp_class = tc_info.get("class")
                break

        # 电压码（温度特性之后 1-2 字符）
        # 典型格式: GRM155R71C... → R7=温度, 1C=16V
        voltage_map_murata = {
            "0G": "4V", "0J": "6.3V", "1A": "10V", "1C": "16V",
            "1E": "25V", "1H": "50V", "2A": "100V",
        }
        for code, volt in voltage_map_murata.items():
            if code in mpn[6:12]:
                result.voltage_rating = volt
                result.voltage_rating_v = _parse_voltage(volt)
                break

        # 容值码（3-4 位数字）
        cap_match = re.search(r"(?<![A-Z])(\d{3,4})(?=[A-Z])", mpn)
        if cap_match:
            cap_str = decode_capacitance_code(cap_match.group(1))
            if cap_str:
                result.capacitance = cap_str
                result.capacitance_pf = _cap_str_to_pf(cap_str)

        # 精度码
        tol_map = {"K": "±10%", "M": "±20%", "J": "±5%", "B": "±0.1pF", "C": "±0.25pF", "D": "±0.5pF", "F": "±1%", "G": "±2%"}
        # 找容值码后面紧跟的字母
        if cap_match:
            after = mpn[cap_match.end():cap_match.end()+1]
            result.tolerance = tol_map.get(after)

        result.confidence = 0.7 if result.capacitance else 0.3
        if result.voltage_rating:
            result.confidence = min(1.0, result.confidence + 0.2)
        if result.temp_characteristic:
            result.confidence = min(1.0, result.confidence + 0.1)

        return result

    # --------------------------------------------------------
    # Samsung CL: CL05B104KO5NNNC
    #   CL = MLCC SMD
    #   05 = 0402, 10 = 0603, 21 = 0805, 31 = 1206
    #   B = thickness
    #   104 = 0.1uF
    #   K = ±10%
    #   O = voltage code (O=16V, 5=6.3V, 6=10V, 7=16V, 8=25V, 9=50V)
    # --------------------------------------------------------
    def _decode_samsung_cap(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="capacitor",
            manufacturer="Samsung",
            mpn=mpn,
        )

        # 尺寸
        size_map = {"03": "0201", "05": "0402", "10": "0603", "21": "0805", "31": "1206", "42": "1210"}
        if len(mpn) >= 4:
            result.package = size_map.get(mpn[2:4])

        # 容值
        cap_match = re.search(r"(?<![A-Z])(\d{3})(?=[A-Z])", mpn)
        if cap_match:
            cap_str = decode_capacitance_code(cap_match.group(1))
            if cap_str:
                result.capacitance = cap_str
                result.capacitance_pf = _cap_str_to_pf(cap_str)

        # 精度
        if cap_match and cap_match.end() < len(mpn):
            tol_map = {"K": "±10%", "M": "±20%", "J": "±5%", "B": "±0.1pF"}
            result.tolerance = tol_map.get(mpn[cap_match.end()])

        # 电压
        v_map = {"3": "2.5V", "5": "6.3V", "6": "10V", "7": "16V", "8": "25V", "9": "50V", "A": "100V", "O": "16V", "E": "25V"}
        # 电压码在精度码之后
        if cap_match and cap_match.end() + 1 < len(mpn):
            v_char = mpn[cap_match.end() + 1]
            result.voltage_rating = v_map.get(v_char)
            if result.voltage_rating:
                result.voltage_rating_v = _parse_voltage(result.voltage_rating)

        result.confidence = 0.7 if result.capacitance else 0.3
        return result

    # --------------------------------------------------------
    # TDK C 系列: C1005X5R1C104K050BC
    #   C = MLCC
    #   1005 = 0402 metric, 1608 = 0603, 2012 = 0805, 3216 = 1206
    #   X5R = 温度特性
    #   1C = 16V
    #   104 = 0.1uF
    #   K = ±10%
    # --------------------------------------------------------
    def _decode_tdk_cap(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="capacitor",
            manufacturer="TDK",
            mpn=mpn,
        )

        # 尺寸 (metric)
        metric_map = {"1005": "0402", "1608": "0603", "2012": "0805", "3216": "1206", "3225": "1210"}
        if len(mpn) >= 5:
            result.package = metric_map.get(mpn[1:5])

        # 温度特性
        for temp in ["C0G", "X7R", "X5R", "X7S", "X6S", "Y5V", "X7T"]:
            if temp in mpn:
                result.temp_characteristic = temp
                tc_info = TEMP_CHARACTERISTICS.get(temp, {})
                result.temp_class = tc_info.get("class")
                break

        # 电压
        for code, volt in VOLTAGE_CODES_MURATA.items():
            if code in mpn:
                result.voltage_rating = volt
                result.voltage_rating_v = _parse_voltage(volt)
                break

        # 容值
        cap_match = re.search(r"(?<![A-Z])(\d{3,4})(?=[A-Z0-9])", mpn)
        if cap_match:
            cap_str = decode_capacitance_code(cap_match.group(1))
            if cap_str:
                result.capacitance = cap_str
                result.capacitance_pf = _cap_str_to_pf(cap_str)

        result.confidence = 0.7 if result.capacitance else 0.3
        return result

    # --------------------------------------------------------
    # Yageo CC: CC0402KRX7R9BB104
    # --------------------------------------------------------
    def _decode_yageo_cap(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="capacitor",
            manufacturer="Yageo",
            mpn=mpn,
        )

        # 尺寸
        size_map = {"0201": "0201", "0402": "0402", "0603": "0603", "0805": "0805", "1206": "1206"}
        for code, pkg in size_map.items():
            if code in mpn:
                result.package = pkg
                break

        # 温度特性
        for temp in ["C0G", "X7R", "X5R", "Y5V"]:
            if temp in mpn:
                result.temp_characteristic = temp
                break

        # 容值（末尾 3-4 位数字）
        cap_match = re.search(r"(\d{3,4})$", mpn)
        if not cap_match:
            cap_match = re.search(r"(?<![A-Z])(\d{3,4})(?=[A-Z])", mpn)
        if cap_match:
            cap_str = decode_capacitance_code(cap_match.group(1))
            if cap_str:
                result.capacitance = cap_str
                result.capacitance_pf = _cap_str_to_pf(cap_str)

        result.confidence = 0.6 if result.capacitance else 0.2
        return result

    # --------------------------------------------------------
    # 电阻 MPN
    # --------------------------------------------------------
    def _decode_resistor_mpn(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="resistor",
            manufacturer="Yageo" if mpn.startswith("RC") else "Generic",
            mpn=mpn,
        )

        # 尺寸
        size_map = {"0201": "0201", "0402": "0402", "0603": "0603", "0805": "0805", "1206": "1206"}
        for code, pkg in size_map.items():
            if code in mpn:
                result.package = pkg
                result.power_rating = RESISTOR_POWER_BY_PACKAGE.get(pkg)
                if result.power_rating:
                    result.power_rating_w = _parse_power(result.power_rating)
                break

        result.confidence = 0.4
        return result

    # --------------------------------------------------------
    # Ferrite bead MPN 解码
    # Murata BLMxx, GZ/Hz series, etc.
    # --------------------------------------------------------
    def _decode_ferrite_mpn(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="ferrite_bead",
            manufacturer="Murata" if mpn.startswith(("BLM", "GZ", "HZ", "MPZ", "NFM", "DLP")) else "Generic",
            mpn=mpn,
        )

        # Package extraction from common patterns
        pkg_map = {
            "18": "0603", "21": "0805", "31": "1206", "32": "1210",
            "2A": "0805", "3A": "1206",
            "01": "0402", "15": "0402",
        }
        m = re.match(r"BLM(\d{2})", mpn)
        if m:
            result.package = pkg_map.get(m.group(1), f"size_{m.group(1)}")

        # Current rating from suffix
        if mpn.endswith(("H", "H7")):
            result.current_rating = "500mA"
            result.current_rating_a = 0.5
        elif mpn.endswith(("K", "K7")):
            result.current_rating = "1A"
            result.current_rating_a = 1.0
        elif mpn.endswith(("M", "M7")):
            result.current_rating = "2A"
            result.current_rating_a = 2.0

        result.notes = "Ferrite bead - impedance specified at 100MHz"
        result.confidence = 0.5
        return result

    # --------------------------------------------------------
    # Inductor MPN 解码
    # Murata LQH/LQM/MLZ series, etc.
    # --------------------------------------------------------
    def _decode_inductor_mpn(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="inductor",
            manufacturer="Murata" if mpn.startswith(("LQH", "LQM", "MLZ", "LQG", "DFE")) else "Generic",
            mpn=mpn,
        )

        # Package from Murata coding
        pkg_map = {
            "18": "0603", "21": "0805", "31": "1206", "32": "1210",
            "2M": "0805", "3M": "1206", "55": "2220",
        }
        m = re.match(r"(?:LQH|LQM|MLZ)(\d{2})", mpn)
        if m:
            result.package = pkg_map.get(m.group(1), f"size_{m.group(1)}")

        # Inductance from suffix
        ind_match = re.search(r"(\d+[RNM]?\d*)([KMU]?)(?:[_-]|$)", mpn)
        if ind_match:
            val_str = ind_match.group(1).replace('R', '.').replace('N', '.').replace('M', '.')
            unit_char = ind_match.group(2)
            try:
                val = float(val_str)
                if unit_char == 'N':
                    result.inductance = f"{val}nH"
                    result.inductance_uh = val / 1000
                elif unit_char == 'U' or not unit_char:
                    result.inductance = f"{val}uH"
                    result.inductance_uh = val
            except ValueError:
                pass

        result.confidence = 0.4
        return result

    # --------------------------------------------------------
    # Diode MPN 解码
    # --------------------------------------------------------
    def _decode_diode_mpn(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="diode",
            mpn=mpn,
        )

        mpn_upper = mpn.upper()

        # Diode type classification
        if mpn_upper.startswith(("1N4148", "MMBD", "MMBA")):
            result.diode_type = "general"
            result.manufacturer = "Generic"
        elif mpn_upper.startswith(("BAV", "BAS", "BAT")):
            result.diode_type = "general"
            result.manufacturer = "NXP"
        elif mpn_upper.startswith(("BZX", "BZV")):
            result.diode_type = "zener"
            result.manufacturer = "Generic"
            zv = re.search(r"(\d+)V(\d)", mpn_upper)
            if zv:
                result.voltage_rating = f"{zv.group(1)}.{zv.group(2)}V"
                result.voltage_rating_v = float(f"{zv.group(1)}.{zv.group(2)}")
        elif mpn_upper.startswith(("SZ", "SM3", "SM0", "SM1", "SM5", "SM7", "SM8", "SM9")) or "TVS" in mpn_upper or mpn_upper.startswith("RCL"):
            result.diode_type = "tvs"
            result.manufacturer = "Littelfuse" if mpn_upper.startswith("SM") else "Generic"
            tv = re.search(r"S(\d{2,3})", mpn_upper)
            if tv:
                v = int(tv.group(1))
                if 3 <= v <= 600:
                    result.voltage_rating = f"{v}V"
                    result.voltage_rating_v = float(v)
        elif mpn_upper.startswith(("B05", "B13", "B54", "B58", "MSS", "US1", "RS1")):
            result.diode_type = "schottky"
            result.manufacturer = "Diodes Inc" if mpn_upper.startswith(("B05", "B54", "B58")) else "Generic"
        elif mpn_upper.startswith("ESD"):
            result.diode_type = "tvs"
            result.manufacturer = "Generic"
        else:
            result.diode_type = "general"
            result.manufacturer = "Generic"

        # Package detection
        pkg_patterns = [
            (r"SOD[-_]?323", "SOD-323"),
            (r"SOD[-_]?123", "SOD-123"),
            (r"SOD[-_]?523", "SOD-523"),
            (r"SOD[-_]?923", "SOD-923"),
            (r"SOT[-_]?23", "SOT-23"),
            (r"SOT[-_]?723", "SOT-723"),
            (r"SOT[-_]?563", "SOT-563"),
            (r"DO[-_]?214", "DO-214AB"),
            (r"DO[-_]?219", "DO-219AD"),
            (r"DFN", "DFN"),
        ]
        for pat, pkg in pkg_patterns:
            if re.search(pat, mpn_upper):
                result.package = pkg
                break

        result.confidence = 0.5 if result.diode_type != "general" else 0.3
        return result

    # --------------------------------------------------------
    # LED MPN 解码
    # --------------------------------------------------------
    def _decode_led_mpn(self, mpn: str) -> DecodedComponent:
        result = DecodedComponent(
            category="led",
            diode_type="led",
            manufacturer="Generic",
            mpn=mpn,
        )

        mpn_upper = mpn.upper()
        if mpn_upper.startswith("SML"):
            result.manufacturer = "Rohm"
        elif mpn_upper.startswith("598"):
            result.manufacturer = "Broadcom"
        elif mpn_upper.startswith("LTST"):
            result.manufacturer = "Lite-On"
        elif mpn_upper.startswith("XZV"):
            result.manufacturer = "SunLED"

        # Package
        if "0402" in mpn_upper or "1005" in mpn_upper:
            result.package = "0402"
        elif "0603" in mpn_upper or "1608" in mpn_upper:
            result.package = "0603"
        elif "0805" in mpn_upper or "2012" in mpn_upper:
            result.package = "0805"

        result.confidence = 0.4
        return result

    # --------------------------------------------------------
    # 通用解码 - 从描述字符串提取参数
    # --------------------------------------------------------
    def _decode_generic(self, text: str) -> DecodedComponent:
        result = DecodedComponent(
            category="unknown",
            manufacturer="Generic",
            mpn=text,
        )

        # 检测是否为电容描述
        if re.search(r"CAP|CAPACITOR|MLCC", text, re.IGNORECASE):
            result.category = "capacitor"

            # 提取容值: 0.1UF, 10UF, 100NF, 22UF, 1000PF
            cap_match = re.search(r"(\d+\.?\d*)\s*(UF|μF|NF|PF|PF)\b", text, re.IGNORECASE)
            if cap_match:
                result.capacitance = f"{cap_match.group(1)}{cap_match.group(2).upper()}"
                # 转标准单位
                val = float(cap_match.group(1))
                unit = cap_match.group(2).upper()
                if unit == "UF":
                    result.capacitance_pf = val * 1_000_000
                elif unit == "NF":
                    result.capacitance_pf = val * 1_000
                elif unit == "PF":
                    result.capacitance_pf = val

            # 提取电压: 16V, 25V, 10V, 6.3V
            v_match = re.search(r"(\d+\.?\d*)\s*V\b", text)
            if v_match and float(v_match.group(1)) <= 500:
                result.voltage_rating = f"{v_match.group(1)}V"
                result.voltage_rating_v = float(v_match.group(1))

            # 封装
            pkg_match = re.search(r"(0201|0402|0603|0805|1206|1210|1812)", text)
            if pkg_match:
                result.package = pkg_match.group(1)

        # 检测是否为电阻描述
        elif re.search(r"RES|RESISTOR", text, re.IGNORECASE):
            result.category = "resistor"

            # 提取阻值: 10K, 4.7K, 100K, 33R, 1K
            r_match = re.search(r"(\d+\.?\d*)\s*(K|M|R|OHM)\b", text, re.IGNORECASE)
            if r_match:
                val = float(r_match.group(1))
                unit = r_match.group(2).upper()
                if unit == "K":
                    result.resistance = f"{val}K"
                    result.resistance_ohm = val * 1000
                elif unit == "M":
                    result.resistance = f"{val}M"
                    result.resistance_ohm = val * 1_000_000
                elif unit in ("R", "OHM"):
                    result.resistance = f"{val}Ω"
                    result.resistance_ohm = val

            # 封装 → 功率
            pkg_match = re.search(r"(0201|0402|0603|0805|1206|1210|1812|2010|2512)", text)
            if pkg_match:
                result.package = pkg_match.group(1)
                result.power_rating = RESISTOR_POWER_BY_PACKAGE.get(result.package)
                if result.power_rating:
                    result.power_rating_w = _parse_power(result.power_rating)

        result.confidence = 0.5 if result.category != "unknown" else 0.1
        return result

    # --------------------------------------------------------
    # 批量解码 Neo4j 中的器件描述
    # --------------------------------------------------------
    def decode_neo4j_description(self, desc: str, part_type: str = "") -> DecodedComponent:
        """解码 Neo4j Component 的 Model/描述字段

        Neo4j 中的电容型号格式如:
          CAP_C0402_DISCRETE_0.1UF_110-0014
          CAP_SMX0402C_DISCRETE_10UF_110-
          RES_R0402_DISCRETE_4.7K_100-002

        从中提取: 封装、容值/阻值等
        """
        result = DecodedComponent(
            category="unknown",
            manufacturer="Generic",
            mpn=desc,
        )

        # 判断类型
        desc_upper = desc.upper()
        if "CAP" in desc_upper or part_type == "CAPACITOR":
            result.category = "capacitor"
        elif "RES" in desc_upper or part_type == "RESISTOR":
            result.category = "resistor"
        elif part_type == "PASSIVE" or "IND_FB" in desc_upper or "FERRITE" in desc_upper or "FB" in desc_upper[:10]:
            result.category = "ferrite_bead"
        elif part_type == "INDUCTOR" or "IND_" in desc_upper or "INDITG" in desc_upper or "IND_CMC" in desc_upper:
            result.category = "inductor"
        elif part_type == "DIODE" or desc_upper.startswith("DIODE"):
            result.category = "diode"
            # Sub-classify diode type from model string
            if "TVS" in desc_upper:
                result.diode_type = "tvs"
            elif "SCHOTTKY" in desc_upper:
                result.diode_type = "schottky"
            elif "ZENER" in desc_upper:
                result.diode_type = "zener"
            else:
                result.diode_type = "general"
        elif part_type == "LED" or desc_upper.startswith("LED"):
            result.category = "led"
            result.diode_type = "led"
            # Color
            if "GRN" in desc_upper or "GREEN" in desc_upper:
                result.led_color = "GRN"
            elif "BLU" in desc_upper or "BLUE" in desc_upper:
                result.led_color = "BLU"
            elif "RED" in desc_upper:
                result.led_color = "RED"
            elif "YEL" in desc_upper or "AMBER" in desc_upper:
                result.led_color = "YEL"
        elif part_type == "CRYSTAL" or "XTAL" in desc_upper or "CRYSTAL" in desc_upper or "OSC_" in desc_upper or "TCXO" in desc_upper:
            result.category = "crystal"
            # Frequency
            freq_match = re.search(r"(\d+\.?\d*)\s*(MHZ|KHZ)", desc_upper)
            if freq_match:
                result.frequency = f"{freq_match.group(1)}{freq_match.group(2)}"
                fval = float(freq_match.group(1))
                result.frequency_hz = fval * 1e6 if freq_match.group(2) == "MHZ" else fval * 1e3
        elif part_type == "MOSFET" or "MOSFET" in desc_upper:
            result.category = "mosfet"
        elif part_type == "TRANSISTOR" or "BJT" in desc_upper or "NPN" in desc_upper or "PNP" in desc_upper:
            result.category = "transistor"

        # 提取封装 (C0402, R0402, C0603, C0805, SMX0402, SMC1206, C7343 等)
        pkg_patterns = [
            r"[CR](0201|0402|0603|0805|1206|1210|1812|2010|2512)",
            r"SM[CXR](0201|0402|0603|0805|1206|1210)",
            r"SMC(2626|3018|7343)",  # tantalum
            r"C(7343|2626|3018)",     # tantalum without prefix
            r"PPG_C(0201|0402|0603)",
        ]
        for pat in pkg_patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                result.package = m.group(1)
                if result.category == "resistor":
                    result.power_rating = RESISTOR_POWER_BY_PACKAGE.get(result.package)
                    if result.power_rating:
                        result.power_rating_w = _parse_power(result.power_rating)
                break

        # 提取容值
        if result.category == "capacitor":
            # 匹配: 0.1UF, 10UF, 22UF, 1UF, 100NF, 10NF, 1000PF, 22 UF, 0.47 F
            # Neo4j format: DISCRETE_0.1UF_ or DISCRETE_22 UF_ or DISCRETE_0.47 F_
            cap_match = re.search(r"(\d+\.?\d*)\s*(UF|μF|F|NF|PF)(?:[_\s]|$)", desc, re.IGNORECASE)
            if cap_match:
                val = cap_match.group(1)
                unit = cap_match.group(2).upper()
                # Normalize bare F to UF
                if unit == 'F' and float(val) < 1:
                    unit = 'UF'
                result.capacitance = f"{val}{unit}"
                fval = float(val)
                if unit in ("UF", "F"):
                    result.capacitance_pf = fval * 1_000_000
                elif unit == "NF":
                    result.capacitance_pf = fval * 1_000
                elif unit == "PF":
                    result.capacitance_pf = fval
            
            # Fallback: match 0.1U_ format (missing F)
            if not result.capacitance:
                cap_match2 = re.search(r"(\d+\.?\d*)\s*U(?:[_\s]|$)", desc, re.IGNORECASE)
                if cap_match2:
                    val = cap_match2.group(1)
                    result.capacitance = f"{val}UF"
                    result.capacitance_pf = float(val) * 1_000_000

        # 提取阻值
        if result.category == "resistor":
            # Neo4j format: DISCRETE_4.7K_ or DISCRETE_10K_ or DISCRETE_0_ or DISCRETE_49.9_
            r_match = re.search(r"DISCRETE_(\d+\.?\d*)\s*([KM]?)(?:[_\s]|$)", desc, re.IGNORECASE)
            if r_match:
                val = float(r_match.group(1))
                unit = r_match.group(2).upper()
                if unit == "K":
                    result.resistance = f"{val}K"
                    result.resistance_ohm = val * 1000
                elif unit == "M":
                    result.resistance = f"{val}M"
                    result.resistance_ohm = val * 1_000_000
                else:
                    result.resistance = f"{val}Ω"
                    result.resistance_ohm = val

        # Ferrite bead: extract impedance @ 100MHz
        if result.category == "ferrite_bead":
            # Package: FB0402, FB0603, FB0805, FB1206, SFB0805
            fb_pkg = re.search(r"(?:FB|SFB)(0402|0603|0805|1206|1210)", desc_upper)
            if fb_pkg:
                result.package = fb_pkg.group(1)
            else:
                # Try IND_FB format
                fb_pkg2 = re.search(r"(0402|0603|0805|1206|1210)", desc_upper)
                if fb_pkg2:
                    result.package = fb_pkg2.group(1)

            # Impedance: 120OHMS@100MHZ, 100 OHMS @ 100MHZ, 22 OHMS @ 100
            imp_match = re.search(r"(\d+\.?\d*)\s*(?:OHMS?|Ω)\s*@\s*(\d+)\s*(?:MHZ|MHZ)?", desc, re.IGNORECASE)
            if imp_match:
                result.resistance = f"{imp_match.group(1)}Ω@{imp_match.group(2)}MHz"
                result.resistance_ohm = float(imp_match.group(1))
                result.notes = f"Impedance {imp_match.group(1)}Ω at {imp_match.group(2)}MHz"

        # Inductor: extract inductance value
        if result.category == "inductor":
            # Package
            ind_pkg = re.search(r"(0402|0603|0805|1206|1210)", desc_upper)
            if ind_pkg:
                result.package = ind_pkg.group(1)

            # Inductance: 1.5UH, 0.1UH, 200UH, 680NH, 68NH, 0.56UH
            ind_match = re.search(r"(\d+\.?\d*)\s*(UH|NH|MH)(?:[_\s]|$)", desc, re.IGNORECASE)
            if ind_match:
                val = float(ind_match.group(1))
                unit = ind_match.group(2).upper()
                result.inductance = f"{val}{unit}"
                if unit == "UH":
                    result.inductance_uh = val
                elif unit == "NH":
                    result.inductance_uh = val / 1000
                elif unit == "MH":
                    result.inductance_uh = val * 1000

        # Diode: extract package
        if result.category == "diode":
            diode_pkgs = [
                (r"SOD[-_]?323", "SOD-323"), (r"SOD[-_]?123", "SOD-123"),
                (r"SOD[-_]?523", "SOD-523"), (r"SOD[-_]?923", "SOD-923"),
                (r"SOT[-_]?23", "SOT-23"), (r"SOT[-_]?723", "SOT-723"),
                (r"SOT[-_]?563", "SOT-563"), (r"DO[-_]?214", "DO-214AB"),
                (r"DO[-_]?219", "DO-219AD"), (r"DFN", "DFN"),
            ]
            for pat, pkg in diode_pkgs:
                if re.search(pat, desc_upper):
                    result.package = pkg
                    break

        # LED: extract package and color
        if result.category == "led":
            led_pkg = re.search(r"(0402|0603|0805|1206|1005|1608|2012)", desc_upper)
            if led_pkg:
                result.package = led_pkg.group(1)

        # Crystal: package
        if result.category == "crystal":
            xtal_pkg = re.search(r"(3225|2520|2016|1612)", desc_upper)
            if xtal_pkg:
                result.package = xtal_pkg.group(1)

        has_params = (result.capacitance or result.resistance or result.inductance
                      or result.frequency or result.diode_type
                      or result.category in ("ferrite_bead", "crystal", "mosfet", "transistor"))
        result.confidence = 0.8 if has_params else 0.3
        return result


# ============================================================
# 辅助函数
# ============================================================
def _parse_voltage(v_str: str) -> Optional[float]:
    """电压字符串转 float: '16V' -> 16.0"""
    m = re.match(r"(\d+\.?\d*)", v_str)
    return float(m.group(1)) if m else None


def _parse_power(p_str: str) -> Optional[float]:
    """功率字符串转 float: '1/16W' -> 0.0625"""
    m = re.match(r"(\d+)/(\d+)W", p_str)
    if m:
        return float(m.group(1)) / float(m.group(2))
    m = re.match(r"(\d+\.?\d*)W", p_str)
    return float(m.group(1)) if m else None


def _cap_str_to_pf(cap_str: str) -> Optional[float]:
    """容值字符串转 pF: '0.1uF' -> 100000"""
    m = re.match(r"(\d+\.?\d*)\s*(UF|μF|NF|PF)", cap_str, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ("UF", "ΜF"):
        return val * 1_000_000
    elif unit == "NF":
        return val * 1_000
    elif unit == "PF":
        return val
    return None


# ============================================================
# AMR 数据生成器 — 从解码结果生成 amr_data.yaml 兼容格式
# ============================================================
class AMRDataGenerator:
    """从 MPN 解码结果生成 AMR 降额数据"""

    def _infer_cap_voltage(self, package: str, capacitance_pf: float) -> Optional[float]:
        """根据封装和容值推断电容耐压"""
        for (pkg, (lo, hi)), v in self.CAP_PACKAGE_VOLTAGE.items():
            if pkg == package and lo <= capacitance_pf < hi:
                return v
        # 默认：0402/0603 -> 16V, 0805/1206 -> 25V
        defaults = {"0402": 16, "0603": 16, "0805": 25, "1206": 25, "1210": 25}
        return defaults.get(package)

    # 电阻封装 → 额定功率 (W)
    RESISTOR_POWER = {
        "0402": 1/16, "0603": 1/10, "0805": 1/8,
        "1206": 1/4, "1210": 1/3, "1812": 1/2,
        "2010": 3/4, "2512": 1.0,
    }

    # 电容温度等级 → 推荐降额系数
    CAP_DERATING_FACTOR = {
        "Class I": 0.5,   # C0G/NP0: 50% 降额
        "Class II": 0.5,  # X7R/X5R: 50% 降额
        "Class III": 0.5, # Y5V: 50% 降额
        None: 0.5,        # 未知: 50% 降额
    }

    # 电容封装 → 默认最大耐压 (V)
    # 基于 MLCC 通用规格：同一封装容值越大耐压越低
    CAP_PACKAGE_VOLTAGE = {
        # (package, capacitance_pf_range) -> voltage_rating_V
        # 0201
        ("0201", (0, 100000)): 25,       # <=0.1uF: 25V (C0G)
        ("0201", (100000, 1000000)): 10, # 0.1~1uF: 10V
        ("0201", (1000000, 1e9)): 6.3,  # >1uF: rare
        # 0402
        ("0402", (0, 100000)): 16,       # <=0.1uF: 16V
        ("0402", (100000, 1000000)): 10, # 0.1~1uF: 10V
        ("0402", (1000000, 1e9)): 6.3,   # >1uF: 6.3V
        # 0603
        ("0603", (0, 100000)): 25,
        ("0603", (100000, 1000000)): 16,
        ("0603", (1000000, 1e9)): 10,
        # 0805
        ("0805", (0, 100000)): 50,
        ("0805", (100000, 1000000)): 25,
        ("0805", (1000000, 22000000)): 16,
        ("0805", (22000000, 1e9)): 10,
        # 1206
        ("1206", (0, 100000)): 50,
        ("1206", (100000, 1000000)): 25,
        ("1206", (1000000, 1e9)): 16,
        # 1210
        ("1210", (0, 1000000)): 25,
        ("1210", (1000000, 1e9)): 16,
        # 1812
        ("1812", (0, 1e9)): 25,
        # 7343 (tantalum)
        ("7343", (0, 1e9)): 10,
        # 2626 (tantalum)
        ("2626", (0, 1e9)): 10,
        # 3018 (tantalum)
        ("3018", (0, 1e9)): 10,
    }

    def generate_amr_entry(self, decoded: DecodedComponent) -> Optional[Dict]:
        """生成单个 AMR 条目"""
        if decoded.category == "capacitor":
            # 优先使用解码的电压，否则用封装+容值推断
            v_rating = decoded.voltage_rating_v
            if not v_rating and decoded.package and decoded.capacitance_pf is not None:
                v_rating = self._infer_cap_voltage(decoded.package, decoded.capacitance_pf)
            
            if v_rating:
                derating = self.CAP_DERATING_FACTOR.get(decoded.temp_class, 0.5)
                return {
                    "category": "capacitor",
                    "mpn_pattern": decoded.mpn,
                    "capacitance": decoded.capacitance,
                    "capacitance_pf": decoded.capacitance_pf,
                    "voltage_rating_V": v_rating,
                    "derating_factor": derating,
                    "max_operating_voltage_V": round(v_rating * derating, 2),
                    "package": decoded.package,
                    "temp_characteristic": decoded.temp_characteristic,
                    "source": "mpn_decoder",
                    "voltage_source": "decoded" if decoded.voltage_rating_v else "inferred_from_package",
                    "confidence": decoded.confidence if decoded.voltage_rating_v else decoded.confidence * 0.7,
                }
        elif decoded.category == "resistor":
            power = self.RESISTOR_POWER.get(decoded.package) if decoded.package else None
            if power:
                return {
                    "category": "resistor",
                    "mpn_pattern": decoded.mpn,
                    "resistance_ohm": decoded.resistance_ohm,
                    "power_rating_W": power,
                    "derating_factor": 0.5,
                    "max_operating_power_W": power * 0.5,
                    "package": decoded.package,
                    "source": "mpn_decoder",
                    "confidence": decoded.confidence,
                }
        elif decoded.category == "ferrite_bead":
            entry = {
                "category": "ferrite_bead",
                "mpn_pattern": decoded.mpn,
                "package": decoded.package,
                "source": "mpn_decoder",
                "confidence": decoded.confidence,
            }
            if decoded.current_rating_a is not None:
                entry["current_rating_A"] = decoded.current_rating_a
                entry["derating_factor"] = 0.5
                entry["max_operating_current_A"] = decoded.current_rating_a * 0.5
            if decoded.resistance_ohm is not None:
                entry["impedance_ohm_100MHz"] = decoded.resistance_ohm
            return entry
        elif decoded.category == "inductor":
            entry = {
                "category": "inductor",
                "mpn_pattern": decoded.mpn,
                "package": decoded.package,
                "source": "mpn_decoder",
                "confidence": decoded.confidence,
            }
            if decoded.inductance_uh is not None:
                entry["inductance_uH"] = decoded.inductance_uh
                entry["derating_factor"] = 0.7  # 70% current derating for inductors
            if decoded.current_rating_a is not None:
                entry["current_rating_A"] = decoded.current_rating_a
                entry["max_operating_current_A"] = decoded.current_rating_a * 0.7
            return entry
        elif decoded.category in ("diode", "led"):
            entry = {
                "category": decoded.category,
                "mpn_pattern": decoded.mpn,
                "package": decoded.package,
                "source": "mpn_decoder",
                "confidence": decoded.confidence,
            }
            if decoded.diode_type:
                entry["diode_type"] = decoded.diode_type
            if decoded.voltage_rating_v is not None:
                entry["voltage_rating_V"] = decoded.voltage_rating_v
                entry["derating_factor"] = 0.5
                entry["max_operating_voltage_V"] = decoded.voltage_rating_v * 0.5
            if decoded.led_color:
                entry["led_color"] = decoded.led_color
            return entry
        elif decoded.category == "crystal":
            entry = {
                "category": "crystal",
                "mpn_pattern": decoded.mpn,
                "package": decoded.package,
                "source": "mpn_decoder",
                "confidence": decoded.confidence,
            }
            if decoded.frequency_hz is not None:
                entry["frequency_Hz"] = decoded.frequency_hz
            return entry
        elif decoded.category in ("mosfet", "transistor"):
            return {
                "category": decoded.category,
                "mpn_pattern": decoded.mpn,
                "package": decoded.package,
                "source": "mpn_decoder",
                "confidence": decoded.confidence,
            }
        return None


# ============================================================
# 主程序 — 批量解码 + 生成 AMR 数据
# ============================================================
if __name__ == "__main__":
    import sys
    import json

    decoder = MPNDecoder()

    # 测试标准 MPN
    test_mpns = [
        "GRM155R71C104KA88D",
        "GRM21BR71C106KE51L",
        "CL05B104KO5NNNC",
        "C1005X5R1C104K050BC",
    ]

    # 测试 Neo4j 描述格式
    test_descs = [
        ("CAP_C0402_DISCRETE_0.1UF_110-0014", "CAPACITOR"),
        ("CAP_C0402_DISCRETE_1UF_110-0014", "CAPACITOR"),
        ("CAP_SMX0402C_DISCRETE_10UF_110-", "CAPACITOR"),
        ("CAP_C0805_DISCRETE_22UF_110-004", "CAPACITOR"),
        ("RES_R0402_DISCRETE_4.7K_100-002", "RESISTOR"),
        ("RES_R0402_DISCRETE_10K_100-0024", "RESISTOR"),
        ("RES_R0402_DISCRETE_0_100-00241-", "RESISTOR"),
    ]

    print("=" * 60)
    print("标准 MPN 解码测试")
    print("=" * 60)
    for mpn in test_mpns:
        r = decoder.decode(mpn)
        print(f"\n{mpn}:")
        print(f"  → {r.to_dict()}")

    print("\n" + "=" * 60)
    print("Neo4j 描述解码测试")
    print("=" * 60)
    for desc, pt in test_descs:
        r = decoder.decode_neo4j_description(desc, pt)
        print(f"\n{desc}:")
        print(f"  → {r.to_dict()}")

    print("\n" + "=" * 60)
    print("AMR 数据生成测试")
    print("=" * 60)
    gen = AMRDataGenerator()
    for desc, pt in test_descs[:5]:
        r = decoder.decode_neo4j_description(desc, pt)
        amr = gen.generate_amr_entry(r)
        if amr:
            print(f"\n{desc}:")
            print(f"  → AMR: {json.dumps(amr, indent=2)}")
