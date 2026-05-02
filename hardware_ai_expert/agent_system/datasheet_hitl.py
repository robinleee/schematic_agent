"""
Datasheet HITL 审批流

核心流程：
  PDF 解析 → 提取参数 → Pending Review → 工程师审批 → 落盘到 AMR 数据源

对应 PRD: Phase 4 - HITL 规则沉淀 + Datasheet 数据闭环
"""

from __future__ import annotations

import os
import yaml
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict
from enum import Enum

from agent_system.datasheet_parser import ExtractedComponent, DatasheetParameter, ParamType

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 数据模型
# ============================================================

class DatasheetReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


@dataclass
class DatasheetParamReview:
    """待审批的 Datasheet 参数项"""
    review_id: str
    mpn: str
    param_type: str           # ParamType.value
    param_name: str
    value: float
    unit: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    condition: str = ""
    source_text: str = ""
    confidence: float = 1.0
    extraction_method: str = ""

    # 审批状态
    status: str = DatasheetReviewStatus.PENDING.value
    reviewer: str = ""
    review_comment: str = ""
    reviewed_at: str = ""
    modified_value: Optional[float] = None
    modified_unit: Optional[str] = None

    # 元数据
    created_at: str = ""
    source_file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DatasheetParamReview":
        return cls(**d)


# ============================================================
# Datasheet HITL 管理器
# ============================================================

class DatasheetHITLManager:
    """
    Datasheet 参数 HITL 管理器

    管理从 PDF 提取的参数的审批流程：
      1. 接收 ExtractedComponent（PDF 解析结果）
      2. 每个参数生成一个 PendingReview 项
      3. 工程师审批（approve/reject/modify）
      4. 审批通过的参数落盘到 amr_data.yaml
    """

    AMR_DATA_DIR = os.path.join(ROOT_DIR, "agent_system", "review_engine", "config")
    AMR_DATA_FILE = os.path.join(AMR_DATA_DIR, "amr_data.yaml")
    PENDING_FILE = os.path.join(AMR_DATA_DIR, "pending_datasheet_reviews.yaml")

    def __init__(self):
        self._pending: List[DatasheetParamReview] = []
        self._approved: List[DatasheetParamReview] = []
        self._rejected: List[DatasheetParamReview] = []
        self._load_pending()

    # --------------------------------------------------------
    # 数据持久化
    # --------------------------------------------------------

    def _load_pending(self):
        """从文件加载待审批列表"""
        if os.path.exists(self.PENDING_FILE):
            try:
                with open(self.PENDING_FILE, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if data and "reviews" in data:
                    for r in data["reviews"]:
                        review = DatasheetParamReview.from_dict(r)
                        if review.status == DatasheetReviewStatus.PENDING.value:
                            self._pending.append(review)
                        elif review.status == DatasheetReviewStatus.APPROVED.value:
                            self._approved.append(review)
                        elif review.status == DatasheetReviewStatus.REJECTED.value:
                            self._rejected.append(review)
                logger.info(f"Loaded {len(self._pending)} pending, {len(self._approved)} approved, {len(self._rejected)} rejected datasheet reviews")
            except Exception as e:
                logger.error(f"Failed to load pending reviews: {e}")

    def _save_pending(self):
        """保存待审批列表到文件"""
        try:
            os.makedirs(self.AMR_DATA_DIR, exist_ok=True)
            data = {
                "reviews": [r.to_dict() for r in self._pending + self._approved + self._rejected],
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.PENDING_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.error(f"Failed to save pending reviews: {e}")

    # --------------------------------------------------------
    # 添加待审批项
    # --------------------------------------------------------

    def add_extracted_component(self, component: ExtractedComponent) -> List[str]:
        """
        将 PDF 解析结果添加到审批队列

        Returns:
            生成的 review_id 列表
        """
        review_ids = []
        for param in component.parameters:
            review_id = f"DS_{component.mpn}_{param.param_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(review_ids)}"

            review = DatasheetParamReview(
                review_id=review_id,
                mpn=component.mpn,
                param_type=param.param_type.value,
                param_name=param.name,
                value=param.value,
                unit=param.unit,
                min_value=param.min_value,
                max_value=param.max_value,
                condition=param.condition,
                source_text=param.source_text,
                confidence=param.confidence,
                extraction_method=component.extraction_method,
                created_at=datetime.now().isoformat(),
                source_file=component.source_file,
            )

            self._pending.append(review)
            review_ids.append(review_id)

        self._save_pending()
        logger.info(f"Added {len(review_ids)} parameters from {component.mpn} to HITL queue")
        return review_ids

    # --------------------------------------------------------
    # 审批操作
    # --------------------------------------------------------

    def approve(self, review_id: str, reviewer: str = "engineer", comment: str = "") -> bool:
        """批准参数"""
        for review in self._pending:
            if review.review_id == review_id:
                review.status = DatasheetReviewStatus.APPROVED.value
                review.reviewer = reviewer
                review.review_comment = comment
                review.reviewed_at = datetime.now().isoformat()
                self._approved.append(review)
                self._pending.remove(review)
                self._save_pending()
                logger.info(f"Approved datasheet param: {review_id}")
                return True
        return False

    def reject(self, review_id: str, reviewer: str = "engineer", comment: str = "") -> bool:
        """拒绝参数"""
        for review in self._pending:
            if review.review_id == review_id:
                review.status = DatasheetReviewStatus.REJECTED.value
                review.reviewer = reviewer
                review.review_comment = comment
                review.reviewed_at = datetime.now().isoformat()
                self._rejected.append(review)
                self._pending.remove(review)
                self._save_pending()
                logger.info(f"Rejected datasheet param: {review_id}")
                return True
        return False

    def modify(self, review_id: str, new_value: float, new_unit: str,
               reviewer: str = "engineer", comment: str = "") -> bool:
        """修改并批准参数"""
        for review in self._pending:
            if review.review_id == review_id:
                review.status = DatasheetReviewStatus.MODIFIED.value
                review.modified_value = new_value
                review.modified_unit = new_unit
                review.reviewer = reviewer
                review.review_comment = comment
                review.reviewed_at = datetime.now().isoformat()
                self._approved.append(review)
                self._pending.remove(review)
                self._save_pending()
                logger.info(f"Modified and approved datasheet param: {review_id}")
                return True
        return False

    # --------------------------------------------------------
    # 查询
    # --------------------------------------------------------

    def get_pending_list(self) -> List[DatasheetParamReview]:
        return list(self._pending)

    def get_approved_list(self) -> List[DatasheetParamReview]:
        return list(self._approved)

    def get_rejected_list(self) -> List[DatasheetParamReview]:
        return list(self._rejected)

    def get_stats(self) -> dict:
        return {
            "pending": len(self._pending),
            "approved": len(self._approved),
            "rejected": len(self._rejected),
            "total": len(self._pending) + len(self._approved) + len(self._rejected),
        }

    # --------------------------------------------------------
    # 落盘到 AMR 数据源
    # --------------------------------------------------------

    def save_approved_to_amr(self) -> dict:
        """
        将审批通过的参数保存到 amr_data.yaml

        Returns:
            {"saved": int, "message": str}
        """
        if not self._approved:
            return {"saved": 0, "message": "没有 approved 的参数"}

        # 按 MPN 分组
        amr_data: Dict[str, dict] = {}

        # 读取已有数据
        if os.path.exists(self.AMR_DATA_FILE):
            try:
                with open(self.AMR_DATA_FILE, 'r', encoding='utf-8') as f:
                    existing = yaml.safe_load(f)
                if existing:
                    amr_data = existing.get("components", {})
            except Exception as e:
                logger.warning(f"Failed to load existing AMR data: {e}")

        # 添加新批准的参数
        saved_count = 0
        for review in self._approved:
            mpn = review.mpn
            if mpn not in amr_data:
                amr_data[mpn] = {
                    "mpn": mpn,
                    "parameters": {},
                    "updated_at": datetime.now().isoformat(),
                }

            # 使用修改后的值（如果有）
            value = review.modified_value if review.modified_value is not None else review.value
            unit = review.modified_unit if review.modified_unit else review.unit

            amr_data[mpn]["parameters"][review.param_type] = {
                "name": review.param_name,
                "value": value,
                "unit": unit,
                "min_value": review.min_value,
                "max_value": review.max_value,
                "condition": review.condition,
                "approved_by": review.reviewer,
                "approved_at": review.reviewed_at,
            }
            saved_count += 1

        # 保存
        try:
            os.makedirs(self.AMR_DATA_DIR, exist_ok=True)
            with open(self.AMR_DATA_FILE, 'w', encoding='utf-8') as f:
                yaml.dump({"components": amr_data}, f, allow_unicode=True, sort_keys=False)

            # 清空已落盘的 approved 列表
            self._approved = []
            self._save_pending()

            logger.info(f"Saved {saved_count} parameters to {self.AMR_DATA_FILE}")
            return {"saved": saved_count, "message": f"已保存 {saved_count} 条参数"}

        except Exception as e:
            logger.error(f"Failed to save AMR data: {e}")
            return {"saved": 0, "message": f"保存失败: {e}"}


# ============================================================
# 文件型 AMR 数据源
# ============================================================

class FileBasedAMRSource:
    """
    基于 YAML 文件的 AMR 数据源

    从 amr_data.yaml 读取工程师审批后的参数
    """

    AMR_DATA_FILE = os.path.join(ROOT_DIR, "agent_system", "review_engine", "config", "amr_data.yaml")

    def __init__(self):
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """加载 AMR 数据"""
        if os.path.exists(self.AMR_DATA_FILE):
            try:
                with open(self.AMR_DATA_FILE, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if data:
                    self._data = data.get("components", {})
                logger.info(f"Loaded AMR data for {len(self._data)} components")
            except Exception as e:
                logger.error(f"Failed to load AMR data: {e}")

    def reload(self):
        """重新加载"""
        self._load()

    def get_capacitor_voltage_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电容耐压值 (V)"""
        # 尝试通过 model 名查找
        for mpn, comp_data in self._data.items():
            if mpn.upper() in model.upper() or model.upper() in mpn.upper():
                params = comp_data.get("parameters", {})
                if "cap_voltage_rating" in params:
                    return float(params["cap_voltage_rating"]["value"])
        return None

    def get_resistor_power_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电阻额定功率 (W)"""
        for mpn, comp_data in self._data.items():
            if mpn.upper() in model.upper() or model.upper() in mpn.upper():
                params = comp_data.get("parameters", {})
                if "res_power_rating" in params:
                    return float(params["res_power_rating"]["value"])
        return None

    def get_ic_voltage_range(self, refdes: str, model: str) -> Optional[tuple[float, float]]:
        """获取 IC 电源电压范围 (min, max)"""
        for mpn, comp_data in self._data.items():
            if mpn.upper() in model.upper() or model.upper() in mpn.upper():
                params = comp_data.get("parameters", {})
                vmin = params.get("voltage_min", {}).get("value")
                vmax = params.get("voltage_max", {}).get("value")
                if vmin is not None and vmax is not None:
                    return (float(vmin), float(vmax))
        return None

    def get_parameter(self, mpn: str, param_type: str) -> Optional[dict]:
        """获取指定器件的指定参数"""
        comp_data = self._data.get(mpn)
        if comp_data:
            return comp_data.get("parameters", {}).get(param_type)
        return None


# ============================================================
# 测试
# ============================================================

def _test():
    """测试 Datasheet HITL 流程"""
    print("=" * 60)
    print("Datasheet HITL 测试")
    print("=" * 60)

    # 1. 创建模拟的提取结果
    from agent_system.datasheet_parser import ExtractedComponent, DatasheetParameter, ParamType

    component = ExtractedComponent(
        mpn="TEST_CAP_10UF_50V",
        source_file="/tmp/test.pdf",
        extraction_method="regex",
        parameters=[
            DatasheetParameter(
                param_type=ParamType.CAP_VOLTAGE_RATING,
                name="Voltage Rating",
                value=50.0,
                unit="V",
                source_text="Voltage Rating: 50V DC",
            ),
            DatasheetParameter(
                param_type=ParamType.CAPACITANCE,
                name="Capacitance",
                value=10.0,
                unit="uF",
                source_text="Capacitance: 10uF",
            ),
        ]
    )

    # 2. 添加到 HITL
    print("\n[1/4] 添加参数到 HITL")
    manager = DatasheetHITLManager()
    review_ids = manager.add_extracted_component(component)
    print(f"  添加 {len(review_ids)} 个参数")
    print(f"  待审批: {manager.get_stats()['pending']}")

    # 3. 模拟审批
    print("\n[2/4] 审批参数")
    manager.approve(review_ids[0], reviewer="engineer_A", comment="确认耐压值")
    manager.modify(review_ids[1], new_value=10.0, new_unit="uF",
                   reviewer="engineer_A", comment="容值正确")
    print(f"  审批后: {manager.get_stats()}")

    # 4. 落盘到 AMR
    print("\n[3/4] 落盘到 AMR 数据源")
    result = manager.save_approved_to_amr()
    print(f"  结果: {result}")

    # 5. 验证 AMR 数据源
    print("\n[4/4] 验证 AMR 数据源")
    source = FileBasedAMRSource()
    voltage = source.get_capacitor_voltage_rating("C1", "TEST_CAP_10UF_50V", "10uF")
    print(f"  耐压值: {voltage}V")
    param = source.get_parameter("TEST_CAP_10UF_50V", "cap_voltage_rating")
    print(f"  参数详情: {param}")

    # 清理
    import os
    for f in [manager.PENDING_FILE, manager.AMR_DATA_FILE]:
        if os.path.exists(f):
            os.remove(f)

    print("\n✅ Datasheet HITL 测试完成")


if __name__ == "__main__":
    _test()
