from datetime import timedelta

from velho.stats import compute_stats, leaderboard

from .conftest import T0, make_staff

CHAT_A, CHAT_B = -100, -200


def test_cans_keep_order_and_positions_after_removal(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    ids = [db.add_can(s.id, 33, e).id for e in "🍎🍋🍊🍇"]
    assert [c.emoji for c in db.get_staff(s.id).cans] == list("🍎🍋🍊🍇")
    assert db.remove_can(ids[1]) is True
    assert db.remove_can(ids[1]) is False  # double press is harmless
    assert [c.emoji for c in db.get_staff(s.id).cans] == list("🍎🍊🍇")
    positions = [r[0] for r in db.conn.execute("SELECT position FROM cans ORDER BY position")]
    assert positions == [1, 2, 3]


def test_edit_can_and_resume_unfinished(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    can = db.add_can(s.id, 33, "🍎")
    db.update_can(can.id, emoji="🍐", size_cl=50, category="beer")
    again = db.start_staff(1)  # "restart": returns the staff in progress
    assert again.id == s.id
    assert (again.cans[0].emoji, again.cans[0].size_cl, again.cans[0].category) == (
        "🍐",
        50,
        "beer",
    )


def test_finish_without_stone(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    db.add_can(s.id, 33, "🍎")
    assert db.finish_staff(s.id, None) is True
    done = db.get_staff(s.id)
    assert done.done and done.stone_emoji is None
    assert compute_stats([done]).stones == 0


def test_estimated_height(db):
    s = make_staff(db, 1, [(33, "🍎"), (50, "🍺"), (33, "🍋")])
    assert s.height_cm == 11.5 + 16 + 11.5


def test_migration_from_v1_database(tmp_path):
    import sqlite3

    from velho.db import MIGRATIONS, Database

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(MIGRATIONS[0])
    old.execute("PRAGMA user_version = 1")
    old.execute("INSERT INTO users(id, name) VALUES (1, 'A')")
    old.execute(
        "INSERT INTO staffs(user_id, started_at, height_cm) VALUES (1, '2026-01-01T00:00:00+00:00', 180)"
    )
    old.commit()
    old.close()
    assert Database(path).active_staff(1) is not None


def test_cannot_finish_empty_or_twice(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    assert db.finish_staff(s.id, "💎") is False
    db.add_can(s.id, 33, "🍎")
    assert db.finish_staff(s.id, "💎") is True
    assert db.finish_staff(s.id, "🔮") is False
    assert db.get_staff(s.id).stone_emoji == "💎"


def test_stats_count_physical_cans_not_emoji_rows(db):
    a = make_staff(db, 1, [(50, "🍺"), (50, "🍺"), (33, "🍋")], minutes=60)
    b = make_staff(db, 2, [(33, "🍎")] * 3 + [(50, "🥤")], minutes=120)
    db.update_can(a.cans[0].id, category="beer")
    db.update_can(a.cans[1].id, category="beer")
    db.update_can(b.cans[0].id, category="cider")
    db.set_stone_size(a.id, "L")
    st = compute_stats([db.get_staff(a.id), db.get_staff(b.id)])
    assert (st.degrees, st.cans_33, st.cans_50, st.cans) == (2, 4, 3, 7)
    assert st.avg_cans == 3.5
    assert st.avg_duration.total_seconds() == 90 * 60
    assert st.avg_height_cm == (43.5 + 50.5) / 2  # 11.5 cm / 16 cm per can
    assert st.top_category == "beer"
    assert st.share_33 == 4 / 7
    assert st.stones == 2 and st.stone_sizes == {"L": 1}


def test_unfinished_staffs_are_not_counted(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    db.add_can(s.id, 33, "🍎")
    assert compute_stats([db.get_staff(s.id)]).degrees == 0


def test_leaderboard(db):
    staffs = [make_staff(db, 1, [(33, "🍎")], at=T0.replace(hour=h)) for h in (1, 2, 3)]
    staffs.append(make_staff(db, 2, [(33, "🍎")]))
    assert leaderboard(staffs) == [("user1", 3, 0), ("user2", 1, 0)]


# --- privacy ---


def test_group_stats_and_gallery_only_include_opted_in_members(db):
    make_staff(db, 1, [(33, "🍎")])
    make_staff(db, 2, [(33, "🍋")])
    db.join(CHAT_A, "A-ryhmä", 1)
    assert [s.user_id for s in db.gallery(CHAT_A, 10, 0)] == [1]
    assert db.gallery_count(CHAT_A) == 1
    assert compute_stats(db.group_staffs(CHAT_A)).degrees == 1


def test_groups_do_not_leak_into_each_other(db):
    make_staff(db, 1, [(33, "🍎")])
    make_staff(db, 2, [(33, "🍋")])
    db.join(CHAT_A, "A", 1)
    db.join(CHAT_B, "B", 2)
    s1 = db.gallery(CHAT_A, 10, 0)[0]
    s2 = db.gallery(CHAT_B, 10, 0)[0]
    assert (s1.user_id, s2.user_id) == (1, 2)
    assert db.group_staff(CHAT_A, s2.id) is None  # looking up B's staff through A fails
    assert db.group_staffs_of(CHAT_A, 2) == []


def test_user_in_two_groups_appears_in_both(db):
    make_staff(db, 1, [(33, "🍎")])
    db.join(CHAT_A, "A", 1)
    db.join(CHAT_B, "B", 1)
    assert db.gallery_count(CHAT_A) == db.gallery_count(CHAT_B) == 1


def test_leave_removes_from_that_group_only(db):
    make_staff(db, 1, [(33, "🍎")])
    db.join(CHAT_A, "A", 1)
    db.join(CHAT_B, "B", 1)
    assert db.leave(CHAT_A, 1) is True
    assert db.gallery(CHAT_A, 10, 0) == []
    assert db.gallery_count(CHAT_B) == 1
    assert db.leave(CHAT_A, 1) is False


def test_unfinished_staff_never_in_gallery(db):
    db.upsert_user(1, "A")
    db.join(CHAT_A, "A", 1)
    s = db.start_staff(1, T0)
    db.add_can(s.id, 33, "🍎")
    assert db.gallery(CHAT_A, 10, 0) == []


def test_delete_user_erases_everything(db):
    make_staff(db, 1, [(33, "🍎"), (50, "🍺")])
    db.join(CHAT_A, "A", 1)
    db.delete_user(1)
    for table in ("users", "staffs", "cans", "memberships"):
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_gallery_is_newest_first_and_paged(db):
    for h in range(1, 6):
        make_staff(db, h, [(33, "🍎")], at=T0.replace(hour=h))
        db.join(CHAT_A, "A", h)
    page1 = db.gallery(CHAT_A, 3, 0)
    page2 = db.gallery(CHAT_A, 3, 3)
    assert [s.user_id for s in page1] == [5, 4, 3]
    assert [s.user_id for s in page2] == [2, 1]


# --- failed attempts ---


def fail(db, uid, cans, *, minutes=30, at=T0):
    db.upsert_user(uid, f"user{uid}")
    s = db.start_staff(uid, at)
    for size, emoji in cans:
        db.add_can(s.id, size, emoji)
    assert db.fail_staff(s.id, uid, at + timedelta(minutes=minutes)) is True
    return db.get_staff(s.id)


def test_failed_attempt_is_kept_and_counted_separately(db):
    ok = make_staff(db, 1, [(33, "🍎"), (50, "🍺")])
    bad = fail(db, 1, [(33, "🍋"), (33, "🍋"), (50, "🥤")])
    assert bad.failed and not bad.done and bad.duration == timedelta(minutes=30)
    st = compute_stats(db.attempts_for_users([1]))
    assert (st.degrees, st.failed, st.failed_cans) == (1, 1, 3)
    assert st.success_rate == 0.5
    # degree stats ignore the failed attempt's cans
    assert (st.cans_33, st.cans_50) == (1, 1)
    assert ok.id != bad.id


def test_only_failures_still_produce_stats(db):
    fail(db, 1, [(33, "🍎")])
    st = compute_stats(db.attempts_for_users([1]))
    assert (st.degrees, st.failed, st.success_rate) == (0, 1, 0.0)


def test_failing_frees_the_slot_for_a_new_attempt(db):
    bad = fail(db, 1, [(33, "🍎")])
    assert db.active_staff(1) is None
    fresh = db.start_staff(1, T0)
    assert fresh.id != bad.id and fresh.cans == []
    assert db.finish_staff(bad.id, "💎") is False  # a failed attempt cannot be finished


def test_empty_attempt_can_fail_and_is_kept(db):
    db.upsert_user(1, "A")
    s = db.start_staff(1, T0)
    assert db.fail_staff(s.id, 1) is True
    kept = db.get_staff(s.id)
    assert kept.failed and kept.cans == []
    assert compute_stats(db.attempts_for_users([1])).failed == 1
    assert db.fail_staff(s.id, 1) is False  # already failed, double press changes nothing


def test_failed_attempts_never_in_gallery_and_respect_membership(db):
    fail(db, 1, [(33, "🍎")])
    fail(db, 2, [(33, "🍋")])
    db.join(CHAT_A, "A", 1)
    assert db.gallery(CHAT_A, 10, 0) == [] and db.gallery_count(CHAT_A) == 0
    st = compute_stats(db.group_staffs(CHAT_A))
    assert st.failed == 1  # only the opted-in member's failure
    assert db.fail_staff(db.own_staffs(2)[0].id, 1) is False  # cannot fail someone else's staff


def test_leaderboard_shows_failures_per_person_including_failure_only_members(db):
    staffs = [make_staff(db, 1, [(33, "🍎")]), fail(db, 1, [(33, "🍋")]), fail(db, 2, [(33, "🍋")])]
    assert leaderboard(staffs) == [("user1", 1, 1), ("user2", 0, 1)]


def test_group_stats_text_shows_failures_and_board_without_any_degree(db):
    from velho.views import stats_text

    fail(db, 1, [(33, "🍋")])
    fail(db, 2, [(33, "🍋"), (50, "🍺")])
    db.join(CHAT_A, "A", 1)
    db.join(CHAT_A, "A", 2)
    staffs = db.group_staffs(CHAT_A)
    text = stats_text(compute_stats(staffs), "Tilastot", leaderboard(staffs))
    assert "Epäonnistuneita yrityksiä: 2 (3 tölkkiä)" in text
    assert "Onnistumisprosentti: 0 %" in text
    assert "user1, 0 tutkintoa, 1 epäonnistunut\n" in text + "\n"
