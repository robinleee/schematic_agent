"""ETL import API router."""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Path
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import timezone
from starlette.concurrency import run_in_threadpool
from ..services.uploads import stage, cleanup, ETL_LIMIT, ETL_SUFFIXES
from ..services.etl_jobs import JobStore

from ..schemas.etl import (
    ETLPreviewResponse, ETLPreviewResult,
    ETLResponse, ETLResult, QualityReport,
    ProjectListResponse, ProjectActionRequest, ProjectActionResponse,
    ETLProgress, ETLStep
)

router = APIRouter(prefix="/etl", tags=["ETL"])
_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="etl")


async def _stage_files(pstxnet, pstxprt, pstchip, bom):
    files = {}
    try:
        for name, upload in (("pstxnet", pstxnet), ("pstxprt", pstxprt),
                             ("pstchip", pstchip), ("bom", bom)):
            if upload is not None:
                files[name] = await stage(upload, ETL_SUFFIXES[name], ETL_LIMIT)
        return files
    except BaseException:
        cleanup(files.values())
        raise


def _etl_result(result):
    qr = result.get("quality_report")
    quality_report = None
    if isinstance(qr, dict):
        summary = qr.get("summary") or {}
        quality_report = QualityReport(
            components=qr.get("components", summary.get("total_components")),
            pins=qr.get("pins"), nets=qr.get("nets"),
            part_type_coverage=qr.get("part_type_coverage", result.get("parttype_coverage")),
            passed=qr.get("passed", result.get("quality_passed", False)),
            details=qr)
    return ETLResult(
        success=result.get("success", False),
        components_count=result.get("components_count"),
        topology_count=result.get("topology_count"),
        parttype_coverage=result.get("parttype_coverage"),
        quality_passed=result.get("quality_passed", False),
        message=result.get("message") or "ETL failed",
        bom_issues=result.get("details", {}).get("bom_issues", []),
        quality_report=quality_report)


def _run_job(store, job_id, files, project_name):
    try:
        queued_at = datetime.fromisoformat(store.get(job_id)["created_at"])
        if (datetime.now(timezone.utc) - queued_at).total_seconds() > int(
            os.environ.get("ETL_QUEUE_TIMEOUT_SECONDS", "3600")
        ):
            store.update(job_id, "timeout", "failed", 0, "ETL queue timed out",
                         "ETL queue timed out", expected=("queued",))
            return
        store.update(job_id, "running", "parsing", 5, "ETL executing")
        from agent_system.etl_web_bridge import ETLWebExecutor
        result = ETLWebExecutor().run_etl(files, project_name)
        parsed = _etl_result(result)
        status = "succeeded" if parsed.success else "failed"
        store.update(job_id, status, "completed" if parsed.success else "failed",
                     100 if parsed.success else 5, parsed.message,
                     None if parsed.success else parsed.message,
                     parsed.model_dump())
    except Exception:
        # Do not expose internal paths, credentials or tracebacks in public job records.
        store.update(job_id, "failed", "failed", 5, "ETL worker failed",
                     "ETL worker failed")
    finally:
        cleanup(files.values())


@router.get("/projects", response_model=ProjectListResponse)
async def get_projects() -> ProjectListResponse:
    """Get project list."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from agent_system.graph_tools import list_projects
        
        # Legacy Project nodes can lack an id; omit them instead of turning
        # the entire project selector into a 500 response.
        projects = [name for name in list_projects()
                    if isinstance(name, str) and name.strip()]
        
        return ProjectListResponse(
            success=True,
            data=projects,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects", response_model=ProjectActionResponse)
async def create_project(request: ProjectActionRequest) -> ProjectActionResponse:
    """Create new project."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from agent_system.etl_web_bridge import ETLWebExecutor
        
        executor = ETLWebExecutor()
        result = executor.create_project(request.project_name)
        
        return ProjectActionResponse(
            success=True,
            data=result,
            message=f"项目 {request.project_name} 创建成功",
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_name}", response_model=ProjectActionResponse)
async def delete_project(project_name: str = Path(...)) -> ProjectActionResponse:
    """Delete project."""
    if not project_name.strip():
        raise HTTPException(status_code=422, detail="project_name must not be blank")
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from agent_system.etl_web_bridge import ETLWebExecutor
        
        executor = ETLWebExecutor()
        result = executor.delete_project(project_name)
        
        return ProjectActionResponse(
            success=True,
            data=result,
            message=f"项目 {project_name} 已删除",
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview", response_model=ETLPreviewResponse)
async def preview_etl(
    pstxnet: UploadFile = File(...),
    pstxprt: UploadFile = File(...),
    pstchip: UploadFile = File(...),
    bom: Optional[UploadFile] = File(None)
) -> ETLPreviewResponse:
    """Preview ETL import data."""
    files = {}
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from agent_system.etl_web_bridge import ETLWebExecutor
        
        files = await _stage_files(pstxnet, pstxprt, pstchip, bom)
        
        executor = ETLWebExecutor()
        result = await run_in_threadpool(executor.preview, files)
        
        preview_result = ETLPreviewResult(
            success=result.get("success", False),
            components_count=result.get("components_count"),
            topology_count=result.get("topology_count"),
            unique_nets=result.get("unique_nets"),
            parttype_coverage=result.get("parttype_coverage"),
            parttype_distribution=result.get("parttype_distribution", {}),
            power_nets_count=result.get("power_nets_count"),
            ground_nets_count=result.get("ground_nets_count"),
            top_nets=result.get("top_nets", []),
            bom_enriched_components=result.get("bom_enriched_components"),
            bom_issues=result.get("bom_issues", []),
        )
        
        return ETLPreviewResponse(
            success=preview_result.success,
            data=preview_result,
            message="ETL preview failed; inspect input and service availability" if not preview_result.success else None,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="ETL preview unavailable") from e
    finally:
        cleanup(files.values())


@router.post("/run", response_model=ETLResponse)
async def run_etl(
    pstxnet: UploadFile = File(...),
    pstxprt: UploadFile = File(...),
    pstchip: UploadFile = File(...),
    bom: Optional[UploadFile] = File(None),
    project_name: str = Form("default")
) -> ETLResponse:
    """Execute ETL import."""
    if not project_name.strip():
        raise HTTPException(status_code=422, detail="project_name must not be blank")
    files = {}
    submitted = False
    try:
        files = await _stage_files(pstxnet, pstxprt, pstchip, bom)
        store = JobStore()
        job_id = store.create(project_name)
        try:
            _workers.submit(_run_job, store, job_id, files, project_name)
            submitted = True
        except Exception:
            store.update(job_id, "failed", "failed", 0, "Could not schedule ETL",
                         "Could not schedule ETL")
            raise
        return ETLResponse(success=True, job_id=job_id, status="queued",
                           message="ETL job accepted", timestamp=datetime.now().isoformat())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail="Could not schedule ETL") from e
    finally:
        if not submitted:
            cleanup(files.values())


@router.get("/progress/{job_id}", response_model=ETLProgress)
async def get_etl_progress(job_id: str) -> ETLProgress:
    """Get ETL progress."""
    record = JobStore().get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="ETL job not found")
    return ETLProgress(
        job_id=record["job_id"], status=record["status"],
        step=ETLStep(record["step"]), progress=record["progress"],
        message=record["message"], error=record["error"],
        result=ETLResult(**record["result"]) if record["result"] else None,
        created_at=record["created_at"], updated_at=record["updated_at"])
