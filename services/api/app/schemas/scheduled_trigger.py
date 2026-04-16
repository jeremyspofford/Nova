from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ScheduledTriggerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    interval_seconds: int
    active_hours_start: str | None
    active_hours_end: str | None
    enabled: bool
    payload_template: dict[str, Any]
    last_fired_at: datetime | None


class ScheduledTriggerUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    active_hours_start: str | None = None
    active_hours_end: str | None = None
    last_fired_at: datetime | None = None


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
