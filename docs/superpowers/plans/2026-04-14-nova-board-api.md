# Nova Board: API Completions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the four stubbed board/approval endpoints and seed the 8 canonical board columns so the Nova Board frontend has a real backend to call.

**Architecture:** All changes are to the existing `services/api` FastAPI service. Four stubs are replaced with real implementations. A new `seed_board_columns()` function is added to `tools/seed.py` and wired into the startup lifespan. The board router gains `GET /board` (columns + grouped tasks) and `PATCH /board/tasks/{id}` (move task). The approvals router gains `GET /approvals/{id}` (fetch) and `POST /approvals/{id}/respond` (decide).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest + TestClient (existing)

**Prerequisite:** Phase 2 complete on `main`. All 57 API tests pass. Run `cd services/api && python3 -m pytest tests/ -v` to verify before starting.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/api/app/tools/seed.py` | Modify | Add `seed_board_columns()` |
| `services/api/app/main.py` | Modify | Call `seed_board_columns()` in lifespan |
| `services/api/app/schemas/board.py` | Modify | Add `BoardColumnResponse`, `BoardResponse` |
| `services/api/app/schemas/approval.py` | Modify | Add `ApprovalRespondRequest` |
| `services/api/app/routers/board.py` | Replace stubs | Implement `GET /board` and `PATCH /board/tasks/{id}` |
| `services/api/app/routers/approvals.py` | Replace stubs | Implement `GET /approvals/{id}` and `POST /approvals/{id}/respond` |
| `services/api/tests/test_board.py` | Create | Tests for board endpoints |
| `services/api/tests/test_approvals_respond.py` | Create | Tests for approval fetch + respond |

---

### Task 1: Board column seeding

**Files:**
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/app/main.py`

- [ ] **Step 1: Write failing test for seeding**

Create `services/api/tests/test_board.py`:

```python
def test_seed_board_columns_creates_8_columns(db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn

    seed_board_columns(db_session)

    columns = db_session.query(BoardColumn).order_by(BoardColumn.order).all()
    assert len(columns) == 8
    names = [c.name for c in columns]
    assert names == [
        "Inbox", "Ready", "Running", "Waiting",
        "Needs Approval", "Done", "Failed", "Cancelled",
    ]


def test_seed_board_columns_is_idempotent(db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn

    seed_board_columns(db_session)
    seed_board_columns(db_session)  # second call must not error or duplicate

    count = db_session.query(BoardColumn).count()
    assert count == 8
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/api
python3 -m pytest tests/test_board.py -v
```

Expected: ImportError or AttributeError — `seed_board_columns` does not exist yet.

- [ ] **Step 3: Add `seed_board_columns` to `tools/seed.py`**

Open `services/api/app/tools/seed.py`. Add this function after `seed_llm_providers`:

```python
def seed_board_columns(db: Session) -> None:
    """Upsert the 8 canonical board columns. Safe to re-run on every startup."""
    from app.models.board_column import BoardColumn

    columns = [
        dict(id="col-inbox",     name="Inbox",          order=1, description="New tasks not yet triaged"),
        dict(id="col-ready",     name="Ready",          order=2, description="Approved and ready to execute"),
        dict(id="col-running",   name="Running",        order=3, description="Currently executing"),
        dict(id="col-waiting",   name="Waiting",        order=4, description="Paused, waiting on external signal"),
        dict(id="col-approval",  name="Needs Approval", order=5, description="Requires human decision before proceeding"),
        dict(id="col-done",      name="Done",           order=6, description="Completed successfully"),
        dict(id="col-failed",    name="Failed",         order=7, description="Terminated with error"),
        dict(id="col-cancelled", name="Cancelled",      order=8, description="Denied or explicitly cancelled"),
    ]

    for defn in columns:
        col = db.query(BoardColumn).filter(BoardColumn.id == defn["id"]).first()
        if col:
            for k, v in defn.items():
                setattr(col, k, v)
        else:
            db.add(BoardColumn(**defn))

    db.commit()
```

- [ ] **Step 4: Wire into main.py lifespan**

Open `services/api/app/main.py`. Add `seed_board_columns` to the import line and the lifespan:

```python
from app.tools.seed import seed_tools, seed_llm_providers, seed_board_columns
```

Inside the `lifespan` function, add the call after the existing seeds:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = _db.SessionLocal()
    try:
        seed_tools(db)
        seed_llm_providers(db, settings)
        seed_board_columns(db)
    finally:
        db.close()
    yield
```

- [ ] **Step 5: Run seeding tests**

```bash
python3 -m pytest tests/test_board.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
python3 -m pytest tests/ -v
```

Expected: all 57 existing tests + 2 new = 59 passed.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/tools/seed.py services/api/app/main.py services/api/tests/test_board.py
git commit -m "feat: seed 8 canonical board columns on API startup"
```

---

### Task 2: Board schemas + GET /board

**Files:**
- Modify: `services/api/app/schemas/board.py`
- Modify: `services/api/app/routers/board.py`

- [ ] **Step 1: Write failing tests for GET /board**

Add to `services/api/tests/test_board.py`:

```python
def test_get_board_returns_columns_and_empty_groups(client):
    response = client.get("/board")
    assert response.status_code == 200
    data = response.json()
    assert "columns" in data
    assert "tasks_by_column" in data
    columns = data["columns"]
    assert len(columns) == 8
    assert columns[0]["name"] == "Inbox"
    assert columns[0]["order"] == 1
    assert "work_in_progress_limit" in columns[0]
    assert "status_filter" in columns[0]


def test_get_board_tasks_without_column_land_in_inbox(client):
    # Create a task with no board_column_id
    client.post("/tasks", json={"title": "orphan task"})
    response = client.get("/board")
    data = response.json()
    inbox_id = next(c["id"] for c in data["columns"] if c["name"] == "Inbox")
    assert len(data["tasks_by_column"][inbox_id]) == 1
    assert data["tasks_by_column"][inbox_id][0]["title"] == "orphan task"


def test_get_board_tasks_with_column_appear_in_correct_column(client, db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn
    seed_board_columns(db_session)
    done_col = db_session.query(BoardColumn).filter(BoardColumn.name == "Done").first()
    client.post("/tasks", json={"title": "done task", "board_column_id": done_col.id})
    response = client.get("/board")
    data = response.json()
    assert any(
        t["title"] == "done task"
        for t in data["tasks_by_column"].get(done_col.id, [])
    )


def test_get_board_status_filter(client):
    client.post("/tasks", json={"title": "inbox task"})
    client.post("/tasks", json={"title": "done task"})
    # Patch one task to done status
    tasks = client.get("/tasks").json()["tasks"]
    done_id = tasks[1]["id"]
    client.patch(f"/tasks/{done_id}", json={"status": "done"})

    response = client.get("/board?status=done")
    data = response.json()
    total_tasks = sum(len(v) for v in data["tasks_by_column"].values())
    assert total_tasks == 1
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_board.py -v
```

Expected: FAIL — GET /board returns 501.

- [ ] **Step 3: Add board schemas**

Replace `services/api/app/schemas/board.py` entirely:

```python
from typing import Any
from pydantic import BaseModel, ConfigDict
from app.schemas.task import TaskResponse


class BoardColumnMove(BaseModel):
    board_column_id: str


class BoardColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    order: int
    work_in_progress_limit: int | None
    status_filter: dict[str, Any] | None
    description: str | None


class BoardResponse(BaseModel):
    columns: list[BoardColumnResponse]
    tasks_by_column: dict[str, list[TaskResponse]]
```

- [ ] **Step 4: Implement GET /board**

Replace `services/api/app/routers/board.py` entirely:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.board_column import BoardColumn
from app.models.task import Task
from app.schemas.board import BoardColumnMove, BoardColumnResponse, BoardResponse
from app.schemas.task import TaskResponse

router = APIRouter(prefix="/board", tags=["board"])


@router.get("", response_model=BoardResponse)
def get_board(
    status: str | None = Query(None),
    risk_class: str | None = Query(None),
    priority: str | None = Query(None),
    labels: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    columns = db.query(BoardColumn).order_by(BoardColumn.order).all()

    # Inbox is the fallback column for tasks with no board_column_id
    inbox = next((c for c in columns if c.order == 1), None)

    # Fetch and optionally filter tasks
    task_query = db.query(Task)
    if status:
        task_query = task_query.filter(Task.status == status)
    if risk_class:
        task_query = task_query.filter(Task.risk_class == risk_class)
    if priority:
        task_query = task_query.filter(Task.priority == priority)
    tasks = task_query.all()

    # Python-side label filter (JSON column, SQLite-safe)
    if labels:
        tasks = [t for t in tasks if all(lbl in (t.labels or []) for lbl in labels)]

    # Build grouped response
    tasks_by_column: dict[str, list[TaskResponse]] = {c.id: [] for c in columns}
    for task in tasks:
        col_id = task.board_column_id
        if col_id not in tasks_by_column:
            col_id = inbox.id if inbox else None
        if col_id:
            tasks_by_column[col_id].append(TaskResponse.model_validate(task))

    return BoardResponse(
        columns=[BoardColumnResponse.model_validate(c) for c in columns],
        tasks_by_column=tasks_by_column,
    )


@router.patch("/tasks/{task_id}")
def move_task(task_id: str, body: BoardColumnMove):
    raise HTTPException(status_code=501, detail="Not implemented")
```

- [ ] **Step 5: Run board tests**

```bash
python3 -m pytest tests/test_board.py -v
```

Expected: seeding tests + GET /board tests pass. PATCH tests still 501 (not yet implemented).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/schemas/board.py services/api/app/routers/board.py
git commit -m "feat: implement GET /board with column grouping and task filters"
```

---

### Task 3: PATCH /board/tasks/{id}

**Files:**
- Modify: `services/api/app/routers/board.py`

- [ ] **Step 1: Write failing tests**

Add to `services/api/tests/test_board.py`:

```python
def test_patch_board_task_moves_to_column(client, db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn
    seed_board_columns(db_session)
    done_col = db_session.query(BoardColumn).filter(BoardColumn.name == "Done").first()

    task = client.post("/tasks", json={"title": "movable"}).json()
    response = client.patch(f"/board/tasks/{task['id']}", json={"board_column_id": done_col.id})
    assert response.status_code == 200
    assert response.json()["board_column_id"] == done_col.id


def test_patch_board_task_404_unknown_task(client, db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn
    seed_board_columns(db_session)
    col = db_session.query(BoardColumn).first()
    response = client.patch("/board/tasks/nonexistent", json={"board_column_id": col.id})
    assert response.status_code == 404


def test_patch_board_task_404_unknown_column(client):
    task = client.post("/tasks", json={"title": "task"}).json()
    response = client.patch(f"/board/tasks/{task['id']}", json={"board_column_id": "nonexistent-col"})
    assert response.status_code == 404


def test_patch_board_task_reflects_in_get_board(client, db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn
    seed_board_columns(db_session)
    ready_col = db_session.query(BoardColumn).filter(BoardColumn.name == "Ready").first()

    task = client.post("/tasks", json={"title": "to move"}).json()
    client.patch(f"/board/tasks/{task['id']}", json={"board_column_id": ready_col.id})

    board = client.get("/board").json()
    ready_tasks = board["tasks_by_column"].get(ready_col.id, [])
    assert any(t["id"] == task["id"] for t in ready_tasks)
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_board.py::test_patch_board_task_moves_to_column -v
```

Expected: FAIL — returns 501.

- [ ] **Step 3: Implement PATCH /board/tasks/{task_id}**

In `services/api/app/routers/board.py`, replace the stub `move_task` function:

```python
@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def move_task(task_id: str, body: BoardColumnMove, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    column = db.query(BoardColumn).filter(BoardColumn.id == body.board_column_id).first()
    if not column:
        raise HTTPException(404, "Column not found")

    task.board_column_id = body.board_column_id
    db.commit()
    db.refresh(task)
    return TaskResponse.model_validate(task)
```

- [ ] **Step 4: Run board tests**

```bash
python3 -m pytest tests/test_board.py -v
```

Expected: all board tests pass.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routers/board.py services/api/tests/test_board.py
git commit -m "feat: implement PATCH /board/tasks/{id} to move task between columns"
```

---

### Task 4: GET /approvals/{id} + POST /approvals/{id}/respond

**Files:**
- Modify: `services/api/app/schemas/approval.py`
- Modify: `services/api/app/routers/approvals.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_approvals_respond.py`:

```python
def _create_task_with_approval(client):
    """Helper: create a task, request approval, return (task, approval)."""
    task = client.post("/tasks", json={"title": "risky"}).json()
    approval = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "confirm action",
        "consequence": "something will happen",
    }).json()
    return task, approval


def test_get_approval_returns_record(client):
    _, approval = _create_task_with_approval(client)
    response = client.get(f"/approvals/{approval['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == approval["id"]
    assert data["status"] == "pending"
    assert data["summary"] == "confirm action"


def test_get_approval_404(client):
    response = client.get("/approvals/nonexistent")
    assert response.status_code == 404


def test_respond_approve_sets_status_and_updates_task(client):
    task, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve",
        "decided_by": "user",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["decision"] == "approve"
    assert data["decided_by"] == "user"
    assert data["decided_at"] is not None

    updated_task = client.get(f"/tasks/{task['id']}").json()
    assert updated_task["status"] == "ready"


def test_respond_deny_sets_status_and_updates_task(client):
    task, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "deny",
        "decided_by": "user",
        "reason": "too risky",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "denied"
    assert data["reason"] == "too risky"

    updated_task = client.get(f"/tasks/{task['id']}").json()
    assert updated_task["status"] == "cancelled"


def test_respond_409_on_non_pending_approval(client):
    _, approval = _create_task_with_approval(client)
    # First response succeeds
    client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve", "decided_by": "user"
    })
    # Second response must 409
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "deny", "decided_by": "user"
    })
    assert response.status_code == 409


def test_respond_404_on_unknown_approval(client):
    response = client.post("/approvals/nonexistent/respond", json={
        "decision": "approve", "decided_by": "user"
    })
    assert response.status_code == 404


def test_respond_with_reason(client):
    _, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve",
        "decided_by": "user",
        "reason": "looks safe",
    })
    assert response.status_code == 200
    assert response.json()["reason"] == "looks safe"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_approvals_respond.py -v
```

Expected: FAIL — both endpoints return 501.

- [ ] **Step 3: Add `ApprovalRespondRequest` to schemas**

Open `services/api/app/schemas/approval.py`. Add this class at the end:

```python
class ApprovalRespondRequest(BaseModel):
    decision: str
    decided_by: str
    reason: str | None = None
```

- [ ] **Step 4: Implement both approval endpoints**

Replace `services/api/app/routers/approvals.py` entirely:

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.approval import Approval
from app.models.task import Task
from app.schemas.approval import ApprovalCreate, ApprovalRead, ApprovalRespondRequest

router = APIRouter(tags=["approvals"])


@router.post("/tasks/{task_id}/approvals", response_model=ApprovalRead, status_code=201)
def request_approval(task_id: str, body: ApprovalCreate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    existing = db.query(Approval).filter(
        Approval.task_id == task_id,
        Approval.status == "pending"
    ).first()
    if existing:
        raise HTTPException(409, "A pending approval already exists for this task")

    approval = Approval(
        task_id=task_id,
        requested_by="nova-lite",
        summary=body.summary,
        consequence=body.consequence,
        options=body.options,
        status="pending",
    )
    db.add(approval)
    task.status = "needs_approval"
    db.commit()
    db.refresh(approval)
    return ApprovalRead.model_validate(approval)


@router.get("/approvals/{approval_id}", response_model=ApprovalRead)
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    return ApprovalRead.model_validate(approval)


@router.post("/approvals/{approval_id}/respond", response_model=ApprovalRead)
def respond_to_approval(
    approval_id: str,
    body: ApprovalRespondRequest,
    db: Session = Depends(get_db),
):
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    if approval.status != "pending":
        raise HTTPException(
            409,
            f"Approval is not pending (current status: {approval.status})"
        )

    # "approve" is the only value that maps to approved; all others are denied
    outcome = "approved" if body.decision == "approve" else "denied"

    approval.status = outcome
    approval.decided_by = body.decided_by
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision = body.decision
    approval.reason = body.reason

    task = db.query(Task).filter(Task.id == approval.task_id).first()
    if task:
        task.status = "ready" if outcome == "approved" else "cancelled"

    db.commit()
    db.refresh(approval)
    return ApprovalRead.model_validate(approval)
```

- [ ] **Step 5: Run approval tests**

```bash
python3 -m pytest tests/test_approvals_respond.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass. Check that `test_stubs.py` no longer includes `GET /approvals/some-id` and `POST /approvals/some-id/respond` — those were removed in Phase 2 cleanup. If they are still present, remove them from STUB_ROUTES.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/schemas/approval.py services/api/app/routers/approvals.py \
        services/api/tests/test_approvals_respond.py
git commit -m "feat: implement GET /approvals/{id} and POST /approvals/{id}/respond"
```
