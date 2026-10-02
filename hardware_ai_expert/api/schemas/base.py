"""Base schemas for API responses."""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, Generic, TypeVar

T = TypeVar('T')


class BaseResponse(BaseModel, Generic[T]):
    """Base response model."""
    success: bool = True
    data: Optional[T] = None
    message: Optional[str] = None
    timestamp: str = datetime.now().isoformat()


class ErrorResponse(BaseModel):
    """Error response model."""
    success: bool = False
    error: Dict[str, Any]
    timestamp: str = datetime.now().isoformat()


class PaginationParams(BaseModel):
    """Pagination parameters."""
    page: int = 1
    page_size: int = 20
