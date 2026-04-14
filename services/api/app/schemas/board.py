from typing import Any
from pydantic import BaseModel, ConfigDict
from app.schemas.task import TaskResponse


class BoardColumnMove(BaseModel):
    board_column_id: str


class BoardColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    order: int
    work_in_progress_limit: int | None
    status_filter: dict[str, Any] | None
    description: str | None


class BoardResponse(BaseModel):
    columns: list[BoardColumnResponse]
    tasks_by_column: dict[str, list[TaskResponse]]
