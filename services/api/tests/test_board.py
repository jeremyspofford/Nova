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
