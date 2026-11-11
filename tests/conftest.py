from datetime import UTC, datetime, timedelta

import pytest

from velho.db import Database

T0 = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


def make_staff(
    db: Database, uid: int, cans: list[tuple[int, str]], *, minutes=60, stone="💎", at=T0
):
    """Finished staff for a user (creates the user). cans = [(size_cl, emoji), ...] bottom first."""
    db.upsert_user(uid, f"user{uid}")
    s = db.start_staff(uid, at)
    for size, emoji in cans:
        db.add_can(s.id, size, emoji)
    db.finish_staff(s.id, stone, at + timedelta(minutes=minutes))
    return db.get_staff(s.id)
