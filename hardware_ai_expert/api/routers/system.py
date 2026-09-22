"""System status API router."""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import List, Dict, Optional

from ..schemas.system import (
    SystemStatusResponse, SystemStatus,
    ServiceInfo, ServiceStatus, DataStats, AgentStats, QueryRecord
)

router = APIRouter(prefix="/system", tags=["System"])


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
                latency_ms=latency,
                version="5.x"
            ))
        except Exception as e:
            services.append(ServiceInfo(
                name="Neo4j",
                status=ServiceStatus.ERROR,
                message=str(e)[:100]
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
                latency_ms=latency,
                version="0.1.x"
            ))
        except Exception as e:
            services.append(ServiceInfo(
                name="Ollama",
                status=ServiceStatus.ERROR,
                message=str(e)[:100]
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
                status=ServiceStatus.STOPPED
            ))
        
        # API Server
        services.append(ServiceInfo(
            name="API Server",
            status=ServiceStatus.RUNNING,
            version="1.0.0"
        ))
        
        # Data stats
        data_stats = DataStats(
            components=0,
            pins=0,
            nets=0,
            part_type_coverage=0.0,
            by_parttype={}
        )
        
        try:
            from agent_system.connection_pool import get_neo4j_driver
            driver = get_neo4j_driver()
            with driver.session() as session:
                rec = session.run(
                    "MATCH (c:Component) "
                    "RETURN count(c) AS comps, "
                    "sum(CASE WHEN c.PartType = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown"
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
                by_parttype=by_parttype
            )
        except Exception:
            pass
        
        # Agent stats (placeholder)
        agent_stats = AgentStats(
            query_count=0,
            token_usage=0,
            recent_queries=[]
        )
        
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
        raise HTTPException(status_code=500, detail=str(e))
