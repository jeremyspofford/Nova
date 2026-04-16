from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.scheduled_trigger import ScheduledTrigger
from app.schemas.scheduled_trigger import (
    ScheduledTriggerListResponse,
    ScheduledTriggerRead,
    ScheduledTriggerUpdate,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/triggers", response_model=ScheduledTriggerListResponse)
def list_triggers(db: Session = Depends(get_db)):
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return ScheduledTriggerListResponse(
        triggers=[ScheduledTriggerRead.model_validate(t) for t in triggers]
    )


@router.patch("/triggers/{trigger_id}", response_model=ScheduledTriggerRead)
def update_trigger(
    trigger_id: str,
    body: ScheduledTriggerUpdate,
    db: Session = Depends(get_db),
):
    trigger = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(404, detail="Trigger not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(trigger, field, value)
    db.commit()
    db.refresh(trigger)
    return ScheduledTriggerRead.model_validate(trigger)
