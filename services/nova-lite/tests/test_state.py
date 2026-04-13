import json
from pathlib import Path
import pytest
from app.state import CursorState


def test_load_cursor_returns_utcnow_when_file_absent(tmp_path):
    """First run: no cursor file → use current UTC time as starting point."""
    state = CursorState(cursor_file=str(tmp_path / "cursor.json"))
    cursor = state.load_cursor()
    assert isinstance(cursor, str)
    assert "T" in cursor


def test_save_and_load_cursor_round_trips(tmp_path):
    """Saved cursor is returned on next load."""
    state = CursorState(cursor_file=str(tmp_path / "cursor.json"))
    ts = "2026-04-13T10:00:00Z"
    state.save_cursor(ts)
    assert state.load_cursor() == ts


def test_save_creates_parent_directories(tmp_path):
    """save_cursor creates parent dirs if they don't exist."""
    nested = tmp_path / "deep" / "dir" / "cursor.json"
    state = CursorState(cursor_file=str(nested))
    state.save_cursor("2026-04-13T10:00:00Z")
    assert nested.exists()
    data = json.loads(nested.read_text())
    assert data["last_event_timestamp"] == "2026-04-13T10:00:00Z"
