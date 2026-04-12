from fastapi import APIRouter
from app.schemas.tool import ToolInvoke

router = APIRouter(prefix="/tools", tags=["tools"])

@router.get("")
def list_tools():
    raise NotImplementedError

@router.get("/{name}")
def get_tool(name: str):
    raise NotImplementedError

@router.post("/{name}/invoke")
def invoke_tool(name: str, body: ToolInvoke):
    raise NotImplementedError
