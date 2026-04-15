import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.run import Run
from app.schemas.activity import ActivityEntryRead, ActivityResponse

router = APIRouter(prefix="/activity", tags=["activity"])


def _serialize_output(output) -> str | None:
    if output is None:
        return None
    s = json.dumps(output)
    if len(s) > 2000:
        return s[:2000] + " ... [truncated]"
    return s


@router.get("", response_model=ActivityResponse)
def get_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    filters = [
        Run.status.in_(["succeeded", "failed", "running"]),
        Run.tool_name.isnot(None),
    ]
    total = db.query(func.count(Run.id)).filter(*filters).scalar() or 0
    runs = (
        db.query(Run)
        .filter(*filters)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return ActivityResponse(
        entries=[
            ActivityEntryRead(
                id=r.id,
                tool_name=r.tool_name,
                trigger_type=r.trigger_type,
                status=r.status,
                summary=r.summary,
                input=r.input,
                output=_serialize_output(r.output),
                error=r.error,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in runs
        ],
        total=total,
    )
