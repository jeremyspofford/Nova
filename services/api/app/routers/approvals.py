from fastapi import APIRouter
from app.schemas.approval import ApprovalRequest, ApprovalResponse

router = APIRouter(tags=["approvals"])

@router.post("/tasks/{task_id}/approvals")
def request_approval(task_id: str, body: ApprovalRequest):
    raise NotImplementedError

@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    raise NotImplementedError

@router.post("/approvals/{approval_id}/respond")
def respond_to_approval(approval_id: str, body: ApprovalResponse):
    raise NotImplementedError
