from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.types import JSON
from app.database import Base


class ScheduledTrigger(Base):
    __tablename__ = "scheduled_triggers"

    id = Column(String, primary_key=True)        # e.g. "system-heartbeat"
    name = Column(String, nullable=False)         # display name
    description = Column(String, nullable=True)
    interval_seconds = Column(Integer, nullable=False)
    active_hours_start = Column(String, nullable=True)  # "09:00" UTC, or None = always
    active_hours_end = Column(String, nullable=True)    # "22:00" UTC, or None = always
    enabled = Column(Boolean, nullable=False, default=True)
    payload_template = Column(JSON, nullable=False, default=dict)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
