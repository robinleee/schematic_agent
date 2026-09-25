"""Chat API router."""
import asyncio
import os
import sys
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from ..schemas.chat import (
    ChatRequest, ChatResponse, ChatResult, ReasoningStep
)

router = APIRouter(prefix="/chat", tags=["Chat"])
CHAT_AGENT_TIMEOUT_SECONDS = float(os.getenv("CHAT_AGENT_TIMEOUT_SECONDS", "300"))


def _run_agent(message: str, task_type: str) -> dict:
    """Run the synchronous ReAct agent outside FastAPI's event loop."""
    sys.path.insert(
        0,
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    from agent_system.react_agent import ReActAgent

    return ReActAgent().run(message, task_type=task_type)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Execute chat and return complete result (non-streaming).
    For streaming, use WebSocket /ws/chat
    """
    try:
        task_type = request.task_type.value if request.task_type else "auto"
        # ReActAgent.run() is synchronous and can take minutes with a thinking
        # model. Keep it out of the event loop so health/review endpoints remain
        # responsive while this request is in progress.
        result = await asyncio.wait_for(
            run_in_threadpool(_run_agent, request.message, task_type),
            timeout=CHAT_AGENT_TIMEOUT_SECONDS,
        )

        # Convert execution trace
        execution_trace = []
        for i, step in enumerate(result.get("execution_trace", [])):
            execution_trace.append(ReasoningStep(
                step_id=i + 1,
                thought=step.get("thought", ""),
                action=step.get("action", ""),
                action_input=step.get("action_input", {}),
                observation=step.get("observation", ""),
                timestamp=step.get("timestamp", datetime.now().isoformat()),
                duration_ms=step.get("duration_ms"),
                is_error=step.get("is_error", False)
            ))
        chat_result = ChatResult(
            status=result.get("status", "success"),
            task_type=result.get("task_type", task_type),
            report=result.get("report", ""),
            execution_trace=execution_trace,
            tool_call_count=result.get("tool_call_count", 0),
            timestamp=datetime.now().isoformat()
        )
        return ChatResponse(
            success=True,
            data=chat_result,
            timestamp=datetime.now().isoformat()
        )
    except asyncio.TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Agent execution timed out after {CHAT_AGENT_TIMEOUT_SECONDS:.0f}s",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
