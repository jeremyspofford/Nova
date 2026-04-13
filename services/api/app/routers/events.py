from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.event import Event
from app.schemas.event import (
    EventCreate,
    EventCreateResponse,
    EventListResponse,
    EventRead,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventCreateResponse, status_code=201)
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    event = Event(
        type=body.type,
        source=body.source,
        subject=body.subject,
        payload=body.payload,
        priority=body.priority,
        risk_class=body.risk_class,
        correlation_id=body.correlation_id,
        actor_type=body.actor_type,
        actor_id=body.actor_id,
        entity_refs=body.entity_refs,
        task_ref=body.task_ref,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return EventCreateResponse(id=event.id, timestamp=event.timestamp)


@router.get("", response_model=EventListResponse)
def list_events(
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; return events after this time"),
    type: str | None = Query(None),
    source: str | None = Query(None),
    priority: str | None = Query(None),
    risk_class: str | None = Query(None),
    correlation_id: str | None = Query(None),
    task_ref: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Event)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, detail="Invalid 'since' format. Use ISO 8601, e.g. 2026-04-13T10:00:00Z")
        query = query.filter(Event.timestamp > since_dt)
    if type:
        query = query.filter(Event.type == type)
    if source:
        query = query.filter(Event.source == source)
    if priority:
        query = query.filter(Event.priority == priority)
    if risk_class:
        query = query.filter(Event.risk_class == risk_class)
    if correlation_id:
        query = query.filter(Event.correlation_id == correlation_id)
    if task_ref:
        query = query.filter(Event.task_ref == task_ref)
    events = query.order_by(Event.timestamp).offset(offset).limit(limit).all()
    return EventListResponse(events=[EventRead.model_validate(e) for e in events])
