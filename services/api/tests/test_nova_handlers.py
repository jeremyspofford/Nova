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
