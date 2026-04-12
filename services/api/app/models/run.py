from uuid import uuid4
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.types import JSON
from app.database import Base


class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    task_id = Column(String, nullable=True)
    tool_name = Column(String, nullable=True)
    workflow_ref = Column(String, nullable=True)
    status = Column(String, nullable=False, default="queued")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    input = Column(JSON, nullable=True)
    output = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    executor_type = Column(String, nullable=False, default="system")
    executor_id = Column(String, nullable=True)
