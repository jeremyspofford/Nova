from uuid import uuid4
from sqlalchemy import Boolean, Column, String
from app.database import Base


class LLMProviderProfile(Base):
    __tablename__ = "llm_provider_profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    provider_type = Column(String, nullable=False)
    endpoint_ref = Column(String, nullable=False)
    model_ref = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    supports_tools = Column(Boolean, nullable=False, default=False)
    supports_streaming = Column(Boolean, nullable=False, default=False)
    privacy_class = Column(String, nullable=False, default="local_only")
    cost_class = Column(String, nullable=False, default="low")
    latency_class = Column(String, nullable=False, default="medium")
    notes = Column(String, nullable=True)
