"""
Datasheet PDF 解析器

功能：
  1. 从 PDF 提取文本和表格
  2. 识别参数表区域（ABSOLUTE MAXIMUM RATINGS, ELECTRICAL CHARACTERISTICS）
  3. 使用 LLM 将原始文本转换为结构化参数
  4. 输出标准格式的 AMR 参数（耐压、电流、温度、ESR 等）

对应 PRD: Phase 4 - Datasheet 数据闭环
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

class ParamType(str, Enum):
    """参数类型"""
    CAPACITANCE = "capacitance"           # 电容值 (F)
    CAP_VOLTAGE_RATING = "cap_voltage_rating"  # 电容耐压 (V)
    CAP_ESR = "cap_esr"                   # ESR (Ω)
    RESISTANCE = "resistance"             # 电阻值 (Ω)
    RES_POWER_RATING = "res_power_rating" # 电阻额定功率 (W)
    VOLTAGE_MIN = "voltage_min"           # 最小工作电压 (V)
    VOLTAGE_MAX = "voltage_max"           # 最大工作电压 (V)
    CURRENT_MAX = "current_max"           # 最大电流 (A)
    TEMP_MIN = "temp_min"                 # 最低工作温度 (°C)
    TEMP_MAX = "temp_max"                 # 最高工作温度 (°C)
    VOUT_FORMULA = "vout_formula"         # 输出电压公式
    INDUCTANCE = "inductance"             # 电感值 (H)
    FREQUENCY = "frequency"               # 开关频率 (Hz)


@dataclass
class DatasheetParameter:
    """从 Datasheet 提取的单个参数"""
    param_type: ParamType
    name: str                    # 原始参数名（如 "Voltage Rating"）
    value: float                 # 数值
    unit: str                    # 单位（如 "V", "uF", "A"）
    condition: str = ""          # 测试条件（如 "@ 25°C"）
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    typical_value: Optional[float] = None
    source_text: str = ""        # 原始文本片段
    confidence: float = 1.0      # 提取置信度


@dataclass
class ExtractedComponent:
    """从 Datasheet 提取的完整器件参数集"""
    mpn: str                     # Manufacturer Part Number
    manufacturer: str = ""
    description: str = ""
    parameters: List[DatasheetParameter] = None
    source_file: str = ""        # 原始 PDF 路径
    extraction_method: str = ""  # "regex" / "llm" / "manual"
    extracted_at: str = ""

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []

    def get_param(self, param_type: ParamType) -> Optional[DatasheetParameter]:
        """获取指定类型的参数"""
        for p in self.parameters:
            if p.param_type == param_type:
                return p
        return None

    def to_dict(self) -> dict:
        return {
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "source_file": self.source_file,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at,
            "parameters": [
                {
                    "param_type": p.param_type.value,
                    "name": p.name,
                    "value": p.value,
                    "unit": p.unit,
                    "condition": p.condition,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "typical_value": p.typical_value,
                    "confidence": p.confidence,
                }
                for p in self.parameters
            ]
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractedComponent":
        params = []
        for p in d.get("parameters", []):
            params.append(DatasheetParameter(
                param_type=ParamType(p["param_type"]),
                name=p["name"],
                value=p["value"],
                unit=p["unit"],
                condition=p.get("condition", ""),
                min_value=p.get("min_value"),
                max_value=p.get("max_value"),
                typical_value=p.get("typical_value"),
                confidence=p.get("confidence", 1.0),
            ))
        return cls(
            mpn=d["mpn"],
            manufacturer=d.get("manufacturer", ""),
            description=d.get("description", ""),
            parameters=params,
            source_file=d.get("source_file", ""),
            extraction_method=d.get("extraction_method", ""),
            extracted_at=d.get("extracted_at", ""),
        )


# ============================================================
# PDF 文本提取器
# ============================================================

class PDFTextExtractor:
    """从 PDF 提取文本内容"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self._doc = None

    def _open(self):
        if self._doc is None:
            import fitz
            self._doc = fitz.open(self.pdf_path)

    def close(self):
        if self._doc:
            self._doc.close()
            self._doc = None

    def extract_all_text(self) -> str:
        """提取 PDF 全部文本"""
        self._open()
        texts = []
        for page in self._doc:
            texts.append(page.get_text())
        return "\n".join(texts)

    def extract_pages(self, start: int = 0, end: Optional[int] = None) -> List[str]:
        """提取指定页范围的文本"""
        self._open()
        texts = []
        end = end or len(self._doc)
        for i in range(start, min(end, len(self._doc))):
            texts.append(self._doc[i].get_text())
        return texts

    def find_pages_with_keywords(self, keywords: List[str]) -> List[int]:
        """找到包含关键词的页码"""
        self._open()
        matched_pages = []
        for i, page in enumerate(self._doc):
            text = page.get_text().upper()
            if any(kw.upper() in text for kw in keywords):
                matched_pages.append(i)
        return matched_pages

    def extract_tables(self, page_num: int) -> List[List[List[str]]]:
        """提取指定页的表格（简单实现）"""
        self._open()
        page = self._doc[page_num]
        tables = []
        # PyMuPDF 的表格提取
        tabs = page.find_tables()
        if tabs.tables:
            for tab in tabs.tables:
                tables.append(tab.extract())
        return tables


# ============================================================
# 参数区域识别器
# ============================================================

class ParameterSectionDetector:
    """
    识别 Datasheet 中的参数表区域

    支持识别的区域：
      - ABSOLUTE MAXIMUM RATINGS
      - RECOMMENDED OPERATING CONDITIONS
      - ELECTRICAL CHARACTERISTICS
      - TYPICAL PERFORMANCE
    """

    SECTION_PATTERNS = {
        "absolute_maximum": [
            r"ABSOLUTE\s+MAXIMUM\s+RATINGS",
            r"MAXIMUM\s+RATINGS",
            r"STRESS\s+RATINGS",
        ],
        "recommended_operating": [
            r"RECOMMENDED\s+OPERATING\s+CONDITIONS",
            r"OPERATING\s+CONDITIONS",
            r"OPERATING\s+RANGES",
        ],
        "electrical_characteristics": [
            r"ELECTRICAL\s+CHARACTERISTICS",
            r"ELECTRICAL\s+SPECIFICATIONS",
            r"DC\s+CHARACTERISTICS",
        ],
        "typical_performance": [
            r"TYPICAL\s+PERFORMANCE",
            r"TYPICAL\s+OPERATING",
            r"CHARACTERISTIC\s+CURVES",
        ],
    }

    def detect_sections(self, text: str) -> Dict[str, str]:
        """
        从文本中识别各个参数区域
        返回: {section_name: section_text}
        """
        sections = {}
        lines = text.split('\n')
        current_section = None
        current_text = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # 检查是否是新的区域标题
            found_section = None
            for section_name, patterns in self.SECTION_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, line_stripped, re.IGNORECASE):
                        found_section = section_name
                        break
                if found_section:
                    break

            if found_section:
                # 保存之前的区域
                if current_section and current_text:
                    sections[current_section] = '\n'.join(current_text)
                current_section = found_section
                current_text = []
            elif current_section:
                current_text.append(line_stripped)

        # 保存最后一个区域
        if current_section and current_text:
            sections[current_section] = '\n'.join(current_text)

        return sections


# ============================================================
# 正则参数提取器（快速模式）
# ============================================================

class RegexParameterExtractor:
    """
    使用正则表达式从文本中快速提取常见参数

    适合明确格式的参数表，速度快但覆盖有限
    """

    # 电容耐压
    CAP_VOLTAGE_PATTERNS = [
        r"(?:Rated\s+)?Voltage[^\n]*?(\d+(?:\.\d+)?)\s*(V|kV)",
        r"Voltage\s+Rating[^\n]*?(\d+(?:\.\d+)?)\s*(V|kV)",
        r"Max\.?\s+Voltage[^\n]*?(\d+(?:\.\d+)?)\s*(V|kV)",
        r"Withstanding\s+Voltage[^\n]*?(\d+(?:\.\d+)?)\s*(V|kV)",
    ]

    # 电容值
    CAPACITANCE_PATTERNS = [
        r"(?:Nominal\s+)?Capacitance[^\n]*?(\d+(?:\.\d+)?)\s*(pF|nF|uF|μF|mF|F)",
        r"Capacity[^\n]*?(\d+(?:\.\d+)?)\s*(pF|nF|uF|μF|mF|F)",
    ]

    # ESR
    ESR_PATTERNS = [
        r"ESR[^\n]*?(\d+(?:\.\d+)?)\s*(m?Ω|ohm)",
        r"Equivalent\s+Series\s+Resistance[^\n]*?(\d+(?:\.\d+)?)\s*(m?Ω|ohm)",
    ]

    # 电阻功率
    RES_POWER_PATTERNS = [
        r"Power\s+Rating[^\n]*?(\d+(?:\.\d+)?)\s*(m?W)",
        r"Rated\s+Power[^\n]*?(\d+(?:\.\d+)?)\s*(m?W)",
    ]

    # 电压范围
    VOLTAGE_RANGE_PATTERNS = [
        r"Input\s+Voltage[^\n]*?(\d+(?:\.\d+)?)\s*V\s*(?:to|-|~|–)\s*(\d+(?:\.\d+)?)\s*V",
        r"Supply\s+Voltage[^\n]*?(\d+(?:\.\d+)?)\s*V\s*(?:to|-|~|–)\s*(\d+(?:\.\d+)?)\s*V",
        r"VCC[^\n]*?(\d+(?:\.\d+)?)\s*V\s*(?:to|-|~|–)\s*(\d+(?:\.\d+)?)\s*V",
    ]

    def extract_capacitor_params(self, text: str) -> List[DatasheetParameter]:
        """提取电容参数"""
        params = []
        text_upper = text.upper()

        # 耐压
        for pattern in self.CAP_VOLTAGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2)
                if unit.upper() == 'KV':
                    value *= 1000
                    unit = 'V'
                params.append(DatasheetParameter(
                    param_type=ParamType.CAP_VOLTAGE_RATING,
                    name="Voltage Rating",
                    value=value,
                    unit=unit,
                    source_text=match.group(0)[:100],
                ))
                break  # 只取第一个匹配

        # 容值
        for pattern in self.CAPACITANCE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2).replace('μ', 'u')
                params.append(DatasheetParameter(
                    param_type=ParamType.CAPACITANCE,
                    name="Capacitance",
                    value=value,
                    unit=unit,
                    source_text=match.group(0)[:100],
                ))
                break

        # ESR
        for pattern in self.ESR_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2)
                if unit.lower().startswith('m'):
                    value /= 1000
                    unit = 'Ω'
                params.append(DatasheetParameter(
                    param_type=ParamType.CAP_ESR,
                    name="ESR",
                    value=value,
                    unit=unit,
                    source_text=match.group(0)[:100],
                ))
                break

        return params

    def extract_resistor_params(self, text: str) -> List[DatasheetParameter]:
        """提取电阻参数"""
        params = []

        for pattern in self.RES_POWER_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2)
                if unit.lower().startswith('m'):
                    value /= 1000
                    unit = 'W'
                params.append(DatasheetParameter(
                    param_type=ParamType.RES_POWER_RATING,
                    name="Power Rating",
                    value=value,
                    unit=unit,
                    source_text=match.group(0)[:100],
                ))
                break

        return params

    def extract_ic_params(self, text: str) -> List[DatasheetParameter]:
        """提取 IC 电源参数"""
        params = []

        for pattern in self.VOLTAGE_RANGE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                vmin = float(match.group(1))
                vmax = float(match.group(2))
                params.append(DatasheetParameter(
                    param_type=ParamType.VOLTAGE_MIN,
                    name="Input Voltage Min",
                    value=vmin,
                    unit="V",
                    source_text=match.group(0)[:100],
                ))
                params.append(DatasheetParameter(
                    param_type=ParamType.VOLTAGE_MAX,
                    name="Input Voltage Max",
                    value=vmax,
                    unit="V",
                    source_text=match.group(0)[:100],
                ))
                break

        return params


# ============================================================
# LLM 参数提取器（智能模式）
# ============================================================

class LLMParameterExtractor:
    """
    使用本地 LLM (Ollama) 从原始文本中提取结构化参数

    适合复杂/非标准格式的参数表
    """

    def __init__(self, model: str = "gemma4:26b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def extract(self, text: str, component_hint: str = "") -> List[DatasheetParameter]:
        """
        使用 LLM 从文本中提取参数

        Args:
            text: Datasheet 的原始文本（已清理）
            component_hint: 器件类型提示（如 "capacitor", "resistor", "buck_converter"）
        """
        prompt = self._build_prompt(text, component_hint)
        response = self._call_llm(prompt)
        return self._parse_response(response)

    def _build_prompt(self, text: str, component_hint: str) -> str:
        """构建提取提示"""
        hint_str = f"This is a {component_hint}. " if component_hint else ""

        return f"""You are a hardware component parameter extractor. {hint_str}

Extract ALL relevant electrical parameters from the following datasheet text.
For each parameter, provide:
- parameter_name: the original name from the datasheet
- param_type: one of [cap_voltage_rating, capacitance, cap_esr, res_power_rating, voltage_min, voltage_max, current_max, temp_min, temp_max, vout_formula, inductance, frequency]
- value: the typical or nominal numeric value
- unit: the unit (V, A, uF, pF, Ω, W, °C, Hz, H, etc.)
- min_value: minimum value if specified
- max_value: maximum value if specified
- condition: test conditions if any

IMPORTANT: Only extract parameters with clear numeric values. Do not guess.

DATASHEET TEXT:
---
{text[:4000]}
---

Respond in valid JSON format:
{{
  "parameters": [
    {{
      "parameter_name": "...",
      "param_type": "...",
      "value": 123.4,
      "unit": "V",
      "min_value": null,
      "max_value": null,
      "condition": "@ 25°C"
    }}
  ]
}}
"""

    def _call_llm(self, prompt: str) -> str:
        """调用 Ollama API"""
        import urllib.request
        import json

        data = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                return result.get("response", "")
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""

    def _parse_response(self, response: str) -> List[DatasheetParameter]:
        """解析 LLM 的 JSON 响应"""
        params = []

        # 提取 JSON 块
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            logger.warning("No JSON found in LLM response")
            return params

        try:
            data = json.loads(json_match.group())
            for p in data.get("parameters", []):
                param_type_str = p.get("param_type", "")
                try:
                    param_type = ParamType(param_type_str)
                except ValueError:
                    logger.warning(f"Unknown param_type: {param_type_str}")
                    continue

                params.append(DatasheetParameter(
                    param_type=param_type,
                    name=p.get("parameter_name", ""),
                    value=p.get("value", 0.0),
                    unit=p.get("unit", ""),
                    min_value=p.get("min_value"),
                    max_value=p.get("max_value"),
                    condition=p.get("condition", ""),
                    confidence=0.8,  # LLM 提取默认置信度
                ))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON: {e}")

        return params


# ============================================================
# 主解析器
# ============================================================

class DatasheetParser:
    """
    Datasheet 解析器主类

    使用策略：
      1. 先用 Regex 快速提取（速度快，覆盖常见参数）
      2. 对 Regex 未覆盖的参数，用 LLM 补充提取
      3. 合并结果，去重
    """

    def __init__(self, use_llm: bool = True):
        self.text_extractor = None
        self.section_detector = ParameterSectionDetector()
        self.regex_extractor = RegexParameterExtractor()
        self.llm_extractor = LLMParameterExtractor() if use_llm else None

    def parse_pdf(self, pdf_path: str, component_hint: str = "") -> ExtractedComponent:
        """
        解析 PDF Datasheet

        Args:
            pdf_path: PDF 文件路径
            component_hint: 器件类型提示（capacitor/resistor/ic/buck_converter 等）

        Returns:
            ExtractedComponent: 提取的器件参数
        """
        import os
        from datetime import datetime

        # 1. 提取文本
        self.text_extractor = PDFTextExtractor(pdf_path)
        full_text = self.text_extractor.extract_all_text()

        # 2. 识别参数区域
        sections = self.section_detector.detect_sections(full_text)

        # 3. 合并关键区域文本
        key_text = full_text
        if sections:
            key_text = "\n\n".join([
                sections.get("absolute_maximum", ""),
                sections.get("recommended_operating", ""),
                sections.get("electrical_characteristics", ""),
            ])

        # 4. 提取参数
        all_params = self._extract_parameters(key_text, component_hint)

        # 5. 构建结果
        # 从文件名推断 MPN
        mpn = os.path.splitext(os.path.basename(pdf_path))[0]

        result = ExtractedComponent(
            mpn=mpn,
            source_file=pdf_path,
            extraction_method="regex+llm" if self.llm_extractor else "regex",
            extracted_at=datetime.now().isoformat(),
            parameters=all_params,
        )

        self.text_extractor.close()
        return result

    def _extract_parameters(self, text: str, component_hint: str) -> List[DatasheetParameter]:
        """提取参数（Regex + LLM 混合）"""
        # 1. Regex 提取
        regex_params = []
        if "cap" in component_hint.lower() or "capacitor" in text.lower()[:500]:
            regex_params.extend(self.regex_extractor.extract_capacitor_params(text))
        elif "res" in component_hint.lower() or "resistor" in text.lower()[:500]:
            regex_params.extend(self.regex_extractor.extract_resistor_params(text))
        else:
            regex_params.extend(self.regex_extractor.extract_ic_params(text))
            regex_params.extend(self.regex_extractor.extract_capacitor_params(text))
            regex_params.extend(self.regex_extractor.extract_resistor_params(text))

        # 2. LLM 补充提取
        llm_params = []
        if self.llm_extractor:
            llm_params = self.llm_extractor.extract(text, component_hint)

        # 3. 合并去重（优先 Regex 结果，LLM 补充缺失的类型）
        merged = {p.param_type: p for p in regex_params}
        for p in llm_params:
            if p.param_type not in merged:
                merged[p.param_type] = p

        return list(merged.values())


# ============================================================
# 测试
# ============================================================

def _test_parser():
    """测试解析器（使用模拟数据）"""
    print("=" * 60)
    print("Datasheet Parser 测试")
    print("=" * 60)

    # 1. 测试 Regex 提取器
    print("\n[1/3] RegexParameterExtractor 测试")

    test_text_cap = """
    ABSOLUTE MAXIMUM RATINGS
    Voltage Rating: 50V DC
    Capacitance: 10uF ±20%
    ESR: 0.05Ω @ 100kHz

    RECOMMENDED OPERATING CONDITIONS
    Temperature: -55°C to +105°C
    """

    extractor = RegexParameterExtractor()
    params = extractor.extract_capacitor_params(test_text_cap)
    print(f"  电容参数: {len(params)} 个")
    for p in params:
        print(f"    {p.param_type.value}: {p.value} {p.unit}")

    test_text_ic = """
    ELECTRICAL CHARACTERISTICS
    Input Voltage: 5.5V to 36V
    Output Current: 3A max
    """

    params = extractor.extract_ic_params(test_text_ic)
    print(f"  IC 参数: {len(params)} 个")
    for p in params:
        print(f"    {p.param_type.value}: {p.value} {p.unit}")

    # 2. 测试区域识别
    print("\n[2/3] ParameterSectionDetector 测试")
    detector = ParameterSectionDetector()
    sections = detector.detect_sections(test_text_cap + test_text_ic)
    print(f"  识别到区域: {list(sections.keys())}")

    # 3. 测试 LLM 提取器（如果 Ollama 可用）
    print("\n[3/3] LLMParameterExtractor 测试")
    llm = LLMParameterExtractor()
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            pass

        params = llm.extract(test_text_cap, "capacitor")
        print(f"  LLM 提取: {len(params)} 个参数")
        for p in params:
            print(f"    {p.param_type.value}: {p.value} {p.unit}")
    except Exception as e:
        print(f"  LLM 不可用: {e}")

    print("\n✅ Datasheet Parser 测试完成")


if __name__ == "__main__":
    _test_parser()
