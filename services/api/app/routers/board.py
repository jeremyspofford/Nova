from fastapi import APIRouter
from app.schemas.board import BoardColumnMove

router = APIRouter(prefix="/board", tags=["board"])

@router.get("")
def get_board():
    raise NotImplementedError

@router.patch("/tasks/{task_id}")
def move_task(task_id: str, body: BoardColumnMove):
    raise NotImplementedError
