from datetime import datetime
from pydantic import BaseModel


class ScheduledTriggerRead(BaseModel):
    id: str
    name: str
    description: str | None
    interval_seconds: int
    active_hours_start: str | None
    active_hours_end: str | None
    enabled: bool
    payload_template: dict
    last_fired_at: datetime | None

    model_config = {"from_attributes": True}


class ScheduledTriggerUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    active_hours_start: str | None = None
    active_hours_end: str | None = None
    last_fired_at: datetime | None = None


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
