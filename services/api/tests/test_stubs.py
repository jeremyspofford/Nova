STUB_ROUTES = [
    # Events
    ("GET",   "/events",                    None),
    ("POST",  "/events",                    {"type": "test", "source": "test", "subject": "test"}),
    # Board
    ("GET",   "/board",                     None),
    ("PATCH", "/board/tasks/some-id",       {"board_column_id": "col-1"}),
    # Tools
    ("GET",   "/tools",                     None),
    ("GET",   "/tools/some-tool",           None),
    ("POST",  "/tools/some-tool/invoke",    {"input": {}}),
    # Runs
    ("GET",   "/runs",                      None),
    ("GET",   "/runs/some-id",              None),
    ("GET",   "/tasks/some-id/runs",        None),
    # Approvals
    ("POST",  "/tasks/some-id/approvals",   {"summary": "test"}),
    ("GET",   "/approvals/some-id",         None),
    ("POST",  "/approvals/some-id/respond", {"decision": "approved", "decided_by": "user"}),
    # Entities
    ("GET",   "/entities",                  None),
    ("GET",   "/entities/some-id",          None),
    ("POST",  "/entities/sync",             {}),
    # LLM providers
    ("GET",   "/llm/providers",             None),
    ("GET",   "/llm/providers/some-id",     None),
    ("POST",  "/llm/route",                 {"purpose": "test", "input": {}, "privacy_preference": "local_preferred"}),
]


def test_stub_routes_return_501(client):
    for method, path, body in STUB_ROUTES:
        response = client.request(method, path, json=body)
        assert response.status_code == 501, f"{method} {path} returned {response.status_code}, expected 501"
