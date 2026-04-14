"""
Startup seeding for tools, LLM providers, and board columns.
Called from main.py lifespan on every startup (upsert — safe to re-run).
"""
from sqlalchemy.orm import Session
from app.models.llm_provider import LLMProviderProfile


def seed_llm_providers(db: Session, settings) -> None:
    """Upsert the Ollama local provider if OLLAMA_BASE_URL is set."""
    if not settings.ollama_base_url:
        return

    provider = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.id == "ollama-local"
    ).first()

    if provider:
        provider.endpoint_ref = settings.ollama_base_url + "/v1"
        provider.model_ref = settings.ollama_model
        provider.enabled = True
    else:
        provider = LLMProviderProfile(
            id="ollama-local",
            name="Ollama Local",
            provider_type="local",
            endpoint_ref=settings.ollama_base_url + "/v1",
            model_ref=settings.ollama_model,
            enabled=True,
            supports_tools=False,
            supports_streaming=False,
            privacy_class="local_only",
            cost_class="low",
            latency_class="medium",
        )
        db.add(provider)

    db.commit()


def seed_board_columns(db: Session) -> None:
    """Upsert the 8 canonical board columns. Safe to re-run on every startup."""
    from app.models.board_column import BoardColumn

    columns = [
        dict(id="col-inbox",     name="Inbox",          order=1, description="New tasks not yet triaged"),
        dict(id="col-ready",     name="Ready",          order=2, description="Approved and ready to execute"),
        dict(id="col-running",   name="Running",        order=3, description="Currently executing"),
        dict(id="col-waiting",   name="Waiting",        order=4, description="Paused, waiting on external signal"),
        dict(id="col-approval",  name="Needs Approval", order=5, description="Requires human decision before proceeding"),
        dict(id="col-done",      name="Done",           order=6, description="Completed successfully"),
        dict(id="col-failed",    name="Failed",         order=7, description="Terminated with error"),
        dict(id="col-cancelled", name="Cancelled",      order=8, description="Denied or explicitly cancelled"),
    ]

    for defn in columns:
        col = db.query(BoardColumn).filter(BoardColumn.id == defn["id"]).first()
        if col:
            for k, v in defn.items():
                setattr(col, k, v)
        else:
            db.add(BoardColumn(**defn))

    db.commit()


def seed_tools(db: Session) -> None:
    """Upsert the Phase 2 tool definitions. Safe to re-run on every startup."""
    from app.models.tool import Tool

    tool_definitions = [
        dict(
            name="debug.echo",
            display_name="Debug Echo",
            description="Returns its input unchanged. Used for testing the tool invocation loop.",
            adapter_type="internal",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=5,
            enabled=True,
            tags=["debug"],
        ),
        dict(
            name="ha.light.turn_on",
            display_name="HA: Turn On Light",
            description=(
                "Turns on a Home Assistant light entity. "
                "Requires HA_BASE_URL and HA_TOKEN environment variables."
            ),
            adapter_type="home_assistant",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 255},
                },
                "required": ["entity_id"],
            },
            output_schema={"type": "object"},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=10,
            enabled=True,
            tags=["home_assistant", "light"],
        ),
        dict(
            name="devops.summarize_ci_failure",
            display_name="DevOps: Summarize CI Failure",
            description="Uses the LLM to summarize a CI failure from a URL and log snippet.",
            adapter_type="internal",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "log_snippet": {"type": "string"},
                },
                "required": ["url", "log_snippet"],
            },
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=30,
            enabled=True,
            tags=["devops", "ci"],
        ),
    ]

    for defn in tool_definitions:
        tool = db.query(Tool).filter(Tool.name == defn["name"]).first()
        if tool:
            for k, v in defn.items():
                setattr(tool, k, v)
        else:
            db.add(Tool(**defn))

    db.commit()
