from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.board_column import BoardColumn
from app.models.task import Task
from app.schemas.board import BoardColumnMove, BoardColumnResponse, BoardResponse
from app.schemas.task import TaskResponse

router = APIRouter(prefix="/board", tags=["board"])


@router.get("", response_model=BoardResponse)
def get_board(
    status: str | None = Query(None),
    risk_class: str | None = Query(None),
    priority: str | None = Query(None),
    labels: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    columns = db.query(BoardColumn).order_by(BoardColumn.order).all()

    # Inbox is the fallback column for tasks with no board_column_id
    inbox = next((c for c in columns if c.order == 1), None)

    # Fetch and optionally filter tasks
    task_query = db.query(Task)
    if status:
        task_query = task_query.filter(Task.status == status)
    if risk_class:
        task_query = task_query.filter(Task.risk_class == risk_class)
    if priority:
        task_query = task_query.filter(Task.priority == priority)
    tasks = task_query.all()

    # Python-side label filter (JSON column, SQLite-safe)
    if labels:
        tasks = [t for t in tasks if all(lbl in (t.labels or []) for lbl in labels)]

    # Build grouped response
    tasks_by_column: dict[str, list[TaskResponse]] = {c.id: [] for c in columns}
    for task in tasks:
        col_id = task.board_column_id
        if col_id not in tasks_by_column:
            col_id = inbox.id if inbox else None
        if col_id:
            tasks_by_column[col_id].append(TaskResponse.from_orm_task(task))

    return BoardResponse(
        columns=[BoardColumnResponse.model_validate(c) for c in columns],
        tasks_by_column=tasks_by_column,
    )


@router.patch("/tasks/{task_id}")
def move_task(task_id: str, body: BoardColumnMove):
    raise HTTPException(status_code=501, detail="Not implemented")
