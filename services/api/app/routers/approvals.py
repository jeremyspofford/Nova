from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.approval import Approval
from app.models.task import Task
from app.schemas.approval import ApprovalCreate, ApprovalRead, ApprovalRespondRequest

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


@router.get("/tasks/{task_id}/approvals", response_model=list[ApprovalRead])
def list_task_approvals(task_id: str, db: Session = Depends(get_db)):
    approvals = db.query(Approval).filter(Approval.task_id == task_id).all()
    return [ApprovalRead.model_validate(a) for a in approvals]


@router.get("/approvals/{approval_id}", response_model=ApprovalRead)
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    return ApprovalRead.model_validate(approval)


@router.post("/approvals/{approval_id}/respond", response_model=ApprovalRead)
def respond_to_approval(
    approval_id: str,
    body: ApprovalRespondRequest,
    db: Session = Depends(get_db),
):
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    if approval.status != "pending":
        raise HTTPException(
            409,
            f"Approval is not pending (current status: {approval.status})"
        )

    # "approve" is the only value that maps to approved; all others are denied
    outcome = "approved" if body.decision == "approve" else "denied"

    approval.status = outcome
    approval.decided_by = body.decided_by
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision = body.decision
    approval.reason = body.reason

    task = db.query(Task).filter(Task.id == approval.task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "ready" if outcome == "approved" else "cancelled"

    db.commit()
    db.refresh(approval)
    return ApprovalRead.model_validate(approval)
