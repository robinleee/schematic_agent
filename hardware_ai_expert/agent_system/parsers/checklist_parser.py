# -*- coding: utf-8 -*-
"""
Checklist 解析器

功能：
  1. 解析 Excel/CSV 格式的检查清单
  2. 转换为结构化审查规则
  3. 支持标准模板格式

对应技术方案 Phase 2
"""

from __future__ import annotations

import os
import re
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

class Severity(Enum):
    """规则严重级别"""
    ERROR = "ERROR"       # 必须修复
    WARNING = "WARNING"   # 建议修复
    INFO = "INFO"         # 参考信息


@dataclass
class ChecklistRule:
    """审查规则"""
    rule_id: str                    # 规则唯一标识
    name: str                       # 规则名称
    category: str = "general"       # 分类（i2c/power/pcie/等）
    target: str = ""                # 适用器件/场景
    check_item: str = ""            # 检查项描述
    pass_condition: str = ""        # 通过条件（可执行表达式或自然语言）
    severity: Severity = Severity.WARNING
    source_checklist: str = ""      # 来源清单
    reference: str = ""             # 参考文档/标准
    page: int = 0                   # 来源页码
    enabled: bool = True            # 是否启用
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "category": self.category,
            "target": self.target,
            "check_item": self.check_item,
            "pass_condition": self.pass_condition,
            "severity": self.severity.value,
            "source_checklist": self.source_checklist,
            "reference": self.reference,
            "page": self.page,
            "enabled": self.enabled,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChecklistRule":
        """从字典创建"""
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            category=data.get("category", "general"),
            target=data.get("target", ""),
            check_item=data.get("check_item", ""),
            pass_condition=data.get("pass_condition", ""),
            severity=Severity(data.get("severity", "WARNING")),
            source_checklist=data.get("source_checklist", ""),
            reference=data.get("reference", ""),
            page=data.get("page", 0),
            enabled=data.get("enabled", True),
        )


# ============================================================
# 列名映射
# ============================================================

COLUMN_MAPPINGS = {
    # 规则ID
    "规则ID": "rule_id",
    "Rule ID": "rule_id",
    "rule_id": "rule_id",
    "ID": "rule_id",
    # 规则名称
    "规则名称": "name",
    "Rule Name": "name",
    "name": "name",
    "名称": "name",
    # 分类
    "分类": "category",
    "Category": "category",
    "category": "category",
    "类别": "category",
    # 适用器件
    "适用器件": "target",
    "Target": "target",
    "target": "target",
    "适用场景": "target",
    # 检查项
    "检查项": "check_item",
    "Check Item": "check_item",
    "check_item": "check_item",
    "检查内容": "check_item",
    # 通过条件
    "通过条件": "pass_condition",
    "Pass Condition": "pass_condition",
    "pass_condition": "pass_condition",
    "条件": "pass_condition",
    # 严重级别
    "严重级别": "severity",
    "Severity": "severity",
    "severity": "severity",
    "级别": "severity",
    # 参考
    "参考": "reference",
    "Reference": "reference",
    "reference": "reference",
    "参考文档": "reference",
}


def normalize_column_name(col: str) -> str:
    """标准化列名"""
    col = col.strip()
    return COLUMN_MAPPINGS.get(col, col)


# ============================================================
# Checklist 解析器
# ============================================================

class ChecklistParser:
    """
    检查清单解析器
    
    支持格式: .xlsx, .xls, .csv
    """
    
    def __init__(self):
        self.topic_keywords = {
            "i2c": ["i2c", "i²c", "smbus", "上拉", "pull-up"],
            "power": ["电源", "power", "ldo", "buck", "dcdc", "去耦", "decoupling"],
            "pcie": ["pcie", "pci express", "差分对", "differential"],
            "usb": ["usb", "type-c", "vbus", "pd"],
            "ddr": ["ddr", "dram", "内存", "memory"],
            "gpio": ["gpio", "中断", "interrupt"],
            "thermal": ["温度", "thermal", "散热", "heatsink"],
            "signal_integrity": ["信号完整性", "阻抗", "impedance", "端接", "termination"],
        }
    
    def parse(self, file_path: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChecklistRule]:
        """
        解析检查清单文件
        
        Args:
            file_path: 文件路径
            metadata: 可选元数据 {source_id, project}
        
        Returns:
            ChecklistRule 列表
        """
        logger.info(f"Parsing Checklist: {file_path}")
        
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext in [".xlsx", ".xls"]:
            df = self._read_excel(file_path)
        elif ext == ".csv":
            df = self._read_csv(file_path)
        else:
            raise ValueError(f"Unsupported checklist format: {ext}")
        
        if df is None or df.empty:
            logger.warning(f"Empty checklist: {file_path}")
            return []
        
        # 标准化列名（支持 pandas 和 SimpleDataFrame）
        if hasattr(df, 'columns'):
            old_columns = list(df.columns)
            new_columns = [normalize_column_name(str(col)) for col in old_columns]
            df.columns = new_columns
            
            # 对于 SimpleDataFrame，同时更新行字典的键
            if hasattr(df, 'rows'):
                for row in df.rows:
                    for old_key, new_key in zip(old_columns, new_columns):
                        if old_key in row and old_key != new_key:
                            row[new_key] = row.pop(old_key)
        
        # 转换为规则
        rules = []
        source_id = metadata.get("source_id", os.path.basename(file_path)) if metadata else os.path.basename(file_path)
        
        # 迭代行（支持 pandas iterrows 和 SimpleDataFrame）
        row_num = 0
        for item in df:
            row_num += 1
            # pandas iterrows 返回 (index, row)，SimpleDataFrame 也返回 (index, row)
            if isinstance(item, tuple) and len(item) == 2:
                _, row = item
            else:
                row = item
            rule = self._row_to_rule(row, source_id, row_num)
            if rule:
                rules.append(rule)
        
        logger.info(f"Parsed {len(rules)} rules from {file_path}")
        return rules
    
    def _read_excel(self, file_path: str):
        """读取 Excel 文件"""
        try:
            import pandas as pd
            return pd.read_excel(file_path)
        except ImportError:
            logger.error("pandas not installed. Cannot read Excel.")
            raise
        except Exception as e:
            logger.error(f"Excel read failed: {e}")
            raise
    
    def _read_csv(self, file_path: str):
        """读取 CSV 文件（标准库实现，不依赖 pandas）"""
        try:
            import csv
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if not rows:
                return None
            
            # 直接使用字典列表，提供 DataFrame-like 接口
            class SimpleDataFrame:
                def __init__(self, rows):
                    self.rows = rows
                    self.columns = list(rows[0].keys()) if rows else []
                
                def __iter__(self):
                    for i, row in enumerate(self.rows):
                        yield i, row
                
                @property
                def empty(self):
                    return len(self.rows) == 0
            
            return SimpleDataFrame(rows)
            
        except ImportError:
            logger.error("csv module not available.")
            raise
        except Exception as e:
            logger.error(f"CSV read failed: {e}")
            raise
    
    def _row_to_rule(self, row, source_id: str, row_num: int) -> Optional[ChecklistRule]:
        """将 DataFrame 行转换为规则"""
        # 获取规则ID
        rule_id = self._get_cell(row, "rule_id", f"{source_id}_R{row_num:03d}")
        name = self._get_cell(row, "name", "")
        
        if not name:
            # 尝试用检查项作为名称
            name = self._get_cell(row, "check_item", "")
        
        if not name:
            return None  # 空行跳过
        
        # 分类（自动推断或从列读取）
        category = self._get_cell(row, "category", "")
        if not category:
            category = self._infer_category(name + " " + self._get_cell(row, "check_item", ""))
        
        # 严重级别
        severity_str = self._get_cell(row, "severity", "WARNING").upper()
        try:
            severity = Severity(severity_str)
        except ValueError:
            severity = Severity.WARNING
        
        return ChecklistRule(
            rule_id=str(rule_id),
            name=str(name),
            category=category,
            target=self._get_cell(row, "target", ""),
            check_item=self._get_cell(row, "check_item", ""),
            pass_condition=self._get_cell(row, "pass_condition", ""),
            severity=severity,
            source_checklist=source_id,
            reference=self._get_cell(row, "reference", ""),
            page=0,
        )
    
    def _get_cell(self, row, col_name: str, default: str = "") -> str:
        """安全获取单元格值"""
        try:
            val = row[col_name] if hasattr(row, col_name) else (row[col_name] if isinstance(row, dict) else None)
            if val is None:
                return default
            # 处理 pandas 的 NaN
            try:
                import pandas as pd
                if pd.isna(val):
                    return default
            except ImportError:
                pass
            return str(val).strip()
        except (KeyError, AttributeError):
            return default
    
    def _infer_category(self, text: str) -> str:
        """从文本推断分类"""
        text_lower = text.lower()
        scores = {}
        
        for topic, keywords in self.topic_keywords.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[topic] = score
        
        if not scores:
            return "general"
        
        return max(scores, key=scores.get)
    
    @staticmethod
    def generate_template() -> str:
        """
        生成标准模板 CSV 内容
        
        用户可下载此模板填写检查清单
        """
        return """规则ID,规则名称,分类,适用器件,检查项,通过条件,严重级别,参考
RULE_001,I2C上拉电阻检查,i2c,所有I2C器件,I2C总线上拉电阻应在1KΩ~10KΩ之间,1K <= pull_up <= 10K,WARNING,I2C Spec
RULE_002,USB差分对阻抗,usb,USB3.0接口,USB3.0差分对阻抗应为90Ω±10%,85 <= impedance <= 95,ERROR,USB3.0 Design Guide
RULE_003,LDO去耦电容,power,LDO稳压器,LDO输出应有1uF+100nF陶瓷电容去耦,capacitance >= 1uF,WARNING,App Note AN-001
"""


# ============================================================
# 测试
# ============================================================

def _test_parser():
    """测试 Checklist 解析器"""
    print("=" * 60)
    print("Checklist Parser 测试")
    print("=" * 60)
    
    import tempfile
    
    # 1. 测试 CSV 解析
    print("\n[1/3] CSV 解析测试")
    csv_content = ChecklistParser.generate_template()
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
        temp_path = f.name
    
    try:
        parser = ChecklistParser()
        rules = parser.parse(temp_path, {"source_id": "test_checklist"})
        
        print(f"  解析到 {len(rules)} 条规则")
        for rule in rules:
            print(f"  - {rule.rule_id}: [{rule.category}] {rule.name} ({rule.severity.value})")
        
        assert len(rules) == 3, "应解析出 3 条规则"
        assert rules[0].category == "i2c", "第一条应为 i2c"
        assert rules[1].category == "usb", "第二条应为 usb"
        assert rules[2].category == "power", "第三条应为 power"
        
    finally:
        os.unlink(temp_path)
    
    # 2. 测试分类推断
    print("\n[2/3] 分类推断测试")
    test_cases = [
        ("I2C bus pull-up resistor", "i2c"),
        ("USB Type-C VBUS decoupling", "usb"),
        ("LDO output capacitor selection", "power"),
        ("General layout guideline", "general"),
    ]
    
    for text, expected in test_cases:
        result = parser._infer_category(text)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{text}' → {result} (expect: {expected})")
    
    # 3. 测试模板生成
    print("\n[3/3] 模板生成测试")
    template = ChecklistParser.generate_template()
    assert "规则ID" in template, "模板应包含规则ID列"
    assert "RULE_001" in template, "模板应包含示例规则"
    print("  ✅ 模板生成成功")
    
    print("\n✅ Checklist Parser 测试完成")


if __name__ == "__main__":
    _test_parser()
