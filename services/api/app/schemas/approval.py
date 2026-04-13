from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ApprovalCreate(BaseModel):
    summary: str
    consequence: str | None = None
    options: list[str] = ["approve", "deny"]


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    requested_by: str
    requested_at: datetime
    summary: str
    consequence: str | None
    options: list[str]
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision: str | None
    reason: str | None
