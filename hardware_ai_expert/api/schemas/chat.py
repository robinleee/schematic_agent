"""Chat schemas."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from enum import Enum


class TaskType(str, Enum):
    """Task type enumeration."""
    REVIEW = "review"
    DIAGNOSIS = "diagnosis"
    QUERY = "query"
    AUTO = "auto"


class ReasoningStep(BaseModel):
    """Reasoning step."""
    step_id: int
    thought: str
    action: str
    action_input: Dict[str, Any]
    observation: str
    timestamp: str
    duration_ms: Optional[int] = None
    is_error: bool = False


class ChatRequest(BaseModel):
    """Chat request."""
    message: str = Field(min_length=1)
    task_type: Optional[TaskType] = TaskType.AUTO
    context: Optional[Dict[str, Any]] = None
    project_id: Optional[str] = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("message must not be blank")
        return message

    @field_validator("project_id")
    @classmethod
    def project_id_nonblank(cls, project_id: Optional[str]) -> Optional[str]:
        if project_id is not None and not project_id.strip():
            raise ValueError("project_id must not be blank")
        return project_id


class ChatResult(BaseModel):
    """Chat result."""
    status: str  # success, timeout, error
    task_type: str
    report: str  # Markdown format
    execution_trace: List[ReasoningStep]
    tool_call_count: int
    timestamp: str


class ChatResponse(BaseModel):
    """Chat response."""
    success: bool = True
    data: ChatResult
    message: Optional[str] = None
    timestamp: str
