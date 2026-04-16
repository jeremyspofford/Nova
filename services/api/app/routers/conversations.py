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
from app.config import settings as _settings
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


CONFIRM_RE = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|do it|go ahead|proceed)\b", re.I)
DENY_RE = re.compile(r"\b(no|nope|cancel|stop|abort|nvm|never ?mind)\b", re.I)

SENSITIVE_TOOLS = {
    "scheduler.create_trigger",
    "scheduler.update_trigger",
    "scheduler.delete_trigger",
}
MAX_TOOL_TURNS = 3
PENDING_TIMEOUT_MINUTES = 30


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

    from app.models.llm_provider import LLMProviderProfile
    provider = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.provider_type == "local",
        LLMProviderProfile.enabled == True,  # noqa: E712
    ).first()
    model_line = f"{provider.model_ref} via Ollama" if provider else "unknown"

    return (
        "You are Nova, an intelligent agent assistant running on a real host machine. "
        f"You are powered by {model_line}. "
        "You can run shell commands, read files, manage scheduled triggers, and query your own activity history using your tools.\n\n"
        f"Current pending tasks:\n{task_lines}\n\n"
        "When the user asks about your configuration, capabilities, scheduled "
        "triggers, or what you can do, call the appropriate introspection tool "
        "rather than speculating: `nova.describe_config` for your setup, "
        "`nova.describe_tools` for your tool catalog, or `scheduler.list_triggers` "
        "for what each trigger does. Never invent what a trigger or tool does — "
        "read it from the DB.\n\n"
        "Respond conversationally. Be concise and helpful. "
        "When a user asks you to do something that maps to a tool, call the tool directly rather than describing what you would do."
    )


def _tool_catalog(db: Session) -> list[dict]:
    """Build OpenAI-format tool list from enabled tools."""
    tools_list = db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema or {"type": "object"},
            },
        }
        for t in tools_list
    ]


def _check_pending_confirmation(
    conv: Conversation, user_msg: str
) -> tuple[str, dict | None]:
    """Returns ('confirm'|'deny'|'none', pending_call_or_None)."""
    if not conv.pending_tool_call:
        return "none", None
    anchor = conv.pending_tool_call_at or datetime.now(timezone.utc)
    # Normalize for SQLite which strips tzinfo
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - anchor
    if age.total_seconds() > PENDING_TIMEOUT_MINUTES * 60:
        return "none", None
    confirm_hit = CONFIRM_RE.search(user_msg) is not None
    deny_hit = DENY_RE.search(user_msg) is not None
    # Ambiguous input ("yes, cancel" / "no, proceed") routes to deny — safer default
    # for sensitive ops. Only an unambiguous confirm counts as confirm.
    if confirm_hit and not deny_hit:
        return "confirm", conv.pending_tool_call
    if deny_hit:
        return "deny", conv.pending_tool_call
    return "none", None


def _render_confirmation(tool_name: str, args: dict) -> str:
    """Render a short markdown confirmation prompt for a sensitive tool call."""
    parts = tool_name.split(".", 1)
    action = parts[1] if len(parts) > 1 else tool_name
    verb = {
        "create": "create",
        "update": "update",
        "delete": "delete",
    }.get(action.split("_", 1)[0], "run")
    lines = [f"I'll {verb} this trigger:"]
    if "name" in args:
        lines.append(f"- **Name:** {args['name']}")
    if "id" in args:
        lines.append(f"- **ID:** {args['id']}")
    if "cron_expression" in args:
        lines.append(f"- **Schedule:** `{args['cron_expression']}`")
    if "payload_template" in args:
        p = args["payload_template"]
        if isinstance(p, dict):
            if "goal" in p:
                lines.append(f"- **Goal:** {p['goal']}")
            elif "tool" in p:
                lines.append(f"- **Tool:** {p['tool']}")
    lines.append("")
    lines.append("Confirm?")
    return "\n".join(lines)


def _record_run(
    db: Session,
    tool_name: str,
    tool_input: dict,
    output: dict | None,
    error: str | None = None,
) -> None:
    """Persist a Run row for tool-call audit."""
    run = Run(
        id=str(uuid4()),
        tool_name=tool_name,
        task_id=None,
        executor_type="chat",
        trigger_type="chat",
        input=tool_input,
        status="failed" if error else "succeeded",
        output=output,
        error=error,
        summary=f"{tool_name} \u2192 {'failed' if error else 'succeeded'}",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()


def _dispatch_tool_call(db: Session, tc: dict) -> dict:
    """Run a non-sensitive tool synchronously; record Run; return output.

    On exception: the full error is persisted to the Run's `error` column for
    audit, but only a sanitized payload is returned to the LLM context — raw
    Python exception strings can leak file paths, credentials, or DB constraint
    details that the model would then echo to the user.
    """
    name = tc["name"]
    args = tc.get("arguments") or {}
    try:
        output = tool_handlers.dispatch(name, args, db, _settings)
        _record_run(db, name, args, output, error=None)
        return output
    except Exception as exc:
        _record_run(db, name, args, output=None, error=str(exc))
        return {"error": "tool invocation failed", "tool_name": name}


def _synth_stream(text: str):
    """Yield a string as a single chunk; mirrors route_streaming's generator shape."""
    yield text


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

    # These are resolved below; captured by generate() closure.
    final_stream = None  # iterable of text chunks for user-visible reply
    final_text_override: str | None = None  # non-None ⇒ use this verbatim for persistence
    final_messages: list[dict] | None = None  # set when Phase 2 will be used

    # ----- Step A: pending confirmation, if any -----
    verdict, pending = _check_pending_confirmation(conv, body.content)
    if verdict == "confirm":
        tool_output = _dispatch_tool_call(db, pending)
        conv.pending_tool_call = None
        conv.pending_tool_call_at = None
        db.commit()
        reply_text = tool_output.get("summary") if isinstance(tool_output, dict) else None
        if not reply_text:
            reply_text = f"Done. {json.dumps(tool_output)}"
        final_stream = _synth_stream(reply_text)
        final_text_override = reply_text

    elif verdict == "deny":
        conv.pending_tool_call = None
        conv.pending_tool_call_at = None
        db.commit()
        final_stream = _synth_stream("Cancelled.")
        final_text_override = "Cancelled."

    else:
        # ----- Step B: Phase 1 — synchronous tool-calling loop -----
        system_content = _build_system_prompt(db)
        messages: list[dict] = [{"role": "system", "content": system_content}]
        for m in history:
            messages.append({"role": m.role, "content": m.content})

        tools = _tool_catalog(db)
        intercepted_confirmation: str | None = None

        for _turn in range(MAX_TOOL_TURNS):
            try:
                result = llm_client.route_with_tools(
                    db, purpose="chat", messages=messages, tools=tools
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                # LLM emitted text — drop to Phase 2 streaming.
                break

            sensitive = next(
                (tc for tc in tool_calls if tc["name"] in SENSITIVE_TOOLS), None
            )
            if sensitive:
                conv.pending_tool_call = sensitive
                conv.pending_tool_call_at = datetime.now(timezone.utc)
                db.commit()
                intercepted_confirmation = _render_confirmation(
                    sensitive["name"], sensitive.get("arguments") or {}
                )
                break

            # Assign a call_id to each tool_call and emit ONE assistant message
            # containing all of them — OpenAI protocol requires paired
            # tool_call_id values on the tool-result messages that follow.
            assistant_tool_calls = []
            outputs: list[tuple[str, dict]] = []
            for tc in tool_calls:
                call_id = f"call_{uuid4().hex[:12]}"
                tc["_call_id"] = call_id  # keep in-memory only; not sent to API
                output = _dispatch_tool_call(db, tc)
                outputs.append((call_id, tc["name"], output))
                assistant_tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("arguments") or {}),
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_tool_calls,
                }
            )
            for call_id, tool_name, output in outputs:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": json.dumps(output),
                    }
                )

        if intercepted_confirmation is not None:
            final_stream = _synth_stream(intercepted_confirmation)
            final_text_override = intercepted_confirmation
        else:
            # Phase 2: stream the final reply using existing streaming machinery.
            final_messages = messages

    # ----- Non-streaming fast path -----
    if not body.stream:
        if final_text_override is not None:
            reply = final_text_override
        else:
            try:
                result = llm_client.route(db, "chat", final_messages or [])
                reply = result.output
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=reply,
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(assistant_msg)
        return MessageRead.model_validate(assistant_msg)

    # ----- Streaming (SSE) path -----
    def generate():
        full_content: list[str] = []
        try:
            if final_stream is not None:
                stream_iter = final_stream
            else:
                stream_iter = llm_client.route_streaming(
                    db, "chat", final_messages or []
                )
            for chunk in stream_iter:
                full_content.append(chunk)
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            conv.updated_at = datetime.now(timezone.utc)
            db.commit()
            return

        persist_text = (
            final_text_override if final_text_override is not None else "".join(full_content)
        )
        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=persist_text,
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
