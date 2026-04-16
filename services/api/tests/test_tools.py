import pytest


def test_get_tools_returns_seeded_tools(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.get("/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    names = {t["name"] for t in tools}
    assert {"debug.echo", "ha.light.turn_on", "devops.summarize_ci_failure", "ha.light.turn_off",
            "http.request", "shell.run", "fs.list", "fs.read", "nova.query_activity",
            "nova.system_health", "nova.daily_summary"} == names


def test_get_tools_default_only_enabled(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    # Disable one tool
    tool = db_session.query(Tool).filter(Tool.name == "ha.light.turn_on").first()
    tool.enabled = False
    db_session.commit()
    response = client.get("/tools")
    names = {t["name"] for t in response.json()["tools"]}
    assert "ha.light.turn_on" not in names
    assert "debug.echo" in names


def test_get_tools_enabled_false_shows_only_disabled(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    tool = db_session.query(Tool).filter(Tool.name == "ha.light.turn_on").first()
    tool.enabled = False
    db_session.commit()
    response = client.get("/tools?enabled=false")
    names = {t["name"] for t in response.json()["tools"]}
    assert "ha.light.turn_on" in names
    assert "debug.echo" not in names


def test_get_tool_by_name(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.get("/tools/debug.echo")
    assert response.status_code == 200
    assert response.json()["name"] == "debug.echo"


def test_get_tool_not_found(client):
    response = client.get("/tools/nonexistent.tool")
    assert response.status_code == 404


def test_invoke_debug_echo(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.post("/tools/debug.echo/invoke", json={"input": {"hello": "world"}})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert "run_id" in data


def test_invoke_creates_run_with_correct_output(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    r = client.post("/tools/debug.echo/invoke", json={"input": {"key": "value"}})
    run_id = r.json()["run_id"]
    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "succeeded"
    assert run["output"] == {"echo": {"key": "value"}}
    assert run["tool_name"] == "debug.echo"


def test_invoke_run_linked_to_task(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    task = client.post("/tasks", json={"title": "test"}).json()
    r = client.post("/tools/debug.echo/invoke", json={
        "input": {"x": 1},
        "task_id": task["id"],
    })
    run_id = r.json()["run_id"]
    runs = client.get(f"/tasks/{task['id']}/runs").json()["runs"]
    assert any(run["id"] == run_id for run in runs)


def test_invoke_unknown_tool_404(client):
    response = client.post("/tools/unknown.tool/invoke", json={"input": {}})
    assert response.status_code == 404


def test_invoke_tool_failure_returns_failed_status(client, db_session):
    from app.tools.seed import seed_tools
    from unittest.mock import patch
    seed_tools(db_session)
    with patch("app.tools.handlers.dispatch", side_effect=RuntimeError("handler crashed")):
        response = client.post("/tools/debug.echo/invoke", json={"input": {}})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] is not None


def test_invoke_disabled_tool_400(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    tool = db_session.query(Tool).filter(Tool.name == "debug.echo").first()
    tool.enabled = False
    db_session.commit()
    response = client.post("/tools/debug.echo/invoke", json={"input": {}})
    assert response.status_code == 400
