"""
统一文档处理器

提供统一的文档处理入口，根据文档类型分发到对应的解析器。

对应技术方案 Phase 1
"""

from __future__ import annotations

import os
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from .design_guide_parser import DesignGuideParser, DesignGuideChunk

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

@dataclass
class ProcessingResult:
    """文档处理结果"""
    doc_type: str
    source_file: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[Any] = field(default_factory=list)
    parameters: List[Any] = field(default_factory=list)
    rules: List[Any] = field(default_factory=list)
    processing_time_ms: int = 0
    error: Optional[str] = None
    
    def is_success(self) -> bool:
        return self.error is None
    
    def get_summary(self) -> str:
        """获取处理摘要"""
        if self.error:
            return f"❌ 处理失败: {self.error}"
        
        parts = [f"✅ 处理完成 ({self.doc_type})"]
        if self.chunks:
            parts.append(f"  切片: {len(self.chunks)} 个")
        if self.parameters:
            parts.append(f"  参数: {len(self.parameters)} 个")
        if self.rules:
            parts.append(f"  规则: {len(self.rules)} 个")
        return "\n".join(parts)


# ============================================================
# 文档处理器
# ============================================================

class DocumentProcessor:
    """
    统一文档处理器
    
    根据文档类型自动选择对应的解析器，输出统一格式的处理结果。
    
    支持的文档类型:
    - datasheet: Datasheet (器件规格书)
    - design_guide: Design Guide (设计指南)
    - checklist: Checklist (检查清单)
    - expert_note: Expert Note (经验文档)
    """
    
    def __init__(self):
        self.parsers = {
            "design_guide": DesignGuideParser(),
            "checklist": None,  # 延迟导入，避免循环依赖
            "expert_note": DesignGuideParser(),  # 复用文本切片
        }
    
    def process(self, file_path: str, doc_type: str, metadata: Optional[Dict[str, Any]] = None) -> ProcessingResult:
        """
        处理文档
        
        Args:
            file_path: 上传文件路径
            doc_type: 文档类型 (datasheet/design_guide/checklist/expert_note)
            metadata: 可选元数据 {
                source_id: 文档标识,
                mpn: 关联器件型号,
                project: 关联项目,
                category: 知识分类,
                uploader: 上传人
            }
        
        Returns:
            ProcessingResult
        """
        start_time = datetime.now()
        metadata = metadata or {}
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return ProcessingResult(
                doc_type=doc_type,
                source_file=file_path,
                error=f"文件不存在: {file_path}"
            )
        
        try:
            # 根据类型分发
            if doc_type == "design_guide":
                result = self._process_design_guide(file_path, metadata)
            elif doc_type == "datasheet":
                result = self._process_datasheet(file_path, metadata)
            elif doc_type == "checklist":
                result = self._process_checklist(file_path, metadata)
            elif doc_type == "expert_note":
                result = self._process_expert_note(file_path, metadata)
            else:
                return ProcessingResult(
                    doc_type=doc_type,
                    source_file=file_path,
                    error=f"不支持的文档类型: {doc_type}"
                )
            
            # 计算处理时间
            elapsed = (datetime.now() - start_time).total_seconds() * 1000
            result.processing_time_ms = int(elapsed)
            
            return result
            
        except Exception as e:
            logger.error(f"Document processing failed: {e}", exc_info=True)
            return ProcessingResult(
                doc_type=doc_type,
                source_file=file_path,
                metadata=metadata,
                error=str(e)
            )
    
    def _process_design_guide(self, file_path: str, metadata: Dict[str, Any]) -> ProcessingResult:
        """处理设计指南"""
        parser = self.parsers["design_guide"]
        chunks = parser.parse(file_path, metadata)
        
        return ProcessingResult(
            doc_type="design_guide",
            source_file=file_path,
            metadata=metadata,
            chunks=chunks,
        )
    
    def _process_datasheet(self, file_path: str, metadata: Dict[str, Any]) -> ProcessingResult:
        """处理 Datasheet（复用现有 DatasheetParser）"""
        try:
            from ..datasheet_parser import DatasheetParser
            parser = DatasheetParser()
            component = parser.parse(file_path, metadata.get("mpn", ""))
            
            return ProcessingResult(
                doc_type="datasheet",
                source_file=file_path,
                metadata=metadata,
                parameters=component.parameters,
            )
        except Exception as e:
            logger.error(f"Datasheet processing failed: {e}")
            return ProcessingResult(
                doc_type="datasheet",
                source_file=file_path,
                metadata=metadata,
                error=f"Datasheet 解析失败: {e}"
            )
    
    def _process_checklist(self, file_path: str, metadata: Dict[str, Any]) -> ProcessingResult:
        """处理检查清单"""
        try:
            from .checklist_parser import ChecklistParser
            parser = ChecklistParser()
            rules = parser.parse(file_path, metadata)
            
            return ProcessingResult(
                doc_type="checklist",
                source_file=file_path,
                metadata=metadata,
                rules=rules,
            )
        except Exception as e:
            logger.error(f"Checklist processing failed: {e}")
            return ProcessingResult(
                doc_type="checklist",
                source_file=file_path,
                metadata=metadata,
                error=f"Checklist 解析失败: {e}"
            )
    
    def _process_expert_note(self, file_path: str, metadata: Dict[str, Any]) -> ProcessingResult:
        """处理经验文档（复用 DesignGuideParser 的文本切片）"""
        parser = self.parsers["design_guide"]
        chunks = parser.parse(file_path, metadata)
        
        return ProcessingResult(
            doc_type="expert_note",
            source_file=file_path,
            metadata=metadata,
            chunks=chunks,
        )
    
    def get_supported_types(self) -> Dict[str, str]:
        """获取支持的文档类型说明"""
        return {
            "datasheet": "Datasheet (器件规格书) - 提取器件参数",
            "design_guide": "Design Guide (设计指南) - 切片向量化",
            "checklist": "Checklist (检查清单) - 结构化规则（Phase 2）",
            "expert_note": "Expert Note (经验文档) - 切片向量化",
        }


# ============================================================
# 便捷函数
# ============================================================

def process_document(file_path: str, doc_type: str, **metadata) -> ProcessingResult:
    """
    便捷函数：处理文档
    
    Example:
        result = process_document(
            "/path/to/guide.pdf",
            "design_guide",
            source_id="usb3_design_guide",
            project="project_alpha"
        )
    """
    processor = DocumentProcessor()
    return processor.process(file_path, doc_type, metadata)


# ============================================================
# 测试
# ============================================================

def _test_processor():
    """测试文档处理器"""
    print("=" * 60)
    print("Document Processor 测试")
    print("=" * 60)
    
    processor = DocumentProcessor()
    
    # 1. 测试支持的类型
    print("\n[1/3] 支持的文档类型:")
    for doc_type, desc in processor.get_supported_types().items():
        print(f"  - {doc_type}: {desc}")
    
    # 2. 测试设计指南处理
    print("\n[2/3] Design Guide 处理测试:")
    
    # 创建一个临时测试文件
    test_content = """# 测试设计指南

## I2C 设计要点

I2C 总线需要上拉电阻，推荐值 4.7KΩ。
时钟频率标准模式 100KHz，快速模式 400KHz。

## 电源设计

LDO 输出需要 1uF + 100nF 陶瓷电容去耦。
输入电容应大于 10uF。
"""
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(test_content)
        temp_path = f.name
    
    try:
        result = processor.process(temp_path, "design_guide", {
            "source_id": "test_guide",
            "project": "test",
            "category": "i2c"
        })
        
        print(f"  状态: {'✅ 成功' if result.is_success() else '❌ 失败'}")
        if result.is_success():
            print(f"  切片数: {len(result.chunks)}")
            for i, chunk in enumerate(result.chunks):
                print(f"    Chunk {i+1}: [{chunk.category}] {chunk.title} ({chunk.char_count} chars)")
        else:
            print(f"  错误: {result.error}")
    finally:
        os.unlink(temp_path)
    
    # 3. 测试不存在的文件
    print("\n[3/3] 错误处理测试:")
    result = processor.process("/nonexistent/file.pdf", "design_guide")
    print(f"  不存在的文件: {'✅ 正确报错' if result.error else '❌ 未报错'}")
    
    print("\n✅ Document Processor 测试完成")


if __name__ == "__main__":
    _test_processor()