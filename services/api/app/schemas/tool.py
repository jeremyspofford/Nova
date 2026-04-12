from pydantic import BaseModel

class ToolInvoke(BaseModel):
    input: dict
    task_id: str | None = None
    requested_by: str | None = None
