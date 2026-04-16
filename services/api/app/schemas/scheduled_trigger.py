from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


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
    interval_seconds: int | None = Field(default=None, gt=0)
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    last_fired_at: datetime | None = None


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
