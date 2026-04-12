from uuid import uuid4
from sqlalchemy import Column, DateTime, String
from sqlalchemy.types import JSON
from app.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    external_id = Column(String, nullable=False)
    source = Column(String, nullable=False)
    type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    state = Column(JSON, nullable=False, default=dict)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True, default=dict)
    capabilities = Column(JSON, nullable=False, default=list)
    room_or_group = Column(String, nullable=True)
