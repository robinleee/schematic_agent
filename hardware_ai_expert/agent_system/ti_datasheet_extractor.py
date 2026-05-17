"""
TI Datasheet AMR 提取器 — 从 TI PDF 提取 Absolute Maximum Ratings

用法:
    python3 ti_datasheet_extractor.py [--input-dir datasheets/] [--output ti_amr_data.yaml]
"""

from __future__ import annotations

import os
import re
import sys
import json
import yaml
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed. Run: pip install PyMuPDF")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class TIComponentAMR:
    mpn: str
    manufacturer: str = "Texas Instruments"
    amr: Dict[str, Any] = field(default_factory=dict)
    recommended_conditions: Dict[str, Any] = field(default_factory=dict)
    esd_ratings: Dict[str, Any] = field(default_factory=dict)
    pin_functions: List[Dict[str, str]] = field(default_factory=list)
    source_file: str = ""
    confidence: float = 0.0


def extract_ti_amr(pdf_path: str) -> Optional[TIComponentAMR]:
    """从 TI Datasheet PDF 提取 AMR 数据"""
    filename = os.path.basename(pdf_path)
    mpn = filename.replace(".pdf", "").upper()
    
    result = TIComponentAMR(mpn=mpn, source_file=filename)
    
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"Cannot open {pdf_path}: {e}")
        return None
    
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()
    
    # 提取 AMR (Absolute Maximum Ratings)
    amr_section = _extract_section(full_text, "Absolute Maximum Ratings")
    if amr_section:
        result.amr = _parse_table(amr_section)
        result.confidence = 0.8 if result.amr else 0.2
    
    # 提取 ESD Ratings
    esd_section = _extract_section(full_text, "ESD Ratings")
    if esd_section:
        result.esd_ratings = _parse_table(esd_section)
    
    # 提取 Recommended Operating Conditions
    rec_section = _extract_section(full_text, "Recommended Operating Conditions")
    if rec_section:
        result.recommended_conditions = _parse_table(rec_section)
    
    # 提取 Pin Functions
    pin_section = _extract_section(full_text, "Pin Configuration and Functions")
    if pin_section:
        result.pin_functions = _parse_pin_functions(pin_section)
    
    if not result.amr and not result.recommended_conditions:
        logger.warning(f"No AMR data extracted from {filename}")
        result.confidence = 0.1
    
    return result


def _extract_section(text: str, header: str) -> Optional[str]:
    """提取指定章节的文本"""
    # 找到章节标题（可能带编号如 "7.1 Absolute Maximum Ratings"）
    pattern = rf'(?:\d+\.?\d*\s+)?{re.escape(header)}[^\n]*\n'
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    
    if not matches:
        return None
    
    # 取最后一个匹配（正文页而非目录页）
    m = matches[-1]
    start = m.end()
    
    # 截取到下一个编号章节 (如 "7.2 ESD") 或 3000 chars
    chunk = text[start:start+4000]
    next_section = re.search(r'\n\s*\d+\.\d+\s+[A-Z]', chunk)
    if next_section:
        return chunk[:next_section.start()].strip()
    return chunk.strip()


def _parse_table(text: str) -> Dict[str, Any]:
    """解析 PDF 提取的表格文本（每列单独一行）"""
    result = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # 跳过注释和表头
        if line.startswith('(') or line in ('MIN', 'MAX', 'UNIT', 'VALUE'):
            i += 1
            continue
        
        # 模式1: 完整行 "Param  min  max  UNIT"
        m = re.match(r'^(.+?)\s+([–-]?\d+\.?\d*)\s+([–-]?\d+\.?\d*)\s+([VACFW°μ]+)\s*$', line)
        if m:
            param = m.group(1).strip()
            result[param] = {"min": m.group(2).replace('–','-'), "max": m.group(3).replace('–','-'), "unit": m.group(4)}
            i += 1
            continue
        
        # 模式2: 完整行 "Param  value  UNIT"
        m = re.match(r'^(.+?)\s+([–-]?\d+\.?\d*)\s+([VACFW°μ]+)\s*$', line)
        if m and not any(kw in m.group(1) for kw in ['Copyright','Product','Folder','Submit','Specifications','JEDEC']):
            param = m.group(1).strip()
            result[param] = {"value": m.group(2).replace('–','-'), "unit": m.group(3)}
            i += 1
            continue
        
        # 模式3: PDF 表格跨行 - 参数名在一行，数据在下几行
        # 例如:
        #   Voltage range
        #   VIN, PS/SYNC, EN, VSEL
        #   –0.3
        #   20
        #   V
        # 或者:
        #   VIN, PS/SYNC, EN, VSEL
        #   –0.3
        #   20
        #   V
        
        # 尝试向前看 5 行找数值
        param_parts = [line]
        j = i + 1
        while j < len(lines) and j < i + 3:
            # 如果下一行是数字，停止收集参数名
            if re.match(r'^[–-]?\d+\.?\d*$', lines[j]):
                break
            # 如果下一行是单位，说明参数名还没结束
            if lines[j] in ('V', 'A', 'W', '°C', 'µF', 'µH', 'mA', 'mV', 'pF', 'nF'):
                break
            param_parts.append(lines[j])
            j += 1
        
        # 现在从 j 开始尝试匹配数值序列
        nums = []
        k = j
        while k < len(lines) and k < j + 3:
            if re.match(r'^[–-]?\d+\.?\d*$', lines[k]):
                nums.append(lines[k].replace('–', '-'))
                k += 1
            else:
                break
        
        # k 应该指向单位
        if nums and k < len(lines) and lines[k] in ('V', 'A', 'W', '°C', 'µF', 'µH', 'mA', 'mV', 'pF', 'nF', 'kHz', 'MHz', 'µs', 'ns'):
            unit = lines[k]
            param = ' '.join(param_parts).strip()
            if len(nums) == 2:
                result[param] = {"min": nums[0], "max": nums[1], "unit": unit}
            elif len(nums) == 1:
                result[param] = {"value": nums[0], "unit": unit}
            i = k + 1
            continue
        
        # 没匹配到，跳过
        i += 1
    
    return result


def _parse_pin_functions(text: str) -> List[Dict[str, str]]:
    """解析 Pin Functions 表"""
    pins = []
    for m in re.finditer(r'^\s*(\w+)\s+(I|O|I/O|—)\s+(.+)$', text, re.MULTILINE):
        pins.append({
            "name": m.group(1),
            "type": m.group(2),
            "description": m.group(3).strip(),
        })
    return pins


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="datasheets/", help="PDF directory")
    parser.add_argument("--output", default="ti_amr_data.yaml", help="Output YAML")
    args = parser.parse_args()
    
    input_dir = args.input_dir
    if not os.path.isabs(input_dir):
        input_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", input_dir)
    
    results = []
    for f in sorted(os.listdir(input_dir)):
        if f.lower().endswith('.pdf'):
            path = os.path.join(input_dir, f)
            logger.info(f"Processing {f}...")
            amr = extract_ti_amr(path)
            if amr:
                results.append(amr)
                logger.info(f"  MPN={amr.mpn}, AMR params={len(amr.amr)}, Rec params={len(amr.recommended_conditions)}")
    
    # 写 YAML
    output = {
        "metadata": {
            "source": "ti_datasheet_extractor",
            "count": len(results),
        },
        "components": [],
    }
    
    for r in results:
        entry = {
            "mpn": r.mpn,
            "manufacturer": r.manufacturer,
            "confidence": r.confidence,
            "source_file": r.source_file,
        }
        if r.amr:
            entry["absolute_maximum_ratings"] = r.amr
        if r.recommended_conditions:
            entry["recommended_operating_conditions"] = r.recommended_conditions
        if r.esd_ratings:
            entry["esd_ratings"] = r.esd_ratings
        output["components"].append(entry)
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output)
    with open(out_path, "w") as f:
        yaml.dump(output, f, default_flow_style=False, allow_unicode=True)
    
    print(f"\n{'='*60}")
    print(f"TI Datasheet AMR 提取结果")
    print(f"{'='*60}")
    print(f"处理 PDF: {len([f for f in os.listdir(input_dir) if f.endswith('.pdf')])}")
    print(f"提取成功: {len(results)}")
    for r in results:
        print(f"  {r.mpn}: AMR={len(r.amr)} params, confidence={r.confidence:.1f}")
    print(f"\n输出: {out_path}")


if __name__ == "__main__":
    main()
