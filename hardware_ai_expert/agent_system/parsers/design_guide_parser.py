"""
Design Guide 解析器

功能：
  1. 从 PDF/Markdown/TXT 提取文本
  2. 按章节智能切片（保持上下文完整性）
  3. 主题分类（I2C/Power/PCIe/等）
  4. 输出 KnowledgeChunk 列表

对应技术方案 Phase 1
"""

from __future__ import annotations

import re
import os
import hashlib
import logging
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

@dataclass
class DesignGuideChunk:
    """设计指南切片"""
    content: str
    title: str = ""                    # 章节标题
    section_level: int = 0             # 标题层级 (#=1, ##=2, ###=3)
    category: str = "general"          # 主题分类
    page: int = 0                      # 来源页码
    content_hash: str = ""             # 内容哈希
    char_count: int = field(init=False) # 字符数
    
    def __post_init__(self):
        self.char_count = len(self.content)
        if not self.content_hash:
            self.content_hash = hashlib.md5(self.content.encode()).hexdigest()[:16]


# ============================================================
# 主题分类器
# ============================================================

class TopicClassifier:
    """
    基于关键词匹配的主题分类器
    
    类别: i2c, power, pcie, spi, gpio, thermal, signal_integrity, general
    """
    
    TOPIC_KEYWORDS = {
        "i2c": ["i2c", "i²c", "inter-integrated circuit", "smbus", "twi",
                "上拉电阻", "pull-up", "clock stretching", "ack", "nack"],
        "power": ["power", "电源", "ldo", "buck", "boost", "dcdc", "dc-dc",
                  "稳压", "voltage regulator", "电流", "current", "功耗", "power dissipation",
                  "热设计", "thermal design", "散热", "heatsink", "温升"],
        "pcie": ["pcie", "pci express", "pci-e", "lane", "gen3", "gen4", "gen5",
                 "差分对", "differential pair", "眼图", "eye diagram"],
        "spi": ["spi", "serial peripheral", "mosi", "miso", "sck", "cs", "chip select"],
        "gpio": ["gpio", "通用输入输出", "general purpose io", "中断", "interrupt",
                 "edge trigger", "level trigger"],
        "thermal": ["thermal", "温度", "temperature", "结温", "junction temperature",
                    "θja", "theta-ja", "热阻", "thermal resistance"],
        "signal_integrity": ["signal integrity", "信号完整性", "阻抗", "impedance",
                             "反射", "reflection", "串扰", "crosstalk", "端接", "termination",
                             "stub", "走线长度", "trace length", "等长", "length matching"],
        "usb": ["usb", "type-c", "type c", "differential pair", "ss tx", "ss rx",
                "vbus", "cc pin", "pd", "power delivery"],
        "ddr": ["ddr", "dram", "sdram", "memory", "地址线", "address line",
                "数据线", "data line", "dm", "dqs", "端接", "termination"],
    }
    
    @classmethod
    def classify(cls, text: str) -> str:
        """
        根据关键词匹配分类主题
        
        返回得分最高的类别，默认 general
        """
        text_lower = text.lower()
        scores = {}
        
        for topic, keywords in cls.TOPIC_KEYWORDS.items():
            score = 0
            for kw in keywords:
                count = text_lower.count(kw.lower())
                if count > 0:
                    # 基础权重
                    weight = 2 if len(kw) > 5 else 1
                    # 标题行（以 # 开头）中的关键词权重翻倍
                    for line in text.split('\n'):
                        if line.strip().startswith('#') and kw.lower() in line.lower():
                            weight *= 3
                            break
                    score += count * weight
            scores[topic] = score
        
        if not scores or max(scores.values()) == 0:
            return "general"
        
        return max(scores, key=scores.get)


# ============================================================
# 文本提取器
# ============================================================

class TextExtractor:
    """从多种格式提取纯文本"""
    
    @staticmethod
    def extract(file_path: str) -> str:
        """
        根据文件扩展名选择合适的提取方式
        
        支持: .pdf, .md, .txt, .markdown
        """
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".pdf":
            return TextExtractor._extract_pdf(file_path)
        elif ext in [".md", ".markdown", ".txt"]:
            return TextExtractor._extract_text_file(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")
    
    @staticmethod
    def _extract_pdf(file_path: str) -> str:
        """使用 PyMuPDF 提取 PDF 文本"""
        try:
            import fitz
            doc = fitz.open(file_path)
            texts = []
            for page in doc:
                texts.append(page.get_text())
            doc.close()
            return "\n".join(texts)
        except ImportError:
            logger.error("PyMuPDF (fitz) not installed. Cannot extract PDF.")
            raise
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            raise
    
    @staticmethod
    def _extract_text_file(file_path: str) -> str:
        """读取文本文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


# ============================================================
# 智能切片器
# ============================================================

class SmartChunker:
    """
    智能文本切片器
    
    策略：
    - Markdown 格式：按标题层级切分
    - 纯文本：按段落 + 长度限制切分
    - 每个切片 500-1500 字符
    - 保留章节层级关系
    """
    
    MIN_CHUNK_SIZE = 300      # 最小切片大小
    MAX_CHUNK_SIZE = 1500     # 最大切片大小
    OVERLAP_SIZE = 100        # 切片间重叠（保持上下文）
    
    def __init__(self):
        self.classifier = TopicClassifier()
    
    def chunk(self, text: str, source_id: str = "") -> List[DesignGuideChunk]:
        """
        将文本切分为多个 KnowledgeChunk
        
        Args:
            text: 原始文本
            source_id: 来源文档标识
        
        Returns:
            DesignGuideChunk 列表
        """
        # 1. 检测是否为 Markdown 格式
        if self._is_markdown(text):
            chunks = self._chunk_markdown(text)
        else:
            chunks = self._chunk_plain_text(text)
        
        # 2. 分类每个切片
        for chunk in chunks:
            chunk.category = self.classifier.classify(chunk.content)
        
        logger.info(f"Chunked '{source_id}' into {len(chunks)} chunks")
        return chunks
    
    def _is_markdown(self, text: str) -> bool:
        """检测文本是否为 Markdown 格式"""
        # 检查是否有 Markdown 标题语法
        header_pattern = re.compile(r"^#{1,6}\s+", re.MULTILINE)
        return len(header_pattern.findall(text[:5000])) >= 2
    
    def _chunk_markdown(self, text: str) -> List[DesignGuideChunk]:
        """
        按 Markdown 标题层级切分
        
        策略：
        - 以 # 或 ## 作为切分边界
        - ### 及以下作为子内容合并到上级
        - 超长章节内部再按段落切分
        """
        chunks = []
        
        # 匹配 Markdown 标题: # Title 或 ## Title
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        
        # 找到所有标题位置
        matches = list(header_pattern.finditer(text))
        
        if not matches:
            # 没有标题，按纯文本处理
            return self._chunk_plain_text(text)
        
        for i, match in enumerate(matches):
            level = len(match.group(1))
            title = match.group(2).strip()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            
            content = text[start:end].strip()
            
            # 如果内容过长，进一步切分
            if len(content) > self.MAX_CHUNK_SIZE:
                sub_chunks = self._split_long_content(content, title, level)
                chunks.extend(sub_chunks)
            else:
                chunks.append(DesignGuideChunk(
                    content=content,
                    title=title,
                    section_level=level,
                ))
        
        return chunks
    
    def _chunk_plain_text(self, text: str) -> List[DesignGuideChunk]:
        """
        纯文本切分
        
        策略：
        - 按段落切分
        - 合并短段落直到达到最小大小
        - 超长段落按句子切分
        """
        chunks = []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        current_content = []
        current_size = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            # 如果当前累积内容 + 新段落超过最大大小，先保存当前
            if current_size + para_size > self.MAX_CHUNK_SIZE and current_size >= self.MIN_CHUNK_SIZE:
                chunks.append(DesignGuideChunk(
                    content="\n\n".join(current_content),
                    title=self._extract_title(current_content[0]),
                    section_level=0,
                ))
                # 保留重叠部分
                current_content = current_content[-1:] if len(current_content) > 1 else []
                current_size = sum(len(p) for p in current_content)
            
            current_content.append(para)
            current_size += para_size
        
        # 保存最后一部分
        if current_content:
            chunks.append(DesignGuideChunk(
                content="\n\n".join(current_content),
                title=self._extract_title(current_content[0]),
                section_level=0,
            ))
        
        return chunks
    
    def _split_long_content(self, content: str, title: str, level: int) -> List[DesignGuideChunk]:
        """将超长内容按段落进一步切分"""
        chunks = []
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        
        current_content = []
        current_size = 0
        chunk_index = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            if current_size + para_size > self.MAX_CHUNK_SIZE and current_size >= self.MIN_CHUNK_SIZE:
                chunk_title = f"{title} (part {chunk_index + 1})" if chunk_index > 0 else title
                chunks.append(DesignGuideChunk(
                    content="\n\n".join(current_content),
                    title=chunk_title,
                    section_level=level,
                ))
                chunk_index += 1
                # 保留最后一段作为重叠
                current_content = [current_content[-1]] if current_content else []
                current_size = sum(len(p) for p in current_content)
            
            current_content.append(para)
            current_size += para_size
        
        if current_content:
            chunk_title = f"{title} (part {chunk_index + 1})" if chunk_index > 0 else title
            chunks.append(DesignGuideChunk(
                content="\n\n".join(current_content),
                title=chunk_title,
                section_level=level,
            ))
        
        return chunks
    
    @staticmethod
    def _extract_title(first_paragraph: str) -> str:
        """从第一段提取标题"""
        # 如果是 Markdown 标题，提取标题文本
        match = re.match(r"^#{1,6}\s+(.+)$", first_paragraph.strip())
        if match:
            return match.group(1).strip()
        # 否则返回前 50 字符作为标题
        return first_paragraph.strip()[:50] + "..." if len(first_paragraph) > 50 else first_paragraph.strip()


# ============================================================
# Design Guide 解析器
# ============================================================

class DesignGuideParser:
    """
    设计指南解析器
    
    支持格式: PDF, Markdown, TXT
    输出: DesignGuideChunk 列表
    """
    
    def __init__(self):
        self.extractor = TextExtractor()
        self.chunker = SmartChunker()
    
    def parse(self, file_path: str, metadata: Optional[dict] = None) -> List[DesignGuideChunk]:
        """
        解析设计指南文件
        
        Args:
            file_path: 文件路径
            metadata: 可选元数据 {source_id, project, category}
        
        Returns:
            DesignGuideChunk 列表
        """
        logger.info(f"Parsing Design Guide: {file_path}")
        
        # 1. 提取文本
        text = self.extractor.extract(file_path)
        
        # 2. 智能切片
        source_id = metadata.get("source_id", os.path.basename(file_path)) if metadata else os.path.basename(file_path)
        chunks = self.chunker.chunk(text, source_id)
        
        logger.info(f"Parsed {len(chunks)} chunks from {file_path}")
        return chunks
    
    def parse_text(self, text: str, source_id: str = "") -> List[DesignGuideChunk]:
        """
        直接从文本解析（用于测试或在线输入）
        """
        return self.chunker.chunk(text, source_id)


# ============================================================
# 测试
# ============================================================

def _test_parser():
    """测试 Design Guide 解析器"""
    print("=" * 60)
    print("Design Guide Parser 测试")
    print("=" * 60)
    
    # 测试 Markdown 文本
    test_md = """
# USB3.0 设计指南

## 1. 差分对设计

USB3.0 SuperSpeed 差分对应控制阻抗在 90Ω ±10%。
走线应尽量短，避免过孔和 stubs。
差分对间距应保持恒定，推荐 2 倍线宽。

## 2. ESD 保护

USB 接口必须添加 ESD 保护器件。
推荐选择容值 <0.5pF 的低容 ESD。
保护器件应靠近连接器放置，距离不超过 5mm。

## 3. 电源设计

VBUS 需要提供 5V/900mA 的供电能力。
建议添加过流保护（OCP）电路。
PD 快充需要额外的 CC 线检测电路。

### 3.1 VBUS 去耦

VBUS 引脚需要 10uF + 100nF 陶瓷电容并联去耦。
电容应靠近引脚放置。

## 4. 信号完整性

TX/RX 差分对应做等长处理，误差控制在 5mil 以内。
避免与高速时钟线平行走线。
参考平面应完整，避免跨分割。
"""
    
    parser = DesignGuideParser()
    chunks = parser.parse_text(test_md, "test_usb3_guide")
    
    print(f"\n[1/3] Markdown 切片测试")
    print(f"  切片数: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"\n  Chunk {i+1}: {chunk.title}")
        print(f"    层级: {chunk.section_level} | 分类: {chunk.category} | 字符: {chunk.char_count}")
        print(f"    预览: {chunk.content[:80]}...")
    
    # 测试分类器
    print(f"\n[2/3] 主题分类测试")
    classifier = TopicClassifier()
    test_cases = [
        ("I2C bus requires 4.7K pull-up resistors", "i2c"),
        ("LDO output voltage should be 1.8V with decoupling capacitor", "power"),
        ("PCIe Gen3 differential pair impedance 85Ω", "pcie"),
        ("General description of the board layout", "general"),
    ]
    for text, expected in test_cases:
        result = classifier.classify(text)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{text[:40]}...' → {result} (expect: {expected})")
    
    # 测试纯文本切分
    print(f"\n[3/3] 纯文本切片测试")
    test_plain = "Paragraph 1 about I2C design. " * 50 + "\n\n" + "Paragraph 2 about power supply. " * 50 + "\n\n" + "Paragraph 3 about signal integrity. " * 50
    chunks = parser.parse_text(test_plain, "test_plain")
    print(f"  切片数: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i+1}: {chunk.category}, {chunk.char_count} chars")
    
    print("\n✅ Design Guide Parser 测试完成")


if __name__ == "__main__":
    _test_parser()