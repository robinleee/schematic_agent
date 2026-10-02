"""System status schemas."""
from pydantic import BaseModel
from typing import List, Dict, Optional
from enum import Enum


class ServiceStatus(str, Enum):
    """Service status."""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    DEGRADED = "degraded"


class ServiceInfo(BaseModel):
    """Service information."""
    name: str
    status: ServiceStatus
    latency_ms: Optional[int] = None
    version: Optional[str] = None
    message: Optional[str] = None


class DataStats(BaseModel):
    """Data statistics."""
    components: Optional[int] = None
    pins: Optional[int] = None
    nets: Optional[int] = None
    part_type_coverage: Optional[float] = None
    by_parttype: Dict[str, int]
    status: str = "unavailable"


class QueryRecord(BaseModel):
    """Query record."""
    query: str
    task_type: str
    tool_calls: int
    duration_ms: int
    timestamp: str


class AgentStats(BaseModel):
    """Agent statistics."""
    query_count: int  # Completed REST/WS chat requests in this process
    success_count: int = 0
    failure_count: int = 0
    average_duration_ms: Optional[float] = None
    token_usage: Optional[int] = None  # Agent does not expose token usage
    recent_queries: List[QueryRecord]
    status: str = "degraded"
    message: str = "Process-local REST/WS chat only; token usage and cross-process history unavailable"


class SystemStatus(BaseModel):
    """System status."""
    services: List[ServiceInfo]
    data_stats: DataStats
    agent_stats: AgentStats


class SystemStatusResponse(BaseModel):
    """System status response."""
    success: bool = True
    data: SystemStatus
    message: Optional[str] = None
    timestamp: str
