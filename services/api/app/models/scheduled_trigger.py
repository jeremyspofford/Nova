from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.types import JSON
from app.database import Base


class ScheduledTrigger(Base):
    __tablename__ = "scheduled_triggers"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    cron_expression = Column(String, nullable=False)
    active_hours_start = Column(String, nullable=True)
    active_hours_end = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    payload_template = Column(JSON, nullable=False, default=dict)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
