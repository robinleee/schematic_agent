"""Review API router."""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import List

from ..schemas.review import (
    ReviewRequest, ReviewResponse, ReviewResult, ReviewReport,
    RulesListResponse, RuleInfo, Violation, Severity
)

router = APIRouter(prefix="/review", tags=["Review"])


@router.get("/rules", response_model=RulesListResponse)
async def get_rules() -> RulesListResponse:
    """Get all available rules."""
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from ..dependencies import get_review_engine
        
        engine = get_review_engine()
        if engine is None:
            raise HTTPException(status_code=503, detail="ReviewEngine not available (Neo4j not connected)")
        rules = engine.config_manager.list_rules(enabled_only=False)
        
        rule_infos = []
        for rule in rules:
            rule_infos.append(RuleInfo(
                id=rule.id if hasattr(rule, 'id') else rule.get("id", ""),
                name=rule.name if hasattr(rule, 'name') else rule.get("name", ""),
                template_id=rule.template_id if hasattr(rule, 'template_id') else rule.get("template_id", ""),
                severity=Severity(rule.severity if hasattr(rule, 'severity') else rule.get("severity", "WARNING")),
                enabled=rule.enabled if hasattr(rule, 'enabled') else rule.get("enabled", True),
                description=rule.description if hasattr(rule, 'description') else rule.get("description")
            ))
        
        return RulesListResponse(
            success=True,
            data=rule_infos,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail="Review infrastructure unavailable") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Unable to load review rules") from e


@router.post("/run", response_model=ReviewResponse)
async def run_review(request: ReviewRequest) -> ReviewResponse:
    """Run review with specified rules."""
    if request.project_id is not None and not request.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be blank")
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from ..dependencies import get_review_engine
        
        # Keep the aggregate call compatible with lightweight offline/fake
        # providers while passing an explicit project to the real provider.
        try:
            engine = (
                get_review_engine()
                if request.project_id is None
                else get_review_engine(request.project_id)
            )
        except TypeError as e:
            # A provider that cannot create a project-scoped engine is
            # unavailable for this request.  Do not fall back to aggregate
            # data, which would break project isolation.
            raise HTTPException(
                status_code=503,
                detail="Review infrastructure unavailable",
            ) from e
        if engine is None:
            raise HTTPException(status_code=503, detail="ReviewEngine not available (Neo4j not connected)")
        violations = engine.run_rules(
            rule_ids=request.rule_ids,
            enabled_only=request.enabled_only
        )
        
        # Convert violations to response format
        violation_responses = []
        for v in violations:
            # Support both object attributes and dict access
            rule_id = v.rule_id if hasattr(v, 'rule_id') else (v.get("rule_id", "") if isinstance(v, dict) else "")
            rule_name = v.rule_name if hasattr(v, 'rule_name') else (v.get("rule_name", "") if isinstance(v, dict) else "")
            refdes = v.refdes if hasattr(v, 'refdes') else (v.get("refdes", "") if isinstance(v, dict) else "")
            net_name = v.net_name if hasattr(v, 'net_name') else (v.get("net_name") if isinstance(v, dict) else None)
            description = v.description if hasattr(v, 'description') else (v.get("description", "") if isinstance(v, dict) else "")
            severity_raw = v.severity if hasattr(v, 'severity') else (v.get("severity", "WARNING") if isinstance(v, dict) else "WARNING")
            expected = v.expected if hasattr(v, 'expected') else (v.get("expected") if isinstance(v, dict) else None)
            actual = v.actual if hasattr(v, 'actual') else (v.get("actual") if isinstance(v, dict) else None)
            suggested_fix = v.suggested_fix if hasattr(v, 'suggested_fix') else (v.get("suggested_fix") if isinstance(v, dict) else None)
            
            violation_responses.append(Violation(
                rule_id=rule_id,
                rule_name=rule_name,
                refdes=refdes,
                net_name=net_name,
                description=description,
                severity=Severity(severity_raw.value if hasattr(severity_raw, 'value') else severity_raw),
                expected=expected,
                actual=actual,
                suggested_fix=suggested_fix
            ))
        
        # Generate summary from violations
        total = len(violation_responses)
        errors = sum(1 for v in violation_responses if v.severity == Severity.ERROR)
        warnings = sum(1 for v in violation_responses if v.severity == Severity.WARNING)
        infos = sum(1 for v in violation_responses if v.severity == Severity.INFO)
        by_rule = {}
        for v in violation_responses:
            by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1
        
        review_report = ReviewReport(
            total=total,
            errors=errors,
            warnings=warnings,
            infos=infos,
            by_rule=by_rule,
            generated_at=datetime.now().isoformat()
        )
        
        # Generate markdown report
        report_lines = [f"# 审查报告\n\n总违规数: {total}\n- 错误: {errors}\n- 警告: {warnings}\n- 信息: {infos}\n"]
        for v in violation_responses:
            report_lines.append(f"- **{v.rule_name}** ({v.severity.value}): {v.refdes} - {v.description}\n")
        report_markdown = "\n".join(report_lines)
        
        review_result = ReviewResult(
            violations=violation_responses,
            report_markdown=report_markdown,
            summary=review_report
        )
        
        return ReviewResponse(
            success=True,
            data=review_result,
            timestamp=datetime.now().isoformat()
        )
        
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail="Review infrastructure unavailable") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Review failed") from e
