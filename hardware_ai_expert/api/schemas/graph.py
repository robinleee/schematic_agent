"""Graph visualization schemas."""
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from enum import Enum


class VizMode(str, Enum):
    """Visualization mode."""
    COMPONENT = "component"
    POWER_CHAIN = "power_chain"
    FAULT_TRACE = "fault_trace"
    COMMON_CAUSE = "common_cause"
    POWER_TREE = "power_tree"


class Direction(str, Enum):
    """Direction for graph traversal."""
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    BOTH = "both"


class GraphRequest(BaseModel):
    """Graph request."""
    mode: VizMode
    refdes: Optional[str] = None  # Starting component
    depth: int = Field(default=2, ge=1, le=5)
    direction: Direction = Direction.BOTH
    voltage: Optional[str] = None  # For power tree mode

    @model_validator(mode="after")
    def require_start(self):
        if self.mode != VizMode.POWER_TREE and not (self.refdes and self.refdes.strip()):
            raise ValueError("refdes is required for this mode")
        return self


class GraphResult(BaseModel):
    """Graph result."""
    dot_content: str  # DOT format string
    node_count: int
    edge_count: int


class GraphResponse(BaseModel):
    """Graph response."""
    success: bool = True
    data: GraphResult
    message: Optional[str] = None
    timestamp: str
