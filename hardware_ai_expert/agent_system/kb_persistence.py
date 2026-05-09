# -*- coding: utf-8 -*-
"""
知识库持久化模块

使用 JSON 文件存储文档记录，实现：
- 文档记录持久化
- 待审核队列持久化
- 统计信息持久化

对应技术方案 Phase 4 持久化需求
"""

from __future__ import annotations

import os
import json
import uuid
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

# 默认存储路径
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "kb"
)


@dataclass
class DocumentRecord:
    """文档记录"""
    doc_id: str
    filename: str
    doc_type: str  # datasheet/design_guide/checklist/expert_note
    status: str = "uploaded"  # uploaded/processing/pending_review/stored/rejected
    metadata: Dict[str, Any] = field(default_factory=dict)
    result_summary: Dict[str, Any] = field(default_factory=dict)
    uploaded_at: str = ""
    reviewed_at: Optional[str] = None
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if not self.uploaded_at:
            self.uploaded_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DocumentRecord:
        return cls(**data)


class KBPersistence:
    """
    知识库持久化管理器

    使用 JSON 文件存储，适合中小规模数据。
    大规模场景可迁移到 SQLite/PostgreSQL。
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)

        self.documents_file = os.path.join(self.data_dir, "documents.json")
        self._documents: List[DocumentRecord] = []
        self._load()

    def _load(self):
        """从文件加载数据"""
        if os.path.exists(self.documents_file):
            try:
                with open(self.documents_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._documents = [DocumentRecord.from_dict(d) for d in data]
                logger.info(f"Loaded {len(self._documents)} documents from {self.documents_file}")
            except Exception as e:
                logger.error(f"Failed to load documents: {e}")
                self._documents = []
        else:
            self._documents = []

    def _save(self):
        """保存数据到文件"""
        try:
            with open(self.documents_file, "w", encoding="utf-8") as f:
                json.dump([d.to_dict() for d in self._documents], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save documents: {e}")

    def add_document(self, filename: str, doc_type: str, metadata: dict = None) -> DocumentRecord:
        """
        添加文档记录

        Args:
            filename: 文件名
            doc_type: 文档类型
            metadata: 元数据

        Returns:
            DocumentRecord
        """
        doc = DocumentRecord(
            doc_id=str(uuid.uuid4())[:8],
            filename=filename,
            doc_type=doc_type,
            metadata=metadata or {},
            status="uploaded",
        )
        self._documents.append(doc)
        self._save()
        logger.info(f"Added document: {doc.doc_id} ({filename})")
        return doc

    def update_status(self, doc_id: str, status: str, **kwargs) -> bool:
        """
        更新文档状态

        Args:
            doc_id: 文档 ID
            status: 新状态
            **kwargs: 其他字段更新

        Returns:
            是否成功
        """
        for doc in self._documents:
            if doc.doc_id == doc_id:
                doc.status = status
                for key, value in kwargs.items():
                    if hasattr(doc, key):
                        setattr(doc, key, value)
                self._save()
                return True
        return False

    def update_result(self, doc_id: str, result_summary: dict) -> bool:
        """更新处理结果摘要"""
        for doc in self._documents:
            if doc.doc_id == doc_id:
                doc.result_summary = result_summary
                self._save()
                return True
        return False

    def get_document(self, doc_id: str) -> Optional[DocumentRecord]:
        """获取单个文档"""
        for doc in self._documents:
            if doc.doc_id == doc_id:
                return doc
        return None

    def get_all_documents(self) -> List[DocumentRecord]:
        """获取所有文档"""
        return sorted(self._documents, key=lambda d: d.uploaded_at, reverse=True)

    def get_documents_by_status(self, status: str) -> List[DocumentRecord]:
        """按状态获取文档"""
        return [d for d in self._documents if d.status == status]

    def get_documents_by_type(self, doc_type: str) -> List[DocumentRecord]:
        """按类型获取文档"""
        return [d for d in self._documents if d.doc_type == doc_type]

    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        for i, doc in enumerate(self._documents):
            if doc.doc_id == doc_id:
                self._documents.pop(i)
                self._save()
                return True
        return False

    def get_stats(self) -> dict:
        """获取统计信息"""
        total = len(self._documents)
        status_counts = {}
        type_counts = {}

        for doc in self._documents:
            status_counts[doc.status] = status_counts.get(doc.status, 0) + 1
            type_counts[doc.doc_type] = type_counts.get(doc.doc_type, 0) + 1

        return {
            "total": total,
            "by_status": status_counts,
            "by_type": type_counts,
        }

    def get_pending_review(self) -> List[DocumentRecord]:
        """获取待审核文档"""
        return [d for d in self._documents if d.status == "pending_review"]

    def approve(self, doc_id: str, reviewer: str = "web_user", comment: str = "") -> bool:
        """批准文档"""
        return self.update_status(
            doc_id, "stored",
            reviewed_at=datetime.now().isoformat(),
            reviewer=reviewer,
            review_comment=comment,
        )

    def reject(self, doc_id: str, reviewer: str = "web_user", comment: str = "") -> bool:
        """拒绝文档"""
        return self.update_status(
            doc_id, "rejected",
            reviewed_at=datetime.now().isoformat(),
            reviewer=reviewer,
            review_comment=comment,
        )


# ============================================================
# 便捷函数
# ============================================================

_persistence_instance: Optional[KBPersistence] = None


def get_persistence() -> KBPersistence:
    """获取持久化实例（单例）"""
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = KBPersistence()
    return _persistence_instance


def reset_persistence():
    """重置持久化实例（用于测试）"""
    global _persistence_instance
    _persistence_instance = None


# ============================================================
# 测试
# ============================================================

def _test_persistence():
    """测试持久化模块"""
    print("=" * 60)
    print("KBPersistence 测试")
    print("=" * 60)

    # 使用临时目录测试
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    db = KBPersistence(tmp_dir)

    # 1. 添加文档
    print("\n[1/5] 添加文档")
    doc1 = db.add_document("usb3_guide.md", "design_guide", {"category": "usb"})
    doc2 = db.add_document("i2c_checklist.csv", "checklist", {"project": "board_a"})
    print(f"  添加: {doc1.doc_id} ({doc1.filename})")
    print(f"  添加: {doc2.doc_id} ({doc2.filename})")

    # 2. 更新状态
    print("\n[2/5] 更新状态")
    db.update_status(doc1.doc_id, "pending_review")
    print(f"  更新状态为 pending_review")

    # 3. 查询
    print("\n[3/5] 查询测试")
    all_docs = db.get_all_documents()
    print(f"  总文档数: {len(all_docs)}")

    pending = db.get_pending_review()
    print(f"  待审核: {len(pending)}")

    dg_docs = db.get_documents_by_type("design_guide")
    print(f"  DesignGuide: {len(dg_docs)}")

    # 4. 审批
    print("\n[4/5] 审批测试")
    db.approve(doc1.doc_id, reviewer="engineer_a", comment="Looks good")
    approved = db.get_documents_by_status("stored")
    print(f"  已入库: {len(approved)}")

    # 5. 统计
    print("\n[5/5] 统计测试")
    stats = db.get_stats()
    print(f"  统计: {stats}")

    # 清理
    import shutil
    shutil.rmtree(tmp_dir)
    print("\n✅ 持久化测试完成")


if __name__ == "__main__":
    _test_persistence()
