"""Review schemas."""
from pydantic import BaseModel
from typing import Optional, List, Dict
from enum import Enum


class Severity(str, Enum):
    """Violation severity."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class Violation(BaseModel):
    """Violation item."""
    rule_id: str
    rule_name: str
    refdes: str
    net_name: Optional[str] = None
    description: str
    severity: Severity
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggested_fix: Optional[str] = None


class RuleInfo(BaseModel):
    """Rule information."""
    id: str
    name: str
    template_id: str
    severity: Severity
    enabled: bool
    description: Optional[str] = None


class ReviewRequest(BaseModel):
    """Review request."""
    rule_ids: Optional[List[str]] = None  # None means all rules
    enabled_only: bool = True
    project_id: Optional[str] = None


class ReviewReport(BaseModel):
    """Review report summary."""
    total: int
    errors: int
    warnings: int
    infos: int
    by_rule: Dict[str, int]
    generated_at: str


class ReviewResult(BaseModel):
    """Review result."""
    violations: List[Violation]
    report_markdown: str
    summary: ReviewReport


class ReviewResponse(BaseModel):
    """Review response."""
    success: bool = True
    data: ReviewResult
    message: Optional[str] = None
    timestamp: str


class RulesListResponse(BaseModel):
    """Rules list response."""
    success: bool = True
    data: List[RuleInfo]
    message: Optional[str] = None
    timestamp: str
