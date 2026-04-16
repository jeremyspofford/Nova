"""
Tool handlers that manage scheduled triggers from chat.
Operate in-process via SQLAlchemy session — no HTTP loop-back.
"""
from sqlalchemy.orm import Session

from app.models.scheduled_trigger import ScheduledTrigger
from app.schemas.scheduled_trigger import ScheduledTriggerCreate, ScheduledTriggerUpdate


def handle_scheduler_create_trigger(input: dict, db: Session) -> dict:
    body = ScheduledTriggerCreate(**input)  # raises ValidationError if invalid
    if db.query(ScheduledTrigger).filter_by(id=body.id).first():
        raise ValueError(f"Trigger '{body.id}' already exists")
    trigger = ScheduledTrigger(**body.model_dump())
    db.add(trigger)
    db.commit()
    return {
        "id": body.id,
        "summary": f"Created trigger '{body.name}' (id={body.id}, {body.cron_expression})",
    }


def handle_scheduler_list_triggers(input: dict, db: Session) -> dict:
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return {
        "triggers": [
            {
                "id": t.id,
                "name": t.name,
                "cron_expression": t.cron_expression,
                "enabled": t.enabled,
                "payload_kind": "tool" if "tool" in (t.payload_template or {}) else "goal",
                "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
            }
            for t in triggers
        ]
    }


def handle_scheduler_update_trigger(input: dict, db: Session) -> dict:
    trigger_id = input["id"]
    updates = input.get("updates") or {}
    trigger = db.query(ScheduledTrigger).filter_by(id=trigger_id).first()
    if not trigger:
        raise ValueError(f"Trigger '{trigger_id}' not found")
    body = ScheduledTriggerUpdate(**updates)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(trigger, field, value)
    db.commit()
    return {"summary": f"Updated trigger '{trigger_id}'", "applied": body.model_dump(exclude_unset=True)}


def handle_scheduler_delete_trigger(input: dict, db: Session) -> dict:
    trigger_id = input["id"]
    trigger = db.query(ScheduledTrigger).filter_by(id=trigger_id).first()
    if not trigger:
        raise ValueError(f"Trigger '{trigger_id}' not found")
    db.delete(trigger)
    db.commit()
    return {"summary": f"Deleted trigger '{trigger_id}'"}
