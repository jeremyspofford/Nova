from pydantic import BaseModel

class EntitySyncRequest(BaseModel):
    source: str | None = None
