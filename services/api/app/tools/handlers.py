"""
Tool handler implementations for Phase 2 tools.

Each handler takes (input: dict, *deps) and returns a dict output.
The dispatch() function routes by tool name.
"""
import httpx
from sqlalchemy.orm import Session
from app import llm_client
from app.config import settings as _settings


def handle_debug_echo(input: dict) -> dict:
    """Returns its input unchanged. Used for testing the invocation loop."""
    return {"echo": input}


def handle_ha_light_turn_on(input: dict, cfg=None) -> dict:
    """Calls the Home Assistant light.turn_on service.

    input: {"entity_id": "light.xyz", "brightness": 0-255 (optional)}
    Raises RuntimeError if HA_BASE_URL or HA_TOKEN are not configured.
    """
    cfg = cfg or _settings
    if not cfg.ha_base_url or not cfg.ha_token:
        raise RuntimeError(
            "HA not configured: set HA_BASE_URL and HA_TOKEN environment variables"
        )
    payload: dict = {"entity_id": input["entity_id"]}
    if "brightness" in input:
        payload["brightness"] = input["brightness"]
    resp = httpx.post(
        f"{cfg.ha_base_url}/api/services/light/turn_on",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}


def handle_devops_summarize_ci_failure(input: dict, db: Session) -> dict:
    """Uses the LLM (via route_internal) to summarize a CI failure.

    input: {"url": "https://...", "log_snippet": "..."}
    """
    prompt = (
        f"Summarize this CI failure concisely (2-3 sentences):\n"
        f"URL: {input['url']}\n\n"
        f"Log:\n{input['log_snippet']}"
    )
    summary = llm_client.route_internal(
        db,
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
    return {"summary": summary}


# Registry: tool name → (handler callable, extra_deps: list["db"|"settings"])
_REGISTRY: dict[str, tuple] = {
    "debug.echo": (handle_debug_echo, []),
    "ha.light.turn_on": (handle_ha_light_turn_on, ["settings"]),
    "devops.summarize_ci_failure": (handle_devops_summarize_ci_failure, ["db"]),
}


def dispatch(tool_name: str, input: dict, db: Session, cfg=None) -> dict:
    """Dispatch to the correct handler by tool name.

    Raises KeyError if tool_name is not in the registry.
    """
    handler_fn, deps = _REGISTRY[tool_name]
    args = []
    for dep in deps:
        if dep == "db":
            args.append(db)
        elif dep == "settings":
            args.append(cfg or _settings)
    return handler_fn(input, *args)
