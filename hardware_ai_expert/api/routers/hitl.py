"""HITL (Human-in-the-Loop) API router."""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Optional

from ..schemas.hitl import (
    PendingListResponse, PendingReview, ReviewStatus,
    ReviewActionRequest, ReviewActionResponse,
    ExportRequest, ExportResponse,
    DatasheetPendingReview, DatasheetPendingListResponse,
    DatasheetReviewActionRequest, DatasheetPersistResponse,
    ReviewActionData, ReviewActionResult
)
from ..dependencies import get_hitl_manager

router = APIRouter(prefix="/hitl", tags=["HITL"])


def _run_actions(manager, request: ReviewActionRequest) -> ReviewActionResponse:
    results = []
    for rid in request.review_ids:
        try:
            ok = getattr(manager, request.action)(
                rid, reviewer=request.reviewer or "engineer", comment=request.comment or ""
            )
            results.append(ReviewActionResult(
                review_id=rid, action=request.action, success=bool(ok),
                error=None if ok else "Review not pending or update failed",
            ))
        except Exception as exc:
            results.append(ReviewActionResult(
                review_id=rid, action=request.action, success=False, error=str(exc),
            ))
    succeeded = sum(item.success for item in results)
    failed = len(results) - succeeded
    return ReviewActionResponse(
        success=failed == 0,
        data=ReviewActionData(results=results, succeeded=succeeded, failed=failed),
        message=f"已处理 {succeeded}/{len(results)} 条记录",
        timestamp=datetime.now().isoformat(),
    )


@router.get("/pending", response_model=PendingListResponse)
async def get_pending(
    status: Optional[ReviewStatus] = Query(ReviewStatus.PENDING),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200)
) -> PendingListResponse:
    """Get pending review list."""
    try:
        manager = get_hitl_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="HITLManager not available (Neo4j not connected)")
        all_items = manager.get_pending_list(
            status=status.value if status else "pending"
        )
        
        # Manual pagination
        total = len(all_items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = all_items[start:end]
        
        pending_reviews = []
        for item in page_items:
            pending_reviews.append(PendingReview(
                review_id=item.review_id if hasattr(item, 'review_id') else str(id(item)),
                rule_id=item.rule_id,
                rule_name=item.rule_name,
                refdes=item.refdes,
                net_name=item.net_name,
                description=item.description,
                severity=item.severity,
                expected=item.expected,
                actual=item.actual,
                suggested_fix=item.suggested_fix,
                status=ReviewStatus(item.status) if hasattr(item, 'status') else ReviewStatus.PENDING,
                reviewer=item.reviewer if hasattr(item, 'reviewer') else None,
                review_comment=item.review_comment if hasattr(item, 'review_comment') else None,
                reviewed_at=item.reviewed_at if hasattr(item, 'reviewed_at') else None,
                created_at=item.created_at if hasattr(item, 'created_at') else datetime.now().isoformat(),
                source=item.source if hasattr(item, 'source') else "agent"
            ))
        
        return PendingListResponse(
            success=True,
            data=pending_reviews,
            total=total,
            page=page,
            page_size=page_size,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/action", response_model=ReviewActionResponse)
async def review_action(request: ReviewActionRequest) -> ReviewActionResponse:
    """Execute review action (approve/reject)."""
    try:
        manager = get_hitl_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="HITLManager not available")
        return _run_actions(manager, request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export", response_model=ExportResponse)
async def export_approved(request: ExportRequest) -> ExportResponse:
    """Save all approved rules to local custom_rules.yaml (not a download)."""
    try:
        manager = get_hitl_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="HITLManager not available")
        result = manager.save_approved_rules()
        if "error" in result:
            raise HTTPException(status_code=500, detail="Rule persistence failed")
        return ExportResponse(
            success=True,
            data={"saved": result["saved"], "rules": result.get("rules", []),
                  "location": "custom_rules.yaml" if result.get("saved") else None},
            message=result.get("message") or f"已保存 {result['saved']} 条规则",
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasheet/pending", response_model=DatasheetPendingListResponse)
async def get_datasheet_pending() -> DatasheetPendingListResponse:
    """Get pending datasheet parameter reviews."""
    try:
        from agent_system.datasheet_hitl import DatasheetHITLManager

        manager = DatasheetHITLManager()
        items = manager.get_pending_list()
        data = [
            DatasheetPendingReview(
                review_id=item.review_id,
                mpn=item.mpn,
                param_type=item.param_type,
                param_name=item.param_name,
                value=item.value,
                unit=item.unit,
                min_value=item.min_value,
                max_value=item.max_value,
                condition=item.condition,
                source_text=item.source_text,
                confidence=item.confidence,
                extraction_method=item.extraction_method,
                status=item.status,
                reviewer=item.reviewer or None,
                review_comment=item.review_comment or None,
                reviewed_at=item.reviewed_at or None,
                created_at=item.created_at,
                source_file=item.source_file,
            )
            for item in items
        ]
        return DatasheetPendingListResponse(
            success=True,
            data=data,
            total=len(data),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/datasheet/action", response_model=ReviewActionResponse)
async def datasheet_review_action(request: DatasheetReviewActionRequest) -> ReviewActionResponse:
    """Approve/reject datasheet parameter reviews."""
    try:
        from agent_system.datasheet_hitl import DatasheetHITLManager

        manager = DatasheetHITLManager()
        return _run_actions(manager, request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/datasheet/persist", response_model=DatasheetPersistResponse)
async def persist_datasheet_approved() -> DatasheetPersistResponse:
    """Persist approved datasheet parameters into review_engine/config/amr_data.yaml."""
    try:
        from agent_system.datasheet_hitl import DatasheetHITLManager

        manager = DatasheetHITLManager()
        result = manager.save_approved_to_amr()
        if result.get("error") or str(result.get("message", "")).startswith("保存失败:"):
            raise HTTPException(status_code=500, detail=result.get("error") or result["message"])
        return DatasheetPersistResponse(
            success=True,
            data=result,
            message=result.get("message"),
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
