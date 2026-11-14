"""Drive the real handlers with fake Telegram events: build → finish → gallery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from velho import handlers as h
from velho.db import Database


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple[str, object]] = []

    async def fake_show(event, text, markup=None):
        out.append((text, markup))

    monkeypatch.setattr(h, "show", fake_show)
    return out


def cb(data: str, user_id=1, chat_id=1):
    c = MagicMock(spec=CallbackQuery)
    c.data = data
    c.from_user = SimpleNamespace(id=user_id, first_name=f"U{user_id}")
    c.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))
    c.answer = AsyncMock()
    return c


def msg(text: str, user_id=1, chat_id=None):
    m = MagicMock(spec=Message)
    m.text = text
    m.from_user = SimpleNamespace(id=user_id, first_name=f"U{user_id}")
    m.chat = SimpleNamespace(id=chat_id or user_id, title="Ryhmä")
    m.answer = AsyncMock()
    return m


async def add_can(db, size: int, emoji: str, uid=1):
    await h.add_prompt(cb(f"b:add:{size}", uid), db)
    await h.emoji_button(cb(f"e:{emoji}", uid), db)


async def test_full_flow_and_double_press(db: Database, sent):
    await h.builder(cb("b:view"), db)
    await add_can(db, 33, "🍎")
    await add_can(db, 50, "🥤")
    await add_can(db, 33, "🍋")

    # pressing the same emoji button twice adds only one can
    await h.add_prompt(cb("b:add:50"), db)
    await h.emoji_button(cb("e:🍺"), db)
    dup = cb("e:🍺")
    await h.emoji_button(dup, db)
    dup.answer.assert_awaited_with("Tämä valinta on jo tehty.", show_alert=True)
    staff = db.active_staff(1)
    assert [(c.size_cl, c.emoji) for c in staff.cans] == [
        (33, "🍎"),
        (50, "🥤"),
        (33, "🍋"),
        (50, "🍺"),
    ]

    # typed emoji works too, undo removes exactly one can even when pressed twice
    await h.add_prompt(cb("b:add:33"), db)
    await h.on_text(msg("🍑"), db)
    last = db.active_staff(1).cans[-1]
    assert last.emoji == "🍑"
    await h.undo(cb(f"b:undo:{last.id}"), db)
    await h.undo(cb(f"b:undo:{last.id}"), db)
    assert len(db.active_staff(1).cans) == 4

    # finish: stone on top, completion time recorded
    await h.finish_prompt(cb("b:finish"), db)
    await h.emoji_button(cb("e:💎"), db)
    assert db.active_staff(1) is None
    done = db.own_staffs(1)[0]
    assert done.stone_emoji == "💎" and done.finished_at
    assert sent[-1][0].splitlines()[2:10] == ["💎", "🍺", "🍺", "🍋", "🥤", "🥤", "🍎", "🟫"]

    # optional extras: stone size; height is estimated from the cans
    await h.stone_size(cb(f"ss:{done.id}:L"), db)
    done = db.get_staff(done.id)
    assert done.stone_size == "L"
    assert done.height_cm == 11.5 * 2 + 16 * 2


async def test_finish_without_stone_and_any_emoji_as_extra(db: Database, sent):
    await h.builder(cb("b:view"), db)
    await add_can(db, 33, "🍎")
    await h.finish_prompt(cb("b:finish"), db)
    await h.on_text(msg("🦄"), db)  # any emoji works as the top extra
    assert db.own_staffs(1)[0].stone_emoji == "🦄"

    await h.builder(cb("b:view"), db)
    await add_can(db, 33, "🍋")
    await h.finish_prompt(cb("b:finish"), db)
    await h.no_stone(cb("ns"), db)
    latest = db.own_staffs(1)[0]
    assert latest.done and latest.stone_emoji is None
    dup = cb("ns")
    await h.no_stone(dup, db)  # double press
    dup.answer.assert_awaited_with("Tämä valinta on jo tehty.", show_alert=True)
    assert "Voimakivi" not in sent[-1][0]


async def test_restart_keeps_pending_state(db: Database, sent):
    await h.builder(cb("b:view"), db)
    await h.add_prompt(cb("b:add:50"), db)
    # "restart": new Database object on the same data would read the same state column
    assert db.get_state(1) == "can:50"
    await h.on_text(msg("not an emoji"), db)  # invalid input keeps waiting
    assert db.get_state(1) == "can:50"


async def test_gallery_permissions(db: Database, sent, monkeypatch):
    monkeypatch.setattr(h, "open_in_private", AsyncMock())  # skip bot.me() lookup
    for uid in (1, 2):
        await h.builder(cb("b:view", uid), db)
        await add_can(db, 33, "🍎", uid)
        await h.finish_prompt(cb("b:finish", uid), db)
        await h.emoji_button(cb("e:💎", uid), db)
    await h.join(msg("/join", 1, chat_id=-100), db)

    # member of the group sees only opted-in staffs
    await h.show_gallery(cb("g:-100:0", 1), db, -100, 0)
    text = sent[-1][0]
    assert "U1" in text and "U2" not in text
    assert text.count("🍎") == 1 and "💎" in text  # the whole staff is shown on the card

    # user 2 never joined and is chatting privately → no access
    await h.show_gallery(cb("g:-100:0", 2), db, -100, 0)
    assert "Liity ensin" in sent[-1][0]
    other = cb("v:-100:1", 2)
    await h.view_staff(other, db)
    other.answer.assert_awaited_with("Sauvaa ei löydy tästä galleriasta.", show_alert=True)


async def test_wipe_deletes_everything(db: Database, sent):
    await h.builder(cb("b:view"), db)
    await add_can(db, 33, "🍎")
    await h.wipe_do(cb("my:wipe:y"), db)
    assert db.conn.execute("SELECT COUNT(*) FROM cans").fetchone()[0] == 0


async def test_failed_attempt_flow(db: Database, sent):
    await h.builder(cb("b:view"), db)
    await add_can(db, 33, "🍎")
    await add_can(db, 50, "🍺")
    await h.drop_do(cb("b:drop:f"), db)
    assert db.active_staff(1) is None
    attempt = db.own_staffs(1)[0]
    assert attempt.failed and len(attempt.cans) == 2

    await h.my(cb("m:my"), db)
    assert "Epäonnistuneita yrityksiä: 1 (2 tölkkiä)" in sent[-1][0]
    assert "Onnistumisprosentti: 0 %" in sent[-1][0]

    # failing right after /new keeps the attempt too
    await h.builder(cb("b:view"), db)
    await h.drop_do(cb("b:drop:f"), db)
    assert [a.failed for a in db.own_staffs(1)] == [True, True]

    # only "Poista kokonaan" deletes, and it leaves the statistics untouched
    await h.builder(cb("b:view"), db)
    await h.drop_do(cb("b:drop:d"), db)
    assert len(db.own_staffs(1)) == 2 and db.active_staff(1) is None
