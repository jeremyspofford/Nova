from fastapi import APIRouter

router = APIRouter(tags=["runs"])

@router.get("/runs")
def list_runs():
    raise NotImplementedError

@router.get("/runs/{run_id}")
def get_run(run_id: str):
    raise NotImplementedError

@router.get("/tasks/{task_id}/runs")
def list_task_runs(task_id: str):
    raise NotImplementedError
