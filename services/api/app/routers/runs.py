from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.run import Run
from app.models.task import Task
from app.schemas.run import RunListResponse, RunRead

router = APIRouter(tags=["runs"])


@router.get("/runs", tags=["runs"])
def list_runs():
    raise HTTPException(status_code=501)


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return RunRead.model_validate(run)


@router.get("/tasks/{task_id}/runs", response_model=RunListResponse)
def list_task_runs(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    runs = (
        db.query(Run)
        .filter(Run.task_id == task_id)
        .order_by(Run.created_at.desc())
        .all()
    )
    return RunListResponse(runs=[RunRead.model_validate(r) for r in runs])
