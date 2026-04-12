from fastapi import APIRouter
from app.schemas.event import EventCreate

router = APIRouter(prefix="/events", tags=["events"])

@router.post("")
def create_event(body: EventCreate):
    raise NotImplementedError

@router.get("")
def list_events():
    raise NotImplementedError
