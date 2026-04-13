import logging

import httpx

log = logging.getLogger(__name__)


class NovaClientError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class NovaClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        kwargs = {"base_url": base_url.rstrip("/"), "timeout": 30.0}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(**kwargs)

    def close(self) -> None:
        self._http.close()

    def _check(self, resp: httpx.Response) -> dict:
        if not resp.is_success:
            raise NovaClientError(resp.status_code, resp.text)
        return resp.json()

    def get_events(self, since: str, limit: int = 10) -> list[dict]:
        resp = self._http.get("/events", params={"since": since, "limit": limit})
        return self._check(resp)["events"]

    def get_tasks(
        self,
        status: str | None = None,
        limit: int = 5,
        origin_event_id: str | None = None,
    ) -> list[dict]:
        params: dict = {"limit": limit}
        if status is not None:
            params["status"] = status
        if origin_event_id is not None:
            params["origin_event_id"] = origin_event_id
        resp = self._http.get("/tasks", params=params)
        return self._check(resp)["tasks"]

    def post_task(self, payload: dict) -> dict:
        resp = self._http.post("/tasks", json=payload)
        return self._check(resp)

    def patch_task(self, task_id: str, updates: dict) -> dict:
        resp = self._http.patch(f"/tasks/{task_id}", json=updates)
        return self._check(resp)

    def get_tools(self) -> list[dict]:
        resp = self._http.get("/tools")
        return self._check(resp)["tools"]

    def invoke_tool(
        self, tool_name: str, input: dict, task_id: str | None = None
    ) -> dict:
        body: dict = {"input": input}
        if task_id is not None:
            body["task_id"] = task_id
        resp = self._http.post(f"/tools/{tool_name}/invoke", json=body)
        return self._check(resp)

    def post_approval(self, task_id: str, payload: dict) -> dict:
        resp = self._http.post(f"/tasks/{task_id}/approvals", json=payload)
        return self._check(resp)

    def llm_route(
        self,
        purpose: str,
        messages: list[dict],
        privacy_preference: str = "local_preferred",
    ) -> str:
        body = {
            "purpose": purpose,
            "input": {"messages": messages},
            "privacy_preference": privacy_preference,
        }
        resp = self._http.post("/llm/route", json=body)
        return self._check(resp)["output"]
