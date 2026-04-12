from pydantic import BaseModel

class BoardColumnMove(BaseModel):
    board_column_id: str
