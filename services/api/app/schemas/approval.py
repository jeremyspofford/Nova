from pydantic import BaseModel

class ApprovalRequest(BaseModel):
    summary: str
    consequence: str | None = None
    options: list[str] = []

class ApprovalResponse(BaseModel):
    decision: str
    decided_by: str
    reason: str | None = None
