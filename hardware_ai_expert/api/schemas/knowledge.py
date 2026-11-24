"""Knowledge base schemas."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from enum import Enum


class KnowledgeCategory(str, Enum):
    """Knowledge category."""
    DATASHEET = "datasheet"
    DESIGN_GUIDE = "design_guide"
    APPLICATION_NOTE = "application_note"
    GENERAL = "general"


class UploadResponse(BaseModel):
    """Knowledge upload response."""
    success: bool = True
    data: Dict[str, Any]  # {"chunk_count": 5, "mpn": "..."}
    message: Optional[str] = None
    timestamp: str


class SearchRequest(BaseModel):
    """Knowledge search request."""
    mpn: Optional[str] = None
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=50)
    project_id: Optional[str] = None

    @field_validator("query")
    @classmethod
    def nonblank(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("query must not be blank")
        return query


class SearchResult(BaseModel):
    """Search result."""
    status: str  # success, not_found, error
    tier: str  # Tier0, Tier1, Tier2, Tier3, none
    content: str
    source: str
    confidence: float
    mpn: Optional[str] = None
    cached: bool = False


class SearchResponse(BaseModel):
    """Search response."""
    success: bool = True
    data: SearchResult
    message: Optional[str] = None
    timestamp: str


class KnowledgeStats(BaseModel):
    """Knowledge base statistics."""
    tier1_chunks: int
    tier2_enabled: bool
    tier3_enabled: bool
    source_distribution: Dict[str, int]


class KnowledgeStatsResponse(BaseModel):
    """Knowledge stats response."""
    success: bool = True
    data: KnowledgeStats
    message: Optional[str] = None
    timestamp: str
