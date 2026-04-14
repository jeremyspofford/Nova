from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.run import Run
from app.models.tool import Tool
from app.schemas.tool import ToolInvokeRequest, ToolInvokeResponse, ToolListResponse, ToolResponse
from app.tools import handlers as tool_handlers

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    enabled: bool | None = Query(True, description="Filter by enabled status. Default true."),
    db: Session = Depends(get_db),
):
    query = db.query(Tool)
    if enabled is not None:
        query = query.filter(Tool.enabled == enabled)
    tools = query.all()
    return ToolListResponse(tools=[ToolResponse.model_validate(t) for t in tools])


@router.get("/{name}", response_model=ToolResponse)
def get_tool(name: str, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.name == name).first()
    if not tool:
        raise HTTPException(404, "Tool not found")
    return ToolResponse.model_validate(tool)


@router.post("/{name}/invoke", response_model=ToolInvokeResponse)
def invoke_tool(name: str, body: ToolInvokeRequest, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.name == name).first()
    if not tool:
        raise HTTPException(404, "Tool not found")
    if not tool.enabled:
        raise HTTPException(400, "Tool is disabled")

    run = Run(
        id=str(uuid4()),
        tool_name=name,
        task_id=body.task_id,
        executor_type="agent",
        input=body.input,
        status="queued",
    )
    db.add(run)
    db.commit()

    # Transition to running
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        output = tool_handlers.dispatch(name, body.input, db)
        run.status = "succeeded"
        run.output = output
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

    db.refresh(run)
    return ToolInvokeResponse(run_id=run.id, status=run.status, output=run.output, error=run.error)
