from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.types import JSON
from app.database import Base


class Tool(Base):
    __tablename__ = "tools"

    name = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    adapter_type = Column(String, nullable=False)
    input_schema = Column(JSON, nullable=False, default=dict)
    output_schema = Column(JSON, nullable=True)
    risk_class = Column(String, nullable=False, default="low")
    requires_approval = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    enabled = Column(Boolean, nullable=False, default=True)
    tags = Column(JSON, nullable=False, default=list)
