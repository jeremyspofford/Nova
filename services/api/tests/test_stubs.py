STUB_ROUTES = [
    ("GET",  "/events",       None),
    ("POST", "/events",       {"type": "test", "source": "test", "subject": "test"}),
    ("GET",  "/board",        None),
    ("GET",  "/tools",        None),
    ("GET",  "/runs",         None),
    ("GET",  "/llm/providers", None),
]


def test_stub_routes_return_501(client):
    for method, path, body in STUB_ROUTES:
        response = client.request(method, path, json=body)
        assert response.status_code == 501, f"{method} {path} returned {response.status_code}, expected 501"
