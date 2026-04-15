import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import llm_client
from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.task import Task
from app.models.tool import Tool
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationRead,
    MessageCreate,
    MessageListResponse,
    MessageRead,
)


def _make_title(content: str) -> str:
    """First 50 chars of content, truncated to nearest word boundary."""
    if len(content) <= 50:
        return content
    truncated = content[:50]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


def _build_system_prompt(db: Session) -> str:
    tasks = (
        db.query(Task)
        .filter(Task.status == "pending")
        .limit(5)
        .all()
    )
    task_lines = "\n".join(
        f"- [{t.id[:8]}] {t.title} ({t.priority})" for t in tasks
    ) or "None"

    tools = db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712
    tool_lines = "\n".join(
        f"- {t.name}: {t.description}" for t in tools
    ) or "None"

    return (
        "You are Nova, an intelligent agent assistant. "
        "Help the user understand their system, answer questions, and plan actions. "
        "You cannot execute tools directly from chat — suggest the user post an event or create a task for actions that need execution.\n\n"
        f"Current pending tasks:\n{task_lines}\n\n"
        f"Available tools (reference only):\n{tool_lines}\n\n"
        "Respond conversationally. Be concise and helpful."
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


@router.post("/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist user message
    user_msg = Message(
        id=str(uuid4()),
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)

    # Set title from first message
    if conv.title == "New Chat":
        conv.title = _make_title(body.content)

    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Build message history for LLM
    history = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).all()

    messages = [{"role": "system", "content": _build_system_prompt(db)}] + [
        {"role": m.role, "content": m.content} for m in history
    ]

    if not body.stream:
        try:
            result = llm_client.route(db, "chat", messages)
            output = result.output
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=output,
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(assistant_msg)
        return MessageRead.model_validate(assistant_msg)

    # Streaming path
    def generate():
        full_content: list[str] = []
        try:
            for chunk in llm_client.route_streaming(db, "chat", messages):
                full_content.append(chunk)
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            conv.updated_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Persist complete assistant message
        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content="".join(full_content),
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()

        yield f"data: {json.dumps({'complete': True})}\n\n"

    return StreamingResponse(
        generate(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
