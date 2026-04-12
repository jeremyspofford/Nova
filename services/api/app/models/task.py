from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.types import JSON
from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    goal = Column(String, nullable=True)
    status = Column(String, nullable=False, default="inbox")
    origin_event_id = Column(String, nullable=True)
    board_column_id = Column(String, nullable=True)
    owner_type = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)
    priority = Column(String, nullable=False, default="normal")
    risk_class = Column(String, nullable=False, default="low")
    approval_required = Column(Boolean, nullable=False, default=False)
    last_decision = Column(String, nullable=False, default="none")
    next_check_at = Column(DateTime(timezone=True), nullable=True)
    result_summary = Column(String, nullable=True)
    labels = Column(JSON, nullable=False, default=list)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
