# These routes remain 501 stubs after Phase 2.
# Routes implemented in Phase 2 (events, /llm/route, tools, runs/{id}, tasks/{id}/runs,
# tasks/{id}/approvals) are removed from this list and tested in their own test files.
# PATCH /board/tasks/{id} is now implemented (Task 3); removed from stubs.
STUB_ROUTES = [
    # Runs — generic list stays 501 (only /runs/{id} and /tasks/{id}/runs are implemented)
    ("GET",   "/runs",                      None),
    # Approvals — respond and get-by-id stay 501 (only POST /tasks/{id}/approvals is implemented)
    ("GET",   "/approvals/some-id",         None),
    ("POST",  "/approvals/some-id/respond", {"decision": "approved", "decided_by": "user"}),
    # Entities
    ("GET",   "/entities",                  None),
    ("GET",   "/entities/some-id",          None),
    ("POST",  "/entities/sync",             {}),
    # LLM providers list — only /llm/route is implemented; provider list/detail stay 501
    ("GET",   "/llm/providers",             None),
    ("GET",   "/llm/providers/some-id",     None),
]


def test_stub_routes_return_501(client):
    for method, path, body in STUB_ROUTES:
        response = client.request(method, path, json=body)
        assert response.status_code == 501, (
            f"{method} {path} returned {response.status_code}, expected 501"
        )
