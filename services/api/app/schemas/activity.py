from datetime import datetime
from pydantic import BaseModel


class ActivityEntryRead(BaseModel):
    id: str
    tool_name: str
    trigger_type: str
    status: str
    summary: str | None
    input: dict | list | None
    output: str | None  # JSON string, server-truncated to 2000 chars
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ActivityResponse(BaseModel):
    entries: list[ActivityEntryRead]
    total: int
