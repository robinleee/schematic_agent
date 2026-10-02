"""FastAPI main application."""
import sys
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from .routers import chat, review, hitl, knowledge, etl, graph, system
from .websocket.chat_ws import handle_chat_websocket
from .schemas.base import BaseResponse
from .security import SecurityBoundary, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings()  # Read-only validation; no live dependency or data mutation.
    # Startup
    print(f"[{datetime.now().isoformat()}] Hardware AI Expert API starting...")
    yield
    # Shutdown
    print(f"[{datetime.now().isoformat()}] Hardware AI Expert API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Hardware AI Expert API",
    description="Hardware schematic review and diagnosis AI system",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# The boundary also protects static routes and the WebSocket handshake.
app.add_middleware(SecurityBoundary)

# Include routers
app.include_router(chat.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
app.include_router(hitl.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(etl.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")


# WebSocket endpoint
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming chat."""
    await handle_chat_websocket(websocket)


# Health check
@app.get("/api/v1/health", response_model=BaseResponse)
async def health_check():
    """Health check endpoint."""
    return BaseResponse(
        success=True,
        message="OK",
        timestamp=datetime.now().isoformat()
    )


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - serve frontend or API info."""
    # Check if frontend dist exists
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        return FileResponse(frontend_dist / "index.html")
    return {
        "name": "Hardware AI Expert API",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json"
    }


# Serve frontend static files (if exists)
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # Serve static files
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    
    # Catch-all route for SPA
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA for all routes."""
        file_path = (frontend_dist / full_path).resolve()
        if frontend_dist.resolve() in file_path.parents and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
