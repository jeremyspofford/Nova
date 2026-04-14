from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Any


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None
    tool_name: str | None
    workflow_ref: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    executor_type: str
    executor_id: str | None


class RunListResponse(BaseModel):
    runs: list[RunRead]
