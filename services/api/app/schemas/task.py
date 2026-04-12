from datetime import datetime
from typing import Any
from pydantic import BaseModel
from app.schemas.common import LastDecision, OwnerType, Priority, RiskClass, TaskStatus


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    goal: str | None = None
    origin_event_id: str | None = None
    owner_type: OwnerType | None = None
    owner_id: str | None = None
    priority: Priority = Priority.normal
    risk_class: RiskClass = RiskClass.low
    approval_required: bool = False
    due_at: datetime | None = None
    labels: list[str] = []
    metadata: dict[str, Any] = {}


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    status: TaskStatus | None = None
    last_decision: LastDecision | None = None
    priority: Priority | None = None
    board_column_id: str | None = None
    owner_type: OwnerType | None = None
    owner_id: str | None = None
    due_at: datetime | None = None
    next_check_at: datetime | None = None
    result_summary: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    goal: str | None
    status: str
    origin_event_id: str | None
    board_column_id: str | None
    owner_type: str | None
    owner_id: str | None
    created_at: datetime
    updated_at: datetime
    due_at: datetime | None
    priority: str
    risk_class: str
    approval_required: bool
    last_decision: str
    next_check_at: datetime | None
    result_summary: str | None
    labels: list[str]
    metadata: dict[str, Any]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_task(cls, task) -> "TaskResponse":
        return cls(
            id=task.id,
            title=task.title,
            description=task.description,
            goal=task.goal,
            status=task.status,
            origin_event_id=task.origin_event_id,
            board_column_id=task.board_column_id,
            owner_type=task.owner_type,
            owner_id=task.owner_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
            due_at=task.due_at,
            priority=task.priority,
            risk_class=task.risk_class,
            approval_required=task.approval_required,
            last_decision=task.last_decision,
            next_check_at=task.next_check_at,
            result_summary=task.result_summary,
            labels=task.labels or [],
            metadata=task.metadata_ or {},
        )


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
