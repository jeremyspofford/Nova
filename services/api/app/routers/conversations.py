import json
import re
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
from app.models.run import Run
from app.models.task import Task
from app.models.tool import Tool
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationRead,
    MessageCreate,
    MessageListResponse,
    MessageRead,
)
from app.tools import handlers as tool_handlers


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
        "Help the user understand their system, answer questions, and take actions.\n\n"
        f"Current pending tasks:\n{task_lines}\n\n"
        f"Available tools:\n{tool_lines}\n\n"
        "Respond conversationally. Be concise and helpful."
    )


def _parse_json_safe(text: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on any failure."""
    try:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        cleaned = match.group(1).strip() if match else text.strip()
        return json.loads(cleaned)
    except Exception:
        return None


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
    if conv.title == "New Chat":
        conv.title = _make_title(body.content)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Build message history
    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )

    # --- Phase 1: Intent classification (MUST run before generator is defined) ---
    tools = db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712
    tool_list = "\n".join(f"  - {t.name}: {t.description}" for t in tools)
    classify_messages = [
        {
            "role": "system",
            "content": (
                "You are an intent classifier for Nova.\n"
                f"Classify the user message. Available tools:\n{tool_list}\n\n"
                'Respond ONLY with JSON:\n'
                '{"intent": "action" | "conversation", '
                '"tool_name": string | null, '
                '"tool_input": object | null, '
                '"confidence": number}\n\n'
                'If unsure, return intent="conversation".'
            ),
        },
        {"role": "user", "content": body.content},
    ]

    tool_name = None    # captured by generator closure
    tool_context = None  # captured by generator closure

    try:
        classify_result = llm_client.route_internal(db, "classify", classify_messages)
        c = _parse_json_safe(classify_result) or {}
    except Exception:
        c = {}

    if (
        c.get("intent") == "action"
        and c.get("confidence", 0) >= 0.7
        and c.get("tool_name") in tool_handlers._REGISTRY
    ):
        tool_name = c["tool_name"]
        tool_input = c.get("tool_input") or {}

        run = Run(
            id=str(uuid4()),
            tool_name=tool_name,
            task_id=None,
            executor_type="chat",
            trigger_type="chat",
            input=tool_input,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()

        try:
            output = tool_handlers.dispatch(tool_name, tool_input, db)
            run.status = "succeeded"
            run.output = output
            run.summary = f"{tool_name} \u2192 succeeded"
            tool_context = (
                f"You just ran `{tool_name}`. "
                f"Result: {json.dumps(output)}. Status: succeeded."
            )
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.summary = f"{tool_name} \u2192 failed"
            tool_context = f"You tried to run `{tool_name}` but it failed: {exc}."
        finally:
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

    # --- Phase 2: Build messages for response LLM call ---
    base_prompt = _build_system_prompt(db)
    system_prompt = (tool_context + "\n\n" + base_prompt) if tool_context else base_prompt
    messages = [{"role": "system", "content": system_prompt}] + [
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

    # Streaming path — generator reads tool_name + tool_context from closure
    def generate():
        if tool_name:
            yield f"data: {json.dumps({'delta': f'[Running {tool_name}...]\n'})}\n\n"

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
