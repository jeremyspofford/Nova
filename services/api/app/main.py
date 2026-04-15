from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.routers import health, tasks, events, board, tools, runs, approvals, entities, llm, conversations
import app.database as _db
from app.tools.seed import seed_tools, seed_llm_providers, seed_board_columns
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = _db.SessionLocal()
    try:
        seed_tools(db)
        seed_llm_providers(db, settings)
        seed_board_columns(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Nova API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(NotImplementedError)
async def not_implemented_handler(request: Request, exc: NotImplementedError):
    return JSONResponse(status_code=501, content={"detail": "Not implemented"})


app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(board.router)
app.include_router(tools.router)
app.include_router(runs.router)
app.include_router(approvals.router)
app.include_router(entities.router)
app.include_router(llm.router)
app.include_router(conversations.router)
