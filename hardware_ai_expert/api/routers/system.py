"""System status API router."""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import List, Dict, Optional
from collections import deque
from threading import Lock

from ..schemas.system import (
    SystemStatusResponse, SystemStatus,
    ServiceInfo, ServiceStatus, DataStats, AgentStats, QueryRecord
)

router = APIRouter(prefix="/system", tags=["System"])
_agent_lock = Lock()
_agent_query_count = 0
_agent_success_count = 0
_agent_failure_count = 0
_agent_total_duration_ms = 0
_recent_queries = deque(maxlen=20)


def record_agent_query(task_type: str, tool_calls: int, duration_ms: int, status: str,
                       source: str = "rest") -> None:
    """Track completed REST/WS chat calls without retaining private prompt text."""
    global _agent_query_count, _agent_success_count, _agent_failure_count, _agent_total_duration_ms
    with _agent_lock:
        _agent_query_count += 1
        _agent_total_duration_ms += duration_ms
        if status == "success":
            _agent_success_count += 1
        else:
            _agent_failure_count += 1
        _recent_queries.append(QueryRecord(
            query="[redacted]", task_type=f"{source}:{task_type} ({status})",
            tool_calls=tool_calls, duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
        ))


def get_agent_stats() -> AgentStats:
    with _agent_lock:
        return AgentStats(query_count=_agent_query_count,
                          success_count=_agent_success_count, failure_count=_agent_failure_count,
                          average_duration_ms=round(_agent_total_duration_ms / _agent_query_count, 1)
                          if _agent_query_count else None,
                          recent_queries=list(reversed(_recent_queries)))


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """Get system status."""
    try:
        # Check services with fallback
        services: List[ServiceInfo] = []
        
        # Neo4j
        try:
            from agent_system.connection_pool import get_neo4j_driver
            driver = get_neo4j_driver()
            with driver.session() as session:
                start = datetime.now()
                result = session.run("RETURN 1")
                result.single()
                latency = int((datetime.now() - start).total_seconds() * 1000)
            services.append(ServiceInfo(
                name="Neo4j",
                status=ServiceStatus.RUNNING,
                latency_ms=latency
            ))
        except Exception:
            services.append(ServiceInfo(
                name="Neo4j",
                status=ServiceStatus.DEGRADED,
                message="Neo4j unavailable"
            ))
        
        # Ollama
        try:
            from agent_system.connection_pool import get_ollama_client
            ollama = get_ollama_client()
            start = datetime.now()
            ollama.list()
            latency = int((datetime.now() - start).total_seconds() * 1000)
            services.append(ServiceInfo(
                name="Ollama",
                status=ServiceStatus.RUNNING,
                latency_ms=latency
            ))
        except Exception:
            services.append(ServiceInfo(
                name="Ollama",
                status=ServiceStatus.DEGRADED,
                message="Ollama unavailable"
            ))
        
        # ChromaDB
        try:
            import chromadb
            client = chromadb.HttpClient(host="localhost", port=8000)
            start = datetime.now()
            client.heartbeat()
            latency = int((datetime.now() - start).total_seconds() * 1000)
            services.append(ServiceInfo(
                name="ChromaDB",
                status=ServiceStatus.RUNNING,
                latency_ms=latency
            ))
        except Exception:
            services.append(ServiceInfo(
                name="ChromaDB",
                status=ServiceStatus.DEGRADED,
                message="ChromaDB unavailable"
            ))
        
        # API Server
        services.append(ServiceInfo(
            name="API Server",
            status=ServiceStatus.RUNNING,
            version="1.0.0"
        ))
        
        # Data stats
        data_stats = DataStats(by_parttype={})
        
        try:
            from agent_system.connection_pool import get_neo4j_driver
            driver = get_neo4j_driver()
            with driver.session() as session:
                rec = session.run(
                    "MATCH (c:Component) "
                    "RETURN count(c) AS comps, "
                    "sum(CASE WHEN c.PartType IS NULL OR trim(c.PartType) = '' "
                    "OR c.PartType = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown"
                ).single()
                comps = rec["comps"] or 0
                unknown = rec["unknown"] or 0
                pins = session.run("MATCH (p:Pin) RETURN count(p) AS c").single()["c"]
                nets = session.run("MATCH (n:Net) RETURN count(n) AS c").single()["c"]
                by_rows = session.run(
                    "MATCH (c:Component) RETURN c.PartType AS pt, count(c) AS c ORDER BY c DESC"
                ).data()
            by_parttype = {(r["pt"] or "Unknown"): r["c"] for r in by_rows}
            coverage = (comps - unknown) / comps * 100 if comps else 0.0
            data_stats = DataStats(
                components=comps,
                pins=pins,
                nets=nets,
                part_type_coverage=round(coverage, 1),
                by_parttype=by_parttype,
                status="available",
            )
        except Exception:
            # Keep all observed data fields unavailable. Do not substitute
            # zeroes or project-independent fixture values when Neo4j fails.
            data_stats = DataStats(by_parttype={}, status="unavailable")
        
        agent_stats = get_agent_stats()
        
        system_status = SystemStatus(
            services=services,
            data_stats=data_stats,
            agent_stats=agent_stats
        )
        
        return SystemStatusResponse(
            success=True,
            data=system_status,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="System status unavailable") from e
