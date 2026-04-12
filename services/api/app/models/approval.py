from uuid import uuid4
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.types import JSON
from app.database import Base


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    task_id = Column(String, nullable=False)
    requested_by = Column(String, nullable=False)
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    summary = Column(String, nullable=False)
    consequence = Column(String, nullable=True)
    options = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="pending")
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision = Column(String, nullable=True)
    reason = Column(String, nullable=True)
