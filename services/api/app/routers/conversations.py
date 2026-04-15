from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationRead,
    MessageCreate,
    MessageListResponse,
    MessageRead,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_read(conv: Conversation, db: Session) -> ConversationRead:
    count = (
        db.query(func.count(Message.id))
        .filter(Message.conversation_id == conv.id)
        .scalar()
    ) or 0
    return ConversationRead(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=count,
    )


@router.post("", response_model=ConversationRead, status_code=201)
def create_conversation(db: Session = Depends(get_db)):
    conv = Conversation(id=str(uuid4()))
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conversation_read(conv, db)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return ConversationListResponse(
        conversations=[_conversation_read(c, db) for c in convs]
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    return MessageListResponse(messages=[MessageRead.model_validate(m) for m in msgs])
