from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskListResponse, TaskResponse, TaskUpdate
from app.utils import STATUS_TO_COLUMN

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    initial_status = "pending"
    task = Task(
        id=str(uuid4()),
        title=body.title,
        description=body.description,
        goal=body.goal,
        origin_event_id=body.origin_event_id,
        owner_type=body.owner_type.value if body.owner_type else None,
        owner_id=body.owner_id,
        priority=body.priority.value,
        risk_class=body.risk_class.value,
        approval_required=body.approval_required,
        due_at=body.due_at,
        labels=body.labels,
        metadata_=body.metadata,
        board_column_id=STATUS_TO_COLUMN.get(initial_status, "col-inbox"),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskResponse.from_orm_task(task)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    status: str | None = Query(None),
    owner_type: str | None = Query(None),
    owner_id: str | None = Query(None),
    board_column_id: str | None = Query(None),
    priority: str | None = Query(None),
    risk_class: str | None = Query(None),
    approval_required: bool | None = Query(None),
    origin_event_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if owner_type:
        query = query.filter(Task.owner_type == owner_type)
    if owner_id:
        query = query.filter(Task.owner_id == owner_id)
    if board_column_id:
        query = query.filter(Task.board_column_id == board_column_id)
    if priority:
        query = query.filter(Task.priority == priority)
    if risk_class:
        query = query.filter(Task.risk_class == risk_class)
    if approval_required is not None:
        query = query.filter(Task.approval_required == approval_required)
    if origin_event_id:
        query = query.filter(Task.origin_event_id == origin_event_id)
    tasks = query.offset(offset).limit(limit).all()
    return TaskListResponse(tasks=[TaskResponse.from_orm_task(t) for t in tasks])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.from_orm_task(task)


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(task_id: str, body: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        # Pydantic model_dump() already resolves enum members to their .value strings
        attr = "metadata_" if field == "metadata" else field
        setattr(task, attr, value)
    if "status" in update_data and "board_column_id" not in update_data:
        task.board_column_id = STATUS_TO_COLUMN.get(update_data["status"], task.board_column_id)
    db.commit()
    db.refresh(task)
    return TaskResponse.from_orm_task(task)
