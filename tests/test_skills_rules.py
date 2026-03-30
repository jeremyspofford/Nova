"""Tests for Skills & Rules system."""
import os
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {}


@pytest.fixture(autouse=True)
def admin_headers():
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


@pytest.fixture
def skill_id():
    resp = httpx.post(
        f"{BASE}/skills",
        json={
            "name": "nova-test-skill",
            "description": "Test skill",
            "content": "You are an expert code reviewer.",
            "category": "review",
            "priority": 10,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create skill: {resp.text}"
    sid = resp.json()["id"]
    yield sid
    try:
        httpx.delete(f"{BASE}/skills/{sid}", headers=HEADERS)
    except Exception:
        pass


def test_skills_endpoint_exists():
    resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_rules_endpoint_exists():
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_seed_rules_exist():
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    rules = resp.json()
    names = {r["name"] for r in rules}
    assert "no-rm-rf" in names
    assert "workspace-boundary" in names
    assert "no-secret-in-output" in names
    for r in rules:
        if r["name"] in ("no-rm-rf", "workspace-boundary", "no-secret-in-output"):
            assert r["is_system"] is True


def test_create_skill():
    resp = httpx.post(
        f"{BASE}/skills",
        json={"name": "nova-test-create-skill", "content": "Test content"},
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["name"] == "nova-test-create-skill"
    assert data["scope"] == "global"
    assert data["enabled"] is True
    httpx.delete(f"{BASE}/skills/{data['id']}", headers=HEADERS)


def test_list_skills(skill_id):
    resp = httpx.get(f"{BASE}/skills", headers=HEADERS)
    found = [s for s in resp.json() if s["id"] == skill_id]
    assert len(found) == 1
    assert found[0]["name"] == "nova-test-skill"


def test_update_skill(skill_id):
    resp = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"content": "Updated content", "priority": 20},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Updated content"
    assert resp.json()["priority"] == 20


def test_delete_skill():
    resp = httpx.post(
        f"{BASE}/skills",
        json={"name": "nova-test-delete-skill", "content": "Temp"},
        headers=HEADERS,
    )
    sid = resp.json()["id"]
    del_resp = httpx.delete(f"{BASE}/skills/{sid}", headers=HEADERS)
    assert del_resp.status_code == 204


def test_toggle_skill(skill_id):
    resp = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"enabled": False},
        headers=HEADERS,
    )
    assert resp.json()["enabled"] is False
    resp2 = httpx.patch(
        f"{BASE}/skills/{skill_id}",
        json={"enabled": True},
        headers=HEADERS,
    )
    assert resp2.json()["enabled"] is True


# ── Rules Tests ──────────────────────────────────────────────────────────────


@pytest.fixture
def rule_id():
    resp = httpx.post(
        f"{BASE}/rules",
        json={
            "name": "nova-test-rule",
            "description": "Test rule",
            "rule_text": "Block test patterns",
            "enforcement": "hard",
            "pattern": "DANGEROUS_PATTERN",
            "target_tools": ["run_shell"],
            "action": "block",
            "severity": "high",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create rule: {resp.text}"
    rid = resp.json()["id"]
    yield rid
    try:
        httpx.delete(f"{BASE}/rules/{rid}", headers=HEADERS)
    except Exception:
        pass


def test_create_rule():
    resp = httpx.post(
        f"{BASE}/rules",
        json={
            "name": "nova-test-create-rule",
            "rule_text": "Block test",
            "enforcement": "hard",
            "pattern": "test_blocked",
            "action": "block",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["name"] == "nova-test-create-rule"
    assert data["enforcement"] == "hard"
    assert data["enabled"] is True
    httpx.delete(f"{BASE}/rules/{data['id']}", headers=HEADERS)


def test_list_rules_includes_seed(rule_id):
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    names = {r["name"] for r in resp.json()}
    assert "no-rm-rf" in names
    assert "nova-test-rule" in names


def test_update_rule(rule_id):
    resp = httpx.patch(
        f"{BASE}/rules/{rule_id}",
        json={"severity": "critical", "pattern": "NEW_PATTERN"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["severity"] == "critical"
    assert resp.json()["pattern"] == "NEW_PATTERN"


def test_cannot_delete_system_rule():
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    system_rule = next((r for r in resp.json() if r["is_system"]), None)
    assert system_rule is not None, "No system rules found"
    del_resp = httpx.delete(f"{BASE}/rules/{system_rule['id']}", headers=HEADERS)
    assert del_resp.status_code == 400


def test_hard_rule_enforcement_present():
    """Verify seed rules are active and configured for enforcement."""
    resp = httpx.get(f"{BASE}/rules", headers=HEADERS)
    rm_rule = next((r for r in resp.json() if r["name"] == "no-rm-rf"), None)
    assert rm_rule is not None
    assert rm_rule["enabled"] is True
    assert rm_rule["enforcement"] in ("hard", "both")
    assert rm_rule["pattern"] is not None
    assert rm_rule["action"] == "block"
