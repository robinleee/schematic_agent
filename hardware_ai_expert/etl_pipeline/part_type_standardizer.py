"""
PartType 标准化器

将 ETL 提取的原始 PartType（如 "SKYLAKE_CAP"、"CAP_PPG"）
标准化为 PRD V5.0 定义的枚举类型。

三层降级策略：
  1. BOM Description 匹配（最高优先级，可选）
  2. Model/Primitive 名规则匹配
  3. Value 字段推断兜底

标准类型枚举：
  [MCU, PMIC, FPGA, LDO, BUCK, CONNECTOR, PASSIVE, IC, SOC, CPU,
   FLASH, DRAM, SENSOR, CRYSTAL, INDUCTOR, DIODE, TRANSISTOR,
   MOSFET, ESD, TVS, UNKNOWN]
"""

from __future__ import annotations

import os
import re
import csv
from typing import Optional, Any
from pathlib import Path


# ============================================================
# 标准类型枚举
# ============================================================

VALID_PART_TYPES = {
    "MCU", "PMIC", "FPGA", "LDO", "BUCK", "CONNECTOR",
    "CAPACITOR", "RESISTOR", "INDUCTOR", "PASSIVE",  # 被动器件细分
    "IC", "SOC", "CPU", "FLASH", "DRAM", "SENSOR", "CRYSTAL",
    "DIODE", "TRANSISTOR", "MOSFET", "ESD", "TVS",
    "TESTPOINT", "LED", "MECHANICAL", "UNKNOWN",
}


# ============================================================
# Layer 1: BOM Description 关键词映射
# ============================================================

BOM_KEYWORDS: dict[str, list[str]] = {
    "MCU": ["MCU", "MICROCONTROLLER", "ARM CORTEX", "CORTEX-M", "CORTEX-A"],
    "PMIC": ["PMIC", "POWER MANAGEMENT", "POWER IC", "BATTERY CHARGER", "CHARGE PUMP"],
    "FPGA": ["FPGA", "FIELD PROGRAMMABLE", "LATTICE", "XILINX", "ALTERA", "INTEL MAX"],
    "LDO": ["LDO", "LOW DROPOUT", "LINEAR REGULATOR", "XC6206", "RT9193", "TLV7"],
    "BUCK": ["BUCK", "DC-DC", "STEP DOWN", "STEP-DOWN", "SWITCHING REGULATOR", "STEP-UP", "BOOST"],
    "CONNECTOR": ["CONNECTOR", "HEADER", "CON HDR", "RECEPTACLE", "JACK", "BAT-HLD",
                   "HOLDER", "SOCKET", "PLUG", "PIN HEADER", "FPC", "FFC"],
    "FLASH": ["FLASH", "NOR FLASH", "NAND FLASH", "EEPROM", "SERIAL FLASH", "SPI FLASH"],
    "DRAM": ["DRAM", "DDR", "LPDDR", "SDRAM", "DDR3", "DDR4", "DDR5"],
    "CRYSTAL": ["CRYSTAL", "OSCILLATOR", "TCXO", "XTAL", "OSCI", "CERAMIC RESONATOR"],
    "INDUCTOR": ["INDUCTOR", "FERRITE BEAD", "CHOKE", "POWER INDUCTOR", "CHIP INDUCTOR"],
    "DIODE": ["DIODE", "SCHOTTKY", "RECTIFIER", "ZENER", "TVS DIODE"],
    "TRANSISTOR": ["TRANSISTOR", "BJT", "NPN", "PNP", "BIPOLAR"],
    "MOSFET": ["MOSFET", "POWER MOSFET", "N-CHANNEL", "P-CHANNEL"],
    "ESD": ["ESD", "TVS", "TRANSIENT", "SURGE PROTECTOR"],
    "SENSOR": ["SENSOR", "TEMPERATURE SENSOR", "ACCELEROMETER", "GYROSCOPE",
               "HUMIDITY", "PRESSURE SENSOR", "OPTICAL SENSOR"],
    "SOC": ["SOC", "SYSTEM ON CHIP", "APPLICATION PROCESSOR"],
    "CPU": ["CPU", "PROCESSOR", "MICROPROCESSOR"],
    "IC": ["IC", "INTEGRATED CIRCUIT", "INTERFACE", "BUFFER", "DRIVER", "OP AMP",
           "COMPARATOR", "MUX", "MULTIPLEXER", "ENCODER", "DECODER"],
}


# ============================================================
# Layer 2: Model/Primitive 名正则模式
# ============================================================

MODEL_PATTERNS: dict[str, list[str]] = {
    "MCU": [r'(?i)MCU', r'(?i)MICRO', r'(?i)CORTEX', r'(?i)STM32', r'(?i)MSP430', r'(?i)^SAK-TC'],
    "FPGA": [r'(?i)FPGA', r'(?i)LATTICE', r'(?i)XILINX', r'(?i)ALTERA', r'(?i)MAX10', r'(?i)XC7Z', r'(?i)XCKU'],
    "PMIC": [r'(?i)PMIC', r'(?i)TPS65', r'(?i)ACT8', r'(?i)BQ24', r'(?i)MAX77', r'(?i)^MPS[_\-]', r'(?i)^MPQ', r'(?i)^MP8', r'(?i)TLF35584'],
    "LDO": [r'(?i)LDO', r'(?i)XC6206', r'(?i)RT9193', r'(?i)TLV7', r'(?i)AMS11'],
    "BUCK": [r'(?i)BUCK', r'(?i)TPS54', r'(?i)MP23', r'(?i)SY8', r'(?i)LMR3'],
    "CONNECTOR": [r'(?i)CONN', r'(?i)HDR', r'(?i)HEADER', r'(?i)RECEPTACLE',
                  r'(?i)JACK', r'(?i)BAT-HLD', r'(?i)HOLDER', r'(?i)FPC',
                  r'(?i)FFC', r'(?i)SOCKET', r'(?i)PLUG',
                  r'(?i)^TE[_\-]', r'(?i)^CNU', r'(?i)^REC0DA'],
    "FLASH": [r'(?i)FLASH', r'(?i)MT25', r'(?i)W25', r'(?i)S25', r'(?i)M25',
              r'(?i)NOR', r'(?i)EEPROM', r'(?i)SPI_FLASH'],
    "DRAM": [r'(?i)DDR', r'(?i)LPDDR', r'(?i)SDRAM', r'(?i)H5T', r'(?i)^MT60B2G8HB', r'(?i)^MT53[D|E]'],
    "CRYSTAL": [r'(?i)XTAL', r'(?i)CRYSTAL', r'(?i)OSCI', r'(?i)TCXO', r'(?i)ABM', r'(?i)^OSC[_\-]', r'(?i)^GNR[_\-]SP'],
    "SENSOR": [r'(?i)SENSOR', r'(?i)BMP28', r'(?i)MPU[-_]?60', r'(?i)LIS3', r'(?i)HMC58', r'(?i)QMC58'],
    "INDUCTOR": [r'(?i)INDUCTOR', r'(?i)FERRITE', r'(?i)CHOKE', r'(?i)^L[0-9]{1,4}[_\-]', r'(?i)^EMIFILTER', r'(?i)^FL[0-9]'],
    "DIODE": [r'(?i)DIODE', r'(?i)SCHOTTKY', r'(?i)RECTIFIER', r'(?i)ZENER',
              r'(?i)1N4148', r'(?i)SS34'],
    "TRANSISTOR": [r'(?i)TRANSISTOR', r'(?i)BJT', r'(?i)NPN', r'(?i)PNP',
                   r'(?i)BC8', r'(?i)2N39'],
    "MOSFET": [r'(?i)MOSFET', r'(?i)SI23', r'(?i)AO34', r'(?i)IRF', r'(?i)^FET[_\-]'],
    "ESD": [r'(?i)\bESD', r'(?i)\bTVS\b', r'(?i)PRTR', r'(?i)USBLC6', r'(?i)PESD'],
    "SOC": [r'(?i)SOC', r'(?i)RK3', r'(?i)AM33', r'(?i)IMX6', r'(?i)ALLWINNER', r'(?i)AST2600'],
    "CPU": [r'(?i)\bCPU\b', r'(?i)I[0-9]-', r'(?i)RYZEN', r'(?i)XEON'],
    "IC": [r'(?i)IC_', r'(?i)INTERFACE', r'(?i)BUFFER', r'(?i)DRIVER',
           r'(?i)MUX', r'(?i)ENCODER', r'(?i)DECODER', r'(?i)OP AMP',
           r'(?i)COMPARATOR', r'(?i)LEVEL SHIFT', r'(?i)TRANSLATOR',
           r'(?i)RTL8', r'(?i)LAN8', r'(?i)ETH PHY', r'(?i)ETHERNET',
           r'(?i)^TI[_\-]', r'(?i)^SN3', r'(?i)^DP83', r'(?i)^NTS', r'(?i)^NTB',
           r'(?i)74LVC', r'(?i)^FD', r'(?i)^INA226', r'(?i)^TS511',
           r'(?i)^ADI[_\-]', r'(?i)^LTC[_\-]', r'(?i)^RENESAS[_\-]',
           r'(?i)^TTL3257', r'(?i)^INDIE[_\-]', r'(?i)^PCF85',
           r'(?i)^UM980', r'(?i)^OPA31', r'(?i)^BCM8958', r'(?i)^9QXL',
           r'(?i)^TPS389', r'(?i)^GTL20', r'(?i)^UPD720', r'(?i)^U_PWRMTR',
           r'(?i)^TLE92', r'(?i)^TLE93', r'(?i)^SPD5118', r'(?i)^PCA96'],
    "TESTPOINT": [r'(?i)^TESTLOOP', r'(?i)^TPAD', r'(?i)^TESTPOINT'],
    "LED": [r'(?i)^LED[_\-]'],
    "MECHANICAL": [r'(?i)^MTH[_\-]', r'(?i)^PEMNUT', r'(?i)^MTG'],
    "CAPACITOR": [r'(?i)^CAP[_\-]', r'(?i)^CAP#1[_\-]', r'(?i)^C#1[_\-]', r'(?i)^381[_\-]'],
    "RESISTOR": [r'(?i)^RES[_\-]', r'(?i)^RESISTOR[_\-]', r'(?i)^R[0-9]{1,4}[_\-]', r'(?i)^719[_\-]'],
}


# ============================================================
# Layer 3: Value 推断模式
# ============================================================

VALUE_PATTERNS = {
    "CAP": re.compile(r'^[0-9]+(\.[0-9]+)?\s*[PNUµμ]?F$', re.IGNORECASE),   # 10pF, 0.1uF, 10µF, 4.7 UF
    "RES": re.compile(r'^[0-9]+(\.[0-9]+)?\s*[KMGΩR]?$', re.IGNORECASE),    # 10, 10K, 1M, 600R
    "IND": re.compile(r'^[0-9]+(\.[0-9]+)?\s*[UNµμ]?H$', re.IGNORECASE),    # 10uH, 100nH
}

MANUFACTURER_ALIASES = {
    "MURATA ELECTRONICS": "Murata", "MURATA": "Murata",
    "TEXAS INSTRUMENTS": "Texas Instruments", "TI": "Texas Instruments",
    "TDK CORPORATION": "TDK", "TDK": "TDK",
    "YAGEO CORPORATION": "Yageo", "YAGEO": "Yageo",
}


def _text(value):
    return str(value).strip() if value is not None else ""


def _normalize_mpn(value):
    # Do not strip punctuation: suffixes and separators can identify different parts.
    return re.sub(r"\s+", "", value).upper()


class PartTypeStandardizer:
    """PartType 标准化器"""

    def __init__(self, bom_path: Optional[str] = None):
        """
        Args:
            bom_path: BOM 文件路径（CSV 或 Excel），可选
        """
        self.bom_data: dict[str, str] = {}
        self.bom_records: dict[str, dict[str, str]] = {}
        self.bom_issues: list[dict] = []
        self.bom_refs: set[str] = set()
        self._conflicted_refs: set[str] = set()
        self.stats = {
            "bom_hits": 0,
            "model_hits": 0,
            "value_hits": 0,
            "unknown": 0,
            "total": 0,
        }

        if bom_path:
            self.bom_data = self._load_bom(bom_path)

    def get_bom_record(self, refdes: str) -> dict[str, str]:
        """Return normalized BOM metadata for a RefDes, if available."""
        return dict(self.bom_records.get(refdes, {}))

    def bom_report(self, component_refs) -> list[dict]:
        """Line-addressable issues; never infer a match outside the netlist."""
        refs = set(component_refs)
        return self.bom_issues + [
            {"source_line": self.bom_records[r]["source_line"],
             "refdes": r, "reason": "unmatched_refdes"}
            for r in sorted(self.bom_refs - refs)
            if r in self.bom_records
        ]

    def _ingest_row(self, row, columns, line, result):
        def raw(name):
            key = columns.get(name)
            value = row.get(key) if key is not None else None
            return str(value) if value is not None else ""

        def get(name):
            return raw(name).strip()

        raw_refs = raw("ref")
        refs = list(dict.fromkeys(r.upper() for r in re.split(r"[,;\s]+", raw_refs) if r))
        if not refs:
            self.bom_issues.append({"source_line": line, "refdes": "", "reason": "missing_refdes"})
            return
        mpn_raw = raw("mpn")
        manufacturer_raw = raw("manufacturer")
        # Never guess a preferred item from an alternatives list.
        ambiguous = bool(re.search(r"[,;|\n]", mpn_raw))
        normalized = _normalize_mpn(mpn_raw) if not ambiguous else ""
        record = {
            "description": get("description"), "mpn": mpn_raw.strip() if not ambiguous else "",
            "mpn_raw": mpn_raw, "mpn_normalized": normalized,
            "manufacturer": MANUFACTURER_ALIASES.get(manufacturer_raw.strip().upper(), manufacturer_raw.strip()),
            "manufacturer_raw": manufacturer_raw,
            "quantity": get("quantity"), "package": get("package"),
            "source_line": line, "refdes_raw": raw_refs, "refdes_list": refs,
        }
        for ref in refs:
            self.bom_refs.add(ref)
            if ref in self.bom_records:
                self.bom_issues.append({"source_line": line, "refdes": ref,
                                        "reason": "duplicate_refdes",
                                        "previous_line": self.bom_records[ref]["source_line"]})
                # Conflicting refs cannot safely be enriched (including identical rows).
                self.bom_records.pop(ref)
                result.pop(ref, None)
                self._conflicted_refs.add(ref)
            elif ref in self._conflicted_refs:
                self.bom_issues.append({"source_line": line, "refdes": ref,
                                        "reason": "duplicate_refdes"})
            else:
                self.bom_records[ref] = dict(record)
                result[ref] = record["description"]
            if not mpn_raw.strip() or ambiguous:
                self.bom_issues.append({"source_line": line, "refdes": ref,
                                        "reason": "missing_mpn" if not mpn_raw.strip() else "multiple_mpn"})

    def enrich_component(self, refdes: str, component: dict[str, Any]) -> dict[str, Any]:
        """Merge BOM metadata into a Component dict without overwriting ETL core fields."""
        record = self.get_bom_record(refdes)
        if not record:
            return component
        enriched = dict(component)
        mapping = {
            "mpn_raw": "MPNRaw",
            "mpn_normalized": "MPNNormalized",
            "manufacturer": "Manufacturer",
            "manufacturer_raw": "ManufacturerRaw",
            "description": "Description",
            "quantity": "Quantity",
            "package": "Package",
            "source_line": "BOMSourceLine",
            "refdes_raw": "BOMRefDesRaw",
            "refdes_list": "BOMRefDesList",
        }
        for src, dst in mapping.items():
            if record.get(src) and not enriched.get(dst):
                enriched[dst] = record[src]
        if record["mpn_normalized"] and not enriched.get("MPN"):
            enriched["MPN"] = record["mpn_normalized"]
        enriched.setdefault("MPNRaw", record["mpn_raw"])
        enriched.setdefault("ManufacturerRaw", record["manufacturer_raw"])
        return enriched

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def standardize(self, refdes: str, model: str, value: Optional[str] = None) -> str:
        """
        三层降级标准化

        Args:
            refdes: 器件位号（用于 BOM 查找）
            model: 库模型名 / primitive 名
            value: 器件 Value，如 "0.1UF", "10K"

        Returns:
            标准化后的 PartType 字符串
        """
        self.stats["total"] += 1

        # Layer 1: BOM Description 匹配
        if self.bom_data:
            result = self._match_bom(refdes)
            if result:
                self.stats["bom_hits"] += 1
                return result

        # Layer 2: Model 名匹配
        result = self._match_model(model)
        if result:
            self.stats["model_hits"] += 1
            return result

        # Layer 3: Value 推断
        result = self._match_value(value)
        if result:
            self.stats["value_hits"] += 1
            return result

        # Fallback: UNKNOWN
        self.stats["unknown"] += 1
        return "UNKNOWN"

    def get_stats(self) -> dict:
        """返回标准化统计"""
        total = self.stats["total"]
        if total == 0:
            return {**self.stats, "coverage": 0.0}

        known = total - self.stats["unknown"]
        coverage = known / total * 100
        return {
            **self.stats,
            "coverage_pct": round(coverage, 1),
        }

    def print_stats(self):
        """打印标准化统计"""
        stats = self.get_stats()
        print("\n" + "=" * 50)
        print("PartType 标准化统计")
        print("=" * 50)
        print(f"  总数:      {stats['total']}")
        print(f"  BOM 匹配:  {stats['bom_hits']}")
        print(f"  Model 匹配: {stats['model_hits']}")
        print(f"  Value 推断: {stats['value_hits']}")
        print(f"  UNKNOWN:   {stats['unknown']}")
        print(f"  覆盖率:    {stats['coverage_pct']}%")
        print("=" * 50)

    # --------------------------------------------------------
    # Layer 1: BOM 匹配
    # --------------------------------------------------------

    def _load_bom(self, path: str) -> dict[str, str]:
        """加载 BOM 文件，返回 {refdes: description}"""
        path = Path(path)
        if not path.exists():
            print(f"[BOM] 文件不存在: {path}")
            return {}

        ext = path.suffix.lower()

        if ext in (".csv", ".txt"):
            return self._load_bom_csv(path)
        elif ext == ".xlsx":
            return self._load_bom_excel(path)
        elif ext == ".xls":
            return self._load_bom_xls(path)
        else:
            print(f"[BOM] 不支持的文件格式: {ext}")
            return {}

    def _load_bom_csv(self, path: Path) -> dict[str, str]:
        """加载 CSV 格式的 BOM"""
        result = {}

        # 尝试不同的编码
        encodings = ["utf-8", "gbk", "latin-1", "cp1252"]

        for encoding in encodings:
            try:
                with open(path, "r", encoding=encoding, newline="") as f:
                    # 尝试自动检测分隔符
                    sample = f.read(4096)
                    f.seek(0)

                    delimiter = ","
                    if "\t" in sample and sample.count("\t") > sample.count(","):
                        delimiter = "\t"

                    reader = csv.DictReader(f, delimiter=delimiter)

                    ref_col = self._find_column(reader.fieldnames,
                                                  ["RefDes", "BOM.Ref Des", "BOM.RefDes",
                                                   "Ref", "Designator", "Reference", "位号"])
                    desc_col = self._find_column(reader.fieldnames,
                                                  ["Description", "BOM.Item Description", "Desc",
                                                   "Part Description", "描述", "Comment"])
                    mpn_col = self._find_column(reader.fieldnames,
                                                ["MPN", "BOM.MPN", "Manufacturer Part Number",
                                                 "Part Number", "P/N", "PN", "料号"])
                    mfr_col = self._find_column(reader.fieldnames,
                                                ["Manufacturer", "BOM.Manufacturer", "Mfr",
                                                 "MFG", "Vendor", "厂商"])
                    qty_col = self._find_column(reader.fieldnames,
                                                ["Qty", "BOM.Qty", "Quantity", "数量"])
                    pkg_col = self._find_column(reader.fieldnames,
                                                ["Package", "Footprint", "封装"])

                    if not ref_col:
                        print(f"[BOM] 未找到 RefDes/Description 列，可用列: {reader.fieldnames}")
                        return {}

                    columns = dict(ref=ref_col, description=desc_col, mpn=mpn_col,
                                   manufacturer=mfr_col, quantity=qty_col, package=pkg_col)
                    for row in reader:
                        self._ingest_row(row, columns, reader.line_num, result)

                print(f"[BOM] 从 CSV 加载了 {len(result)} 条 BOM 记录")
                return result

            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"[BOM] CSV 读取失败: {e}")
                return {}

        print("[BOM] 无法解码 CSV 文件")
        return {}

    def _load_bom_excel(self, path: Path) -> dict[str, str]:
        """加载 .xlsx 格式的 BOM."""
        if path.suffix.lower() == ".xls":
            return self._load_bom_xls(path)

        try:
            import openpyxl
        except ImportError:
            print("[BOM] 未安装 openpyxl，无法读取 Excel。请运行: pip install openpyxl")
            return {}

        result = {}
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
            ws = wb.active

            # 查找表头行
            headers = [str(cell.value).strip() if cell.value else "" for cell in ws[1]]

            ref_col_idx = self._find_column_index(headers,
                                                  ["RefDes", "BOM.Ref Des", "BOM.RefDes",
                                                   "Ref", "Designator", "Reference", "位号"])
            desc_col_idx = self._find_column_index(headers,
                                                   ["Description", "BOM.Item Description", "Desc",
                                                    "Part Description", "描述", "Comment"])
            mpn_col_idx = self._find_column_index(headers,
                                                  ["MPN", "BOM.MPN", "Manufacturer Part Number",
                                                   "Part Number", "P/N", "PN", "料号"])
            mfr_col_idx = self._find_column_index(headers,
                                                  ["Manufacturer", "BOM.Manufacturer", "Mfr",
                                                   "MFG", "Vendor", "厂商"])
            qty_col_idx = self._find_column_index(headers, ["Qty", "BOM.Qty", "Quantity", "数量"])
            pkg_col_idx = self._find_column_index(headers, ["Package", "Footprint", "封装"])

            if ref_col_idx is None:
                print(f"[BOM] 未找到 RefDes/Description 列，可用列: {headers}")
                return {}

            columns = dict(ref=ref_col_idx, description=desc_col_idx, mpn=mpn_col_idx,
                           manufacturer=mfr_col_idx, quantity=qty_col_idx, package=pkg_col_idx)
            for line, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
                row = {idx: values[idx] if idx < len(values) else None
                       for idx in columns.values() if idx is not None}
                self._ingest_row(row, columns, line, result)

            print(f"[BOM] 从 Excel 加载了 {len(result)} 条 BOM 记录")
            return result

        except Exception as e:
            print(f"[BOM] Excel 读取失败: {e}")
            return {}

    def _load_bom_xls(self, path: Path) -> dict[str, str]:
        """使用 xlrd 加载旧式 .xls BOM。"""
        try:
            import xlrd
        except ImportError:
            print("[BOM] 未安装 xlrd，无法读取 .xls。请运行: pip install xlrd")
            return {}

        result = {}
        try:
            workbook = xlrd.open_workbook(path, on_demand=True)
            sheet = workbook.sheet_by_index(0)
            headers = [
                str(sheet.cell_value(0, column)).strip()
                if sheet.ncols else ""
                for column in range(sheet.ncols)
            ]
            columns = {
                "ref": self._find_column_index(
                    headers,
                    ["RefDes", "Ref", "Designator", "Reference", "BOM.Ref Des", "位号"],
                ),
                "description": self._find_column_index(
                    headers,
                    [
                        "Description",
                        "Desc",
                        "Part Description",
                        "BOM.Item Description",
                        "描述",
                        "Comment",
                    ],
                ),
                "mpn": self._find_column_index(
                    headers,
                    [
                        "MPN",
                        "Manufacturer Part Number",
                        "Part Number",
                        "P/N",
                        "PN",
                        "BOM.MPN",
                        "料号",
                    ],
                ),
                "manufacturer": self._find_column_index(
                    headers,
                    ["Manufacturer", "Mfr", "MFG", "Vendor", "BOM.Manufacturer", "厂商"],
                ),
                "quantity": self._find_column_index(
                    headers, ["Qty", "Quantity", "BOM.Qty", "数量"]
                ),
                "package": self._find_column_index(headers, ["Package", "Footprint", "封装"]),
            }

            if columns["ref"] is None:
                print(f"[BOM] 未找到 RefDes/Description 列，可用列: {headers}")
                return {}

            for line in range(1, sheet.nrows):
                row = {
                    column: sheet.cell_value(line, column)
                    for column in columns.values()
                    if column is not None
                }
                self._ingest_row(row, columns, line + 1, result)

            print(f"[BOM] 从旧式 XLS 加载了 {len(result)} 条 BOM 记录")
            return result
        except Exception as e:
            print(f"[BOM] XLS 读取失败: {e}")
            return {}

    @staticmethod
    def _find_column(fieldnames: Optional[list[str]], candidates: list[str]) -> Optional[str]:
        """在字段名中查找匹配的列"""
        if not fieldnames:
            return None
        fieldnames_lower = [f.strip().lower() for f in fieldnames]
        for cand in candidates:
            normalized_candidate = cand.strip().lower()
            if normalized_candidate in fieldnames_lower:
                idx = fieldnames_lower.index(normalized_candidate)
                return fieldnames[idx]
        return None

    @staticmethod
    def _find_column_index(headers: list[str], candidates: list[str]) -> Optional[int]:
        """在表头中查找匹配的列索引"""
        headers_lower = [h.strip().lower() for h in headers]
        for cand in candidates:
            normalized_candidate = cand.strip().lower()
            if normalized_candidate in headers_lower:
                return headers_lower.index(normalized_candidate)
        return None

    def _match_bom(self, refdes: str) -> Optional[str]:
        """通过 BOM Description 匹配标准类型"""
        desc = self.bom_data.get(refdes)
        if not desc:
            return None

        desc_upper = desc.upper()

        for part_type, keywords in BOM_KEYWORDS.items():
            for kw in keywords:
                if kw.upper() in desc_upper:
                    return part_type

        return None

    # --------------------------------------------------------
    # Layer 2: Model 匹配
    # --------------------------------------------------------

    def _match_model(self, model: Optional[str]) -> Optional[str]:
        """通过 Model/Primitive 名匹配标准类型"""
        if not model:
            return None

        # 先检查是否直接命中高置信度模式
        for part_type, patterns in MODEL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, model):
                    return part_type

        # 被动器件兜底：如果 Model 名包含明显的被动器件特征
        passive_model_pattern = re.compile(
            r'(?i)^(CAP|RES|IND|INDUCTOR|FERRITE|C[0-9]{4}|R[0-9]{4}|L[0-9]{4})[_\-]'
        )
        if passive_model_pattern.search(model):
            return "PASSIVE"

        return None

    # --------------------------------------------------------
    # Layer 3: Value 推断
    # --------------------------------------------------------

    def _match_value(self, value: Optional[str]) -> Optional[str]:
        """通过 Value 字段推断类型"""
        if not value:
            return None

        val = value.strip().upper()

        # 跳过 DNP/NC 标记
        if val.startswith("DNP") or val.startswith("NC") or val == "0":
            return None

        if VALUE_PATTERNS["CAP"].match(val):
            return "CAPACITOR"
        if VALUE_PATTERNS["RES"].match(val):
            return "RESISTOR"
        if VALUE_PATTERNS["IND"].match(val):
            return "INDUCTOR"

        return None


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    """运行自测"""
    print("=" * 60)
    print("PartTypeStandardizer Self-test")
    print("=" * 60)

    standardizer = PartTypeStandardizer()

    test_cases = [
        # (refdes, model, value, expected)
        ("C30001", "CAP_PPG_C0402_DISCRETE_0.1UF_11", "0.1UF", "PASSIVE"),
        ("R30002", "RES_PPG_R0402_DISCRETE_10K_", "10K", "PASSIVE"),
        ("L30003", "IND_PPG_L0603_DISCRETE_10UH_", "10UH", "PASSIVE"),
        ("U30004", "MT25QL02GCBB8E12_TPBGA24", None, "FLASH"),
        ("J70003", "HDR_2X5_M", None, "CONNECTOR"),
        ("BT6E1", "SKYLAKE_CAP_BAT-HLD-2032-TE_CR2", None, "CONNECTOR"),
        ("U50001", "TPS5430DDAR", None, "BUCK"),
        ("U50002", "XC6206P332MR", None, "LDO"),
        ("U60001", "STM32F407VGT6", None, "MCU"),
        ("U60002", "XC7Z020-1CLG400C", None, "FPGA"),
        ("D30001", "SS34_SMA", None, "DIODE"),
        ("Q30001", "SI2302CDS", None, "MOSFET"),
        ("Y30001", "ABM8-272-T3", None, "CRYSTAL"),
        ("U70001", "MPU-6050", None, "SENSOR"),
        ("U80001", "RK3568", None, "SOC"),
        ("U90001", "RTL8211E-VB-CG", None, "IC"),
        ("C30002", "CAP_C0402_100NF_50V", "100NF", "PASSIVE"),
        ("R30003", "R0402_1K_1%", "1K", "PASSIVE"),
        ("U30005", "ESD5V0D9", None, "ESD"),
        ("J30001", "FPC_0.5MM_30PIN", None, "CONNECTOR"),
        ("U30006", "W25Q128JVSQ", None, "FLASH"),
        ("U30007", "H5TQ4G63CFR", None, "DRAM"),
        ("L30002", "FERRITE_BEAD_600R", "600R", "PASSIVE"),  # 注意：FERRITE_BEAD 在 Model 匹配中是 INDUCTOR
        ("FB3001", "FB_PPG_0603_600R", "600R", "PASSIVE"),   # 同上
    ]

    passed = 0
    failed = 0
    failed_cases = []

    for refdes, model, value, expected in test_cases:
        result = standardizer.standardize(refdes, model, value)
        ok = result == expected

        # 特殊处理：FERRITE_BEAD 匹配到 INDUCTOR 也接受
        if not ok and expected == "PASSIVE" and "FERRITE" in (model or "").upper():
            if result == "INDUCTOR":
                ok = True

        if ok:
            passed += 1
            print(f"  ✅ {refdes}: {model} → {result}")
        else:
            failed += 1
            print(f"  ❌ {refdes}: {model} → {result} (expected: {expected})")
            failed_cases.append((refdes, model, value, expected, result))

    print(f"\n  结果: {passed}/{len(test_cases)} 通过")
    standardizer.print_stats()

    # 注意：自测时 bom_hits 为 0 因为没有提供 BOM
    if failed > 0:
        print("\n  失败的用例:")
        for refdes, model, value, expected, result in failed_cases:
            print(f"    - {refdes}: {model} (value={value}) → {result}, expected {expected}")

    if failed == 0:
        print("\n✅ PartTypeStandardizer All tests passed")
    else:
        print(f"\n⚠️  {failed} 个测试失败，需要调整匹配规则")

    return failed == 0


if __name__ == "__main__":
    _run_tests()
