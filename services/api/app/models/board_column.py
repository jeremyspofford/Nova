from uuid import uuid4
from sqlalchemy import Column, Integer, String
from sqlalchemy.types import JSON
from app.database import Base


class BoardColumn(Base):
    __tablename__ = "board_columns"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False)
    order = Column(Integer, nullable=False)
    status_filter = Column(JSON, nullable=True)
    work_in_progress_limit = Column(Integer, nullable=True)
    description = Column(String, nullable=True)
