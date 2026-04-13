from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, String
from sqlalchemy.types import JSON
from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    correlation_id = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    risk_class = Column(String, nullable=False, default="low")
    actor_type = Column(String, nullable=False, default="system")
    actor_id = Column(String, nullable=True)
    entity_refs = Column(JSON, nullable=False, default=list)
    task_ref = Column(String, nullable=True)
