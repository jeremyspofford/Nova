from pydantic import BaseModel
from typing import Literal

class LLMRouteRequest(BaseModel):
    purpose: str
    input: dict
    privacy_preference: Literal["local_preferred", "local_required", "cloud_allowed"] = "local_preferred"
    tool_use_required: bool = False
