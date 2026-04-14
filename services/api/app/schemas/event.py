from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    type: str
    source: str
    subject: str
    payload: dict[str, Any] = {}
    priority: str = "normal"
    risk_class: str = "low"
    correlation_id: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    entity_refs: list[str] = []
    task_ref: str | None = None


class EventCreateResponse(BaseModel):
    """Minimal POST /events response per 15-16 spec."""
    id: str
    timestamp: datetime


class EventRead(BaseModel):
    """Full event record returned in GET /events."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    source: str
    subject: str
    payload: dict[str, Any]
    timestamp: datetime
    priority: str
    risk_class: str
    actor_type: str
    actor_id: str | None
    entity_refs: list[str]
    task_ref: str | None
    correlation_id: str | None


class EventListResponse(BaseModel):
    events: list[EventRead]
