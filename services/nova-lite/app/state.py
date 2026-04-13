import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class CursorState:
    def __init__(self, cursor_file: str):
        self._path = Path(cursor_file)

    def load_cursor(self) -> str:
        """Return the last event timestamp, or UTC now if no cursor file exists."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return data["last_event_timestamp"]
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Corrupted cursor file, resetting: %s", e)
        # First run: only process events that arrive after now
        return datetime.now(tz=timezone.utc).isoformat()

    def save_cursor(self, timestamp: str) -> None:
        """Persist the cursor to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"last_event_timestamp": timestamp}))
