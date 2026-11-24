"""WebSocket chat handler for streaming inference."""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool


class ConnectionManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept(subprotocol=websocket.scope.get("state", {}).get("chat_subprotocol"))
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def send_json(self, websocket: WebSocket, data: Dict[str, Any]):
        await websocket.send_json(data)


manager = ConnectionManager()


async def handle_chat_websocket(websocket: WebSocket):
    """Handle WebSocket chat connection."""
    await manager.connect(websocket)
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            
            if data.get("type") == "ping":
                await manager.send_json(websocket, {"type": "pong"})
                continue
            
            if data.get("type") == "chat":
                payload = data.get("payload", {})
                message = payload.get("message", "")
                task_type = payload.get("task_type", "auto")
                project_id = payload.get("project_id")

                # Run agent with streaming
                await run_agent_streaming(websocket, message, task_type, project_id)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        await manager.send_json(websocket, {
            "type": "error",
            "payload": {"error": str(e)}
        })
        manager.disconnect(websocket)


async def run_agent_streaming(websocket: WebSocket, message: str, task_type: str = "auto",
                               project_id: Optional[str] = None):
    """Run agent and stream results."""
    started = time.monotonic()
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from agent_system.react_agent import ReActAgent

        # Initialize agent
        agent = ReActAgent()

        # ReActAgent is synchronous. Run it off the event loop so callbacks can
        # send steps before the final result and other requests remain responsive.
        loop = asyncio.get_running_loop()
        pending_steps = []

        def step_callback(step: Dict[str, Any]):
            """Callback for each reasoning step."""
            pending_steps.append(asyncio.run_coroutine_threadsafe(manager.send_json(websocket, {
                "type": "step",
                "payload": {
                    "step": {
                        "step_id": step.get("step_id", 0),
                        "thought": step.get("thought", ""),
                        "action": step.get("action", ""),
                        "action_input": step.get("action_input", {}),
                        "observation": step.get("observation", ""),
                        "timestamp": step.get("timestamp", datetime.now().isoformat()),
                        "duration_ms": step.get("duration_ms"),
                        "is_error": step.get("is_error", False)
                    }
                }
            }), loop))

        # Run agent
        result = await run_in_threadpool(agent.run, message, task_type=task_type,
                                         project_id=project_id)
        for pending in pending_steps:
            await asyncio.wrap_future(pending)
        from ..routers.system import record_agent_query
        duration_s = time.monotonic() - started
        record_agent_query(result.get("task_type", task_type),
                           result.get("tool_call_count", 0),
                           int(duration_s * 1000),
                           result.get("status", "success"), source="ws")
        from ..routers.agent_runs import record_engine_run
        record_engine_run(
            "legacy", result.get("status", "success"), duration_s,
            tools=result.get("tool_call_count", 0),
            project_id=project_id, source="ws",
        )
        
        # Send final result
        await manager.send_json(websocket, {
            "type": "result",
            "payload": {
                "result": {
                    "status": result.get("status", "success"),
                    "task_type": result.get("task_type", task_type),
                    "report": result.get("report", ""),
                    "execution_trace": result.get("execution_trace", []),
                    "tool_call_count": result.get("tool_call_count", 0),
                    "timestamp": datetime.now().isoformat()
                }
            }
        })
        
    except Exception as e:
        from ..routers.system import record_agent_query
        duration_s = time.monotonic() - started
        record_agent_query(task_type, 0, int(duration_s * 1000),
                           "error", source="ws")
        from ..routers.agent_runs import record_engine_run
        record_engine_run("legacy", "error", duration_s,
                          project_id=project_id, source="ws")
        await manager.send_json(websocket, {
            "type": "error",
            "payload": {"error": str(e)}
        })
