"""HITL (Human-in-the-Loop) approval schemas."""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Literal, Dict
from enum import Enum


class ReviewStatus(str, Enum):
    """Review status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PERSISTED = "persisted"


class PendingReview(BaseModel):
    """Pending review item."""
    review_id: str
    rule_id: str
    rule_name: str
    refdes: str
    net_name: Optional[str] = None
    description: str
    severity: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggested_fix: Optional[str] = None
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str
    source: str = "agent"


class PendingListRequest(BaseModel):
    """Pending list request."""
    status: Optional[ReviewStatus] = ReviewStatus.PENDING
    page: int = 1
    page_size: int = 50


class PendingListResponse(BaseModel):
    """Pending list response."""
    success: bool = True
    data: List[PendingReview]
    total: int
    page: int
    page_size: int
    message: Optional[str] = None
    timestamp: str


class ReviewActionRequest(BaseModel):
    """Review action request."""
    review_ids: List[str] = Field(..., min_length=1)
    action: Literal["approve", "reject"]
    comment: Optional[str] = None
    reviewer: Optional[str] = "engineer"

    @field_validator("review_ids")
    @classmethod
    def validate_ids(cls, ids: List[str]) -> List[str]:
        if any(not rid.strip() for rid in ids):
            raise ValueError("review_ids must not contain blank IDs")
        if len(ids) != len(set(ids)):
            raise ValueError("review_ids must not contain duplicates")
        return ids


class ReviewActionResult(BaseModel):
    review_id: str
    action: Literal["approve", "reject"]
    success: bool
    error: Optional[str] = None


class ReviewActionData(BaseModel):
    results: List[ReviewActionResult]
    succeeded: int
    failed: int


class ReviewActionResponse(BaseModel):
    """Review action response."""
    success: bool = True
    data: ReviewActionData
    message: Optional[str] = None
    timestamp: str


class ExportRequest(BaseModel):
    """Save all approved rules to local YAML."""
    model_config = ConfigDict(extra="forbid")


class ExportResult(BaseModel):
    saved: int
    rules: List[str] = Field(default_factory=list)
    location: Optional[str] = None  # Server-side filename, never an absolute path


class ExportResponse(BaseModel):
    """Local rule persistence response."""
    success: bool = True
    data: ExportResult
    message: Optional[str] = None
    timestamp: str


class DatasheetPendingReview(BaseModel):
    """Pending datasheet parameter review item."""
    review_id: str
    mpn: str
    param_type: str
    param_name: str
    value: float
    unit: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    condition: str = ""
    source_text: str = ""
    confidence: float = 1.0
    extraction_method: str = ""
    status: str = "pending"
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str
    source_file: str = ""


class DatasheetPendingListResponse(BaseModel):
    success: bool = True
    data: List[DatasheetPendingReview]
    total: int
    message: Optional[str] = None
    timestamp: str


class DatasheetReviewActionRequest(ReviewActionRequest):
    pass


class DatasheetPersistResponse(BaseModel):
    success: bool = True
    data: Dict[str, object]
    message: Optional[str] = None
    timestamp: str
