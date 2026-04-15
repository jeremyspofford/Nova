import os
import pytest

# Must set before any app import that references settings
os.environ.setdefault("NOVA_API_URL", "http://test:8000")


class FakeClient:
    """In-memory fake of NovaClient. Tests mutate these attributes to control responses."""

    def __init__(self):
        self.events: list[dict] = []
        self.tasks: dict[str, dict] = {}
        self.tools: list[dict] = []
        self.approvals: dict[str, dict] = {}
        self._llm_response: str = ""
        self._invoke_result: dict = {"run_id": "run-1", "status": "succeeded"}
        self._next_task_id: int = 1

    def get_events(self, since: str, limit: int = 10) -> list[dict]:
        return self.events[:limit]

    def get_tasks(
        self,
        status: str | None = None,
        limit: int = 5,
        origin_event_id: str | None = None,
    ) -> list[dict]:
        result = list(self.tasks.values())
        if status is not None:
            result = [t for t in result if t.get("status") == status]
        if origin_event_id is not None:
            result = [t for t in result if t.get("origin_event_id") == origin_event_id]
        return result[:limit]

    def get_tools(self) -> list[dict]:
        return self.tools

    def post_task(self, payload: dict) -> dict:
        task_id = f"task-{self._next_task_id}"
        self._next_task_id += 1
        task = {"id": task_id, "status": "pending", **payload}
        self.tasks[task_id] = task
        return task

    def patch_task(self, task_id: str, updates: dict) -> dict:
        self.tasks[task_id].update(updates)
        return self.tasks[task_id]

    def post_approval(self, task_id: str, payload: dict) -> dict:
        approval = {"id": "approval-1", "task_id": task_id, "status": "pending", **payload}
        self.approvals[task_id] = approval
        return approval

    def llm_route(
        self,
        purpose: str,
        messages: list[dict],
        privacy_preference: str = "local_preferred",
    ) -> str:
        return self._llm_response

    def invoke_tool(
        self, tool_name: str, input: dict, task_id: str | None = None
    ) -> dict:
        return self._invoke_result


@pytest.fixture
def fake_client():
    return FakeClient()
