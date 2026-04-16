from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


def _validate_cron(v: str) -> str:
    from croniter import croniter
    if not croniter.is_valid(v):
        raise ValueError(f"invalid cron expression: {v}")
    return v


def _validate_payload_shape(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    has_tool = "tool" in payload
    has_goal = "goal" in payload
    if has_tool and has_goal:
        raise ValueError("payload cannot contain both 'tool' and 'goal'")
    if not (has_tool or has_goal):
        raise ValueError("payload must contain either 'tool' or 'goal'")
    if has_goal:
        goal = payload["goal"]
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
    if has_tool:
        tool = payload["tool"]
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError("tool must be a non-empty string")
    return payload


class ScheduledTriggerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    cron_expression: str
    active_hours_start: str | None
    active_hours_end: str | None
    enabled: bool
    payload_template: dict[str, Any]
    last_fired_at: datetime | None


class ScheduledTriggerCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str
    description: str | None = None
    cron_expression: str
    payload_template: dict[str, Any]
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v): return _validate_cron(v)

    @model_validator(mode="after")
    def _payload(self):
        _validate_payload_shape(self.payload_template)
        return self


class ScheduledTriggerUpdate(BaseModel):
    enabled: bool | None = None
    cron_expression: str | None = None
    payload_template: dict[str, Any] | None = None
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    last_fired_at: datetime | None = None

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v):
        return _validate_cron(v) if v is not None else v

    @model_validator(mode="after")
    def _payload(self):
        if self.payload_template is not None:
            _validate_payload_shape(self.payload_template)
        return self


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
