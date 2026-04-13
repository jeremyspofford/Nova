from typing import Any
from pydantic import BaseModel, ConfigDict


class ToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    display_name: str
    description: str
    adapter_type: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    risk_class: str
    requires_approval: bool
    timeout_seconds: int
    enabled: bool
    tags: list[str]


class ToolListResponse(BaseModel):
    tools: list[ToolResponse]


class ToolInvokeRequest(BaseModel):
    input: dict[str, Any]
    task_id: str | None = None
    requested_by: str | None = None


class ToolInvokeResponse(BaseModel):
    run_id: str
    status: str
