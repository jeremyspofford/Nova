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
    # board_column_id is not in TaskCreate; create then move via PATCH
    r = client.post("/tasks", json={"title": "done task"})
    task_id = r.json()["id"]
    client.patch(f"/tasks/{task_id}", json={"board_column_id": done_col.id})
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


def test_seed_board_columns_is_idempotent(db_session):
    from app.tools.seed import seed_board_columns
    from app.models.board_column import BoardColumn

    seed_board_columns(db_session)
    seed_board_columns(db_session)  # second call must not error or duplicate

    count = db_session.query(BoardColumn).count()
    assert count == 8
