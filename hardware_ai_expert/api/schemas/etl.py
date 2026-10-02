"""ETL import schemas."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from enum import Enum


class ETLStep(str, Enum):
    """ETL step enumeration."""
    PENDING = "pending"
    PARSING = "parsing"
    VALIDATING = "validating"
    LOADING = "loading"
    COMPLETED = "completed"
    FAILED = "failed"


class ETLPreviewResult(BaseModel):
    """ETL preview result."""
    success: bool
    components_count: Optional[int] = None
    topology_count: Optional[int] = None
    unique_nets: Optional[int] = None
    parttype_coverage: Optional[float] = None
    parttype_distribution: Dict[str, int]
    power_nets_count: Optional[int] = None
    ground_nets_count: Optional[int] = None
    top_nets: List[str]
    bom_enriched_components: Optional[int] = None
    bom_issues: List[Dict] = Field(default_factory=list)


class ETLPreviewResponse(BaseModel):
    """ETL preview response."""
    success: bool = True
    data: ETLPreviewResult
    message: Optional[str] = None
    timestamp: str


class ETLProgress(BaseModel):
    """ETL progress."""
    job_id: str
    status: str
    step: ETLStep
    progress: float  # 0-100
    message: str
    error: Optional[str] = None
    result: Optional["ETLResult"] = None
    created_at: str
    updated_at: str


class QualityReport(BaseModel):
    """Quality report."""
    components: Optional[int] = None
    pins: Optional[int] = None
    nets: Optional[int] = None
    part_type_coverage: Optional[float] = None
    passed: bool
    details: Optional[Dict] = None


class ETLResult(BaseModel):
    """ETL result."""
    success: bool
    components_count: Optional[int] = None
    topology_count: Optional[int] = None
    parttype_coverage: Optional[float] = None
    quality_passed: bool
    message: str
    quality_report: Optional[QualityReport] = None
    bom_issues: List[Dict] = Field(default_factory=list)


class ETLResponse(BaseModel):
    """ETL response."""
    success: bool = True
    job_id: str
    status: str
    data: Optional[ETLResult] = None
    message: Optional[str] = None
    timestamp: str


class ProjectListResponse(BaseModel):
    """Project list response."""
    success: bool = True
    data: List[str]
    message: Optional[str] = None
    timestamp: str


class ProjectActionRequest(BaseModel):
    """Project action request."""
    project_name: str = Field(min_length=1)

    @field_validator("project_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_name must not be blank")
        return value


class ProjectActionResponse(BaseModel):
    """Project action response."""
    success: bool = True
    data: Dict[str, str]  # {"project_id": "..."}
    message: Optional[str] = None
    timestamp: str
