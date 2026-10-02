"""Graph visualization API router."""
from fastapi import APIRouter, HTTPException
from datetime import datetime

from ..schemas.graph import (
    GraphRequest, GraphResponse, GraphResult,
    VizMode, Direction
)

router = APIRouter(prefix="/graph", tags=["Graph"])


@router.post("/visualize", response_model=GraphResponse)
async def visualize_graph(request: GraphRequest) -> GraphResponse:
    """Generate graph visualization DOT."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from web_ui.sub_pages.graph_viz import (
            _build_component_relation_dot,
            _build_power_chain_dot,
            _build_fault_root_dot,
            _build_common_cause_dot,
            _build_power_tree_dot
        )
        
        dot_content = ""
        node_count = 0
        edge_count = 0
        
        if request.mode == VizMode.COMPONENT:
            dot_content = _build_component_relation_dot(
                refdes=request.refdes or "",
                depth=request.depth
            )
        elif request.mode == VizMode.POWER_CHAIN:
            dot_content = _build_power_chain_dot(
                refdes=request.refdes or "",
                direction=request.direction.value,
                max_depth=request.depth
            )
        elif request.mode == VizMode.FAULT_TRACE:
            dot_content = _build_fault_root_dot(refdes=request.refdes or "")
        elif request.mode == VizMode.COMMON_CAUSE:
            from agent_system.graph_tools import get_common_cause_graph
            import json as _json
            graph_json = get_common_cause_graph(request.refdes or "")
            graph_data = _json.loads(graph_json) if isinstance(graph_json, str) and graph_json.startswith("{") else {"nodes": [], "edges": []}
            dot_content = _build_common_cause_dot(graph_data)
        elif request.mode == VizMode.POWER_TREE:
            dot_content = _build_power_tree_dot(voltage=request.voltage)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {request.mode}")
        
        # Count nodes and edges from DOT content
        import re
        node_count = len(re.findall(r'\b\w+\s*\[', dot_content))
        edge_count = len(re.findall(r'->', dot_content))
        
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
