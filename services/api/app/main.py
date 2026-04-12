from fastapi import FastAPI
from app.routers import health, tasks

app = FastAPI(title="Nova API", version="0.1.0")

app.include_router(health.router)
app.include_router(tasks.router)
