from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone


def test_system_health_all_green(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):  # 50% used
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "ok"
    assert "disk" in result["message"].lower()


def test_system_health_disk_threshold(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 950, 50)):  # 95% used
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "disk" in result["title"].lower()


def test_system_health_memory_threshold(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=95)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "memory" in result["title"].lower()


def test_system_health_stale_tasks(db_session):
    from app.tools.nova_handlers import handle_system_health
    from app.models.task import Task
    stale = Task(
        id="stale-1",
        title="old",
        status="pending",
        priority="normal",
        risk_class="low",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db_session.add(stale)
    db_session.commit()
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "stale" in result["title"].lower()


def test_daily_summary_returns_ok_with_message(db_session):
    from app.tools.nova_handlers import handle_daily_summary
    with patch("app.llm_client.route_internal", return_value="Summary text here."):
        result = handle_daily_summary({"window_hours": 24}, db_session)
    assert result["status"] == "ok"
    assert "Summary text here." in result["message"]
    assert "Daily summary" in result["message"]


def test_describe_tools_groups_by_prefix(db_session):
    from app.tools.nova_handlers import handle_describe_tools
    from app.tools.seed import seed_tools
    seed_tools(db_session)

    result = handle_describe_tools({}, db_session)
    categories = result["categories"]
    assert result["total_count"] >= 11  # at least the currently seeded tools
    # Grouping by first dotted segment
    assert "scheduler" in categories
    assert "nova" in categories
    assert "shell" in categories
    assert "fs" in categories

    # Each entry has the keys the LLM needs
    first_cat = next(iter(categories.values()))
    first_tool = first_cat[0]
    assert "name" in first_tool
    assert "display_name" in first_tool
    assert "description" in first_tool
    assert "risk_class" in first_tool
    assert "input_schema" in first_tool


def test_describe_tools_excludes_disabled(db_session):
    from app.tools.nova_handlers import handle_describe_tools
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)

    # Disable one tool and verify it's absent
    tool = db_session.query(Tool).filter_by(name="debug.echo").first()
    tool.enabled = False
    db_session.commit()

    result = handle_describe_tools({}, db_session)
    all_names = [t["name"] for tools_list in result["categories"].values() for t in tools_list]
    assert "debug.echo" not in all_names
