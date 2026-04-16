from uuid import uuid4
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    title = Column(String, nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    pending_tool_call = Column(JSON, nullable=True)
    pending_tool_call_at = Column(DateTime(timezone=True), nullable=True)
    messages = relationship("Message", order_by="Message.created_at", back_populates="conversation")
