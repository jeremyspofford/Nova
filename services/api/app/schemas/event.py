from pydantic import BaseModel

class EventCreate(BaseModel):
    type: str
    source: str
    subject: str
    payload: dict = {}
