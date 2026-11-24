"""Graph visualization API router."""
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
from datetime import datetime

from ..schemas.graph import (
    GraphRequest, GraphResponse, GraphResult,
    VizMode, Direction
)

router = APIRouter(prefix="/graph", tags=["Graph"])


def _build_dot(request: GraphRequest) -> str:
    """Build DOT in a worker thread with the request's project as the thread's scope."""
    from agent_system.graph_tools import get_current_project, set_current_project
    from web_ui.sub_pages.graph_viz import (
        _build_component_relation_dot,
        _build_power_chain_dot,
        _build_fault_root_dot,
        _build_common_cause_dot,
        _build_power_tree_dot
    )

    previous = get_current_project()
    set_current_project((request.project_id or "default").strip() or "default")
    try:
        if request.mode == VizMode.COMPONENT:
            return _build_component_relation_dot(
                refdes=request.refdes or "",
                depth=request.depth
            )
        if request.mode == VizMode.POWER_CHAIN:
            return _build_power_chain_dot(
                refdes=request.refdes or "",
                direction=request.direction.value,
                max_depth=request.depth
            )
        if request.mode == VizMode.FAULT_TRACE:
            return _build_fault_root_dot(refdes=request.refdes or "")
        if request.mode == VizMode.COMMON_CAUSE:
            from agent_system.graph_tools import get_common_cause_graph
            import json as _json
            graph_json = get_common_cause_graph(request.refdes or "")
            graph_data = _json.loads(graph_json) if isinstance(graph_json, str) and graph_json.startswith("{") else {"nodes": [], "edges": []}
            return _build_common_cause_dot(graph_data)
        if request.mode == VizMode.POWER_TREE:
            return _build_power_tree_dot(voltage=request.voltage)
        raise HTTPException(status_code=400, detail=f"Unknown mode: {request.mode}")
    finally:
        set_current_project(previous)


@router.post("/visualize", response_model=GraphResponse)
async def visualize_graph(request: GraphRequest) -> GraphResponse:
    """Generate graph visualization DOT."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

        # Builders issue many sequential Cypher queries; keep them off the event loop.
        dot_content = await run_in_threadpool(_build_dot, request) or ""
        node_count = 0
        edge_count = 0
        
        # Count nodes and edges from DOT content. graph_viz builders emit
        # undirected syntax ("--"), not "->", so match both.
        import re
        # "node [...]" / "edge [...]" are DOT default-attribute statements, not nodes.
        node_count = len(re.findall(r'\b(?!(?:node|edge|graph)\b)\w+\s*\[', dot_content))
        edge_count = len(re.findall(r'--|->', dot_content))
        
        graph_result = GraphResult(
            dot_content=dot_content,
            node_count=node_count,
            edge_count=edge_count
        )
        
        return GraphResponse(
            success=True,
            data=graph_result,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
