from typing import Literal
from pydantic import BaseModel


class LLMRouteRequest(BaseModel):
    purpose: str
    input: dict  # {"messages": [{"role": "...", "content": "..."}]}
    privacy_preference: Literal["local_preferred", "local_required", "cloud_allowed"] = "local_preferred"
    tool_use_required: bool = False


class LLMRouteResponse(BaseModel):
    provider_id: str
    model_ref: str
    output: str
    # run_id omitted — Phase 5 observability
