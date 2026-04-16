from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.scheduled_trigger import ScheduledTrigger
from app.schemas.scheduled_trigger import (
    ScheduledTriggerCreate,
    ScheduledTriggerListResponse,
    ScheduledTriggerRead,
    ScheduledTriggerUpdate,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def system_info():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "deployment_mode": settings.deployment_mode,
    }


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


@router.post("/triggers", response_model=ScheduledTriggerRead)
def create_trigger(body: ScheduledTriggerCreate, db: Session = Depends(get_db)):
    existing = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == body.id).first()
    if existing:
        raise HTTPException(409, detail=f"Trigger '{body.id}' already exists")
    trigger = ScheduledTrigger(**body.model_dump())
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    return ScheduledTriggerRead.model_validate(trigger)


@router.delete("/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, db: Session = Depends(get_db)):
    trigger = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(404, detail="Trigger not found")
    db.delete(trigger)
    db.commit()
    return {"status": "deleted", "id": trigger_id}
