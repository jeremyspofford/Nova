from pydantic import BaseModel

class RunResponse(BaseModel):
    id: str
    status: str
