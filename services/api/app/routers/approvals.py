from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.approval import Approval
from app.models.task import Task
from app.schemas.approval import ApprovalCreate, ApprovalRead

router = APIRouter(tags=["approvals"])


@router.post("/tasks/{task_id}/approvals", response_model=ApprovalRead, status_code=201)
def request_approval(task_id: str, body: ApprovalCreate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    existing = db.query(Approval).filter(
        Approval.task_id == task_id,
        Approval.status == "pending"
    ).first()
    if existing:
        raise HTTPException(409, "A pending approval already exists for this task")

    approval = Approval(
        task_id=task_id,
        requested_by="nova-lite",
        summary=body.summary,
        consequence=body.consequence,
        options=body.options,
        status="pending",
    )
    db.add(approval)

    # Server-side: set task status to needs_approval
    task.status = "needs_approval"
    db.commit()
    db.refresh(approval)
    return ApprovalRead.model_validate(approval)


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/approvals/{approval_id}/respond")
def respond_to_approval(approval_id: str):
    raise HTTPException(status_code=501, detail="Not implemented")
