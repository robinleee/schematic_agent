"""Knowledge base API router."""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from datetime import datetime
from typing import Optional
import os
from starlette.concurrency import run_in_threadpool
from ..services.uploads import stage, cleanup, KNOWLEDGE_LIMIT

from ..schemas.knowledge import (
    UploadResponse, SearchRequest, SearchResponse, SearchResult,
    KnowledgeStatsResponse, KnowledgeStats
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


def _component_specs(project_id: str, refdes: str) -> dict:
    """Only project-owned Component data; no global vector/GraphRAG/Tier3 fallback."""
    from neo4j import GraphDatabase
    from agent_system.mpn_decoder import MPNDecoder
    if not project_id.strip() or not refdes.strip():
        raise ValueError("project_id and refdes are required")
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD")))
    try:
        with driver.session() as session:
            row = session.run(
                """MATCH (c:Component {project_id: $pid, RefDes: $ref})
                   RETURN c.MPN AS mpn, c.MPNRaw AS mpn_raw,
                          c.Manufacturer AS manufacturer, c.Description AS description,
                          c.BOMSourceLine AS source_line, c.Package AS package""",
                pid=project_id, ref=refdes).single()
    finally:
        driver.close()
    if row is None:
        return {"status": "not_found", "reason": "component_not_in_project"}
    component = dict(row)
    mpn = component.get("mpn")
    decoded = MPNDecoder().decode(mpn).to_dict() if mpn else None
    return {
        "status": "decoded" if decoded and decoded.get("confidence", 0) > 0 else "unresolved",
        "reason": None if mpn else "missing_or_ambiguous_mpn",
        "component": component, "decoder": decoded,
        "amr": {"voltage_rating_v": decoded["voltage_rating_v"],
                "source": "mpn_decoder", "confidence": decoded["confidence"]}
        if decoded and decoded.get("voltage_rating_v") is not None else None,
        "datasheet": {"status": "unavailable", "reason": "project_scoped_index_not_verified"},
        "graphrag": {"status": "unavailable", "reason": "project_scoped_retrieval_not_verified"},
        "tier3": {"status": "disabled", "reason": "external_calls_not_permitted"},
    }


@router.get("/projects/{project_id}/components/{refdes}/specs")
async def component_specs(project_id: str, refdes: str) -> dict:
    """Project-scoped BOM/decoder lookup; deliberately does not contact external services."""
    try:
        return await run_in_threadpool(_component_specs, project_id, refdes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Component lookup unavailable") from exc


@router.post("/upload", response_model=UploadResponse)
async def upload_knowledge(
    file: UploadFile = File(...),
    mpn: str = Form(...),
    category: str = Form("general"),
    source: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
) -> UploadResponse:
    """Upload knowledge document."""
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in (".pdf", ".txt"):
        raise HTTPException(status_code=400, detail="Only PDF and TXT documents are supported")
    if not mpn.strip():
        raise HTTPException(status_code=422, detail="mpn must not be blank")
    if (project_id is None) != (scope == "shared") or (scope not in (None, "shared")):
        raise HTTPException(status_code=422, detail="Specify project_id or explicit scope=shared")
    if project_id is not None and not project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be blank")
    from ..dependencies import get_knowledge_router
    router_instance = get_knowledge_router(project_id=project_id, shared=scope == "shared")
    if router_instance is None:
        raise HTTPException(status_code=503, detail="Knowledge router unavailable")
    temp_path = None
    try:
        temp_path = await stage(file, {".pdf", ".txt"}, KNOWLEDGE_LIMIT)
        result_dict = await run_in_threadpool(
            router_instance.upload_document,
            file_path=temp_path, mpn=mpn, category=category, source=source)
        return UploadResponse(
            success=True,
            data=result_dict,
            message=f"成功导入 {result_dict.get('chunk_count', 0)} 个知识切片",
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Knowledge index unavailable or partially indexed") from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail="Knowledge upload failed") from e
    finally:
        if temp_path is not None:
            cleanup([temp_path])


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(request: SearchRequest) -> SearchResponse:
    """Search knowledge base."""
    try:
        if request.project_id is not None and not request.project_id.strip():
            raise HTTPException(status_code=422, detail="project_id must not be blank")
        from ..dependencies import get_knowledge_router
        router_instance = get_knowledge_router(project_id=request.project_id)
        if router_instance is None:
            raise HTTPException(status_code=503, detail="Knowledge router unavailable")
        result = router_instance.search(
            mpn=request.mpn,
            query=request.query,
            max_results=request.max_results
        )
        
        # Handle both dict and object results
        def _get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default) if hasattr(obj, key) else default
        
        search_result = SearchResult(
            status=_get(result, "status", "not_found"),
            tier=_get(result, "tier", "none"),
            content=str(_get(result, "content", "")),
            source=str(_get(result, "source", "")),
            confidence=float(_get(result, "confidence", 0.0)),
            mpn=_get(result, "mpn"),
            cached=bool(_get(result, "cached", False))
        )
        
        return SearchResponse(
            success=True,
            data=search_result,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail="Knowledge search unavailable") from e


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def get_knowledge_stats() -> KnowledgeStatsResponse:
    """Get knowledge base statistics."""
    try:
        from ..dependencies import get_knowledge_router
        router_instance = get_knowledge_router()
        if router_instance is None:
            raise HTTPException(status_code=503, detail="Knowledge router unavailable")
        result = router_instance.get_stats()
        
        # Handle both dict and object results
        def _get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default) if hasattr(obj, key) else default
        
        stats = KnowledgeStats(
            tier1_chunks=_get(result, "tier1_chunks"),
            tier2_enabled=_get(result, "tier2_enabled", False),
            tier3_enabled=_get(result, "tier3_enabled", False),
            source_distribution=_get(result, "source_distribution", {})
        )
        
        return KnowledgeStatsResponse(
            success=True,
            data=stats,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail="Knowledge statistics unavailable") from e
