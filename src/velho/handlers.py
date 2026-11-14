"""Telegram handlers. Pending input ("waiting for an emoji…") lives in users.state so a
restart loses nothing; every state-consuming action runs synchronously (no awaits between
reading and clearing the state), which makes double button presses harmless."""

from __future__ import annotations

import contextlib
from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from . import views as v
from .db import Database, utcnow
from .staff import (
    CATEGORIES,
    STONE_SIZES,
    fmt_date,
    fmt_height,
    fmt_litres,
    parse_clock,
    parse_height_cm,
    single_emoji,
)
from .stats import compute_stats, leaderboard

router = Router()
PRIVATE = F.chat.type == "private"
GROUP = F.chat.type.in_({"group", "supergroup"})

Event = Message | CallbackQuery


# --- helpers ---------------------------------------------------------------------------


async def show(event: Event, text: str, markup=None) -> None:
    """Edit the button message in place, or answer a plain message."""
    if isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            with contextlib.suppress(TelegramBadRequest):  # "message is not modified"
                await event.message.edit_text(text, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


async def alert(cb: CallbackQuery, text: str) -> None:
    await cb.answer(text, show_alert=True)


def who(db: Database, event: Event) -> int:
    user = event.from_user
    assert user is not None
    db.upsert_user(user.id, user.first_name)
    return user.id


def chat_of(event: Event) -> int:
    msg = event.message if isinstance(event, CallbackQuery) else event
    return msg.chat.id  # type: ignore[union-attr]


def may_see_group(db: Database, event: Event, uid: int, chat_id: int) -> bool:
    """Group data is visible inside that group, or to its opted-in members."""
    return chat_of(event) == chat_id or db.is_member(chat_id, uid)


async def open_in_private(message: Message, text: str) -> None:
    me = await message.bot.me()  # type: ignore[union-attr]
    await message.answer(
        text,
        reply_markup=v.kb([v.Btn(text="Avaa botti", url=f"https://t.me/{me.username}?start=hi")]),
    )


def menu_for(db: Database, uid: int):
    return v.menu_kb(db.active_staff(uid) is not None)


# --- start, help, menu -----------------------------------------------------------------


@router.message(Command("start"), PRIVATE)
@router.callback_query(F.data == "m:menu")
async def start(event: Event, db: Database) -> None:
    uid = who(db, event)
    db.set_state(uid, None)  # the menu is also the universal "cancel"
    name = escape(event.from_user.first_name)  # type: ignore[union-attr]
    text = f"Moi {name}! Tällä botilla rakennat velhon sauvan tölkki kerrallaan."
    await show(event, text, menu_for(db, uid))


@router.message(Command("help"))
@router.callback_query(F.data == "m:help")
async def help_(event: Event, db: Database) -> None:
    who(db, event)
    await show(event, v.HELP, v.kb([v.MENU_BTN]))


@router.message(Command("start", "new", "my"), GROUP)
async def group_redirect(message: Message) -> None:
    await open_in_private(message, "Sauvat rakennetaan yksityisviestissä. Avaa botti napista.")


# --- group opt-in ----------------------------------------------------------------------


@router.message(Command("join"), GROUP)
async def join(message: Message, db: Database) -> None:
    uid = who(db, message)
    db.join(message.chat.id, message.chat.title or "ryhmä", uid)
    await open_in_private(
        message,
        f"{escape(message.from_user.first_name)} on nyt mukana ryhmän tilastoissa ja galleriassa.\n"  # type: ignore[union-attr]
        "Sauva kirjataan yksityisviestissä. Komento /leave poistaa sinut.",
    )


@router.message(Command("leave"), GROUP)
async def leave_here(message: Message, db: Database) -> None:
    uid = who(db, message)
    left = db.leave(message.chat.id, uid)
    await message.answer(
        "Poistuit ryhmän tilastoista ja galleriasta."
        if left
        else "Et ollut mukana. Komento /join liittää sinut."
    )


@router.message(Command("join"), PRIVATE)
async def join_private(message: Message) -> None:
    await message.answer(
        "Komento /join toimii vain ryhmässä. Kirjoita se ryhmässä, jonka tilastoihin haluat mukaan."
    )


@router.message(Command("leave"), PRIVATE)
async def leave_menu(message: Message, db: Database) -> None:
    uid = who(db, message)
    groups = db.user_groups(uid)
    if not groups:
        await message.answer("Et ole mukana missään ryhmässä.")
        return
    rows = [[v.b(f"Poistu: {title}", f"lv:{chat_id}")] for chat_id, title in groups]
    await message.answer("Mistä ryhmästä poistutaan?", reply_markup=v.kb(*rows, [v.MENU_BTN]))


@router.callback_query(F.data.startswith("lv:"))
async def leave_cb(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    db.leave(int((cb.data or "").split(":")[1]), uid)
    await show(cb, "Poistuit ryhmästä. Sauvasi eivät näy siellä enää.", v.kb([v.MENU_BTN]))


# --- builder ---------------------------------------------------------------------------


@router.message(Command("new"), PRIVATE)
@router.callback_query(F.data == "b:view")
async def builder(event: Event, db: Database) -> None:
    """Show the staff in progress (starting one if needed). Also the 'back' target."""
    uid = who(db, event)
    db.set_state(uid, None)
    s = db.start_staff(uid)
    await show(event, v.builder_text(s, utcnow(), db.get_height(uid)), v.builder_kb(s))


async def active_or_alert(cb: CallbackQuery, db: Database):
    uid = who(db, cb)
    s = db.active_staff(uid)
    if s is None:
        await alert(cb, "Sauva ei ole kesken. Aloita uusi valikosta.")
    return s


def owns_can(db: Database, uid: int, can_id: int) -> bool:
    owner = db.can_owner(can_id)
    return owner is not None and owner[0] == uid


@router.callback_query(F.data.startswith("b:add:"))
async def add_prompt(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    size = int((cb.data or "").split(":")[2])
    if size not in (33, 50):
        return await alert(cb, "Tuntematon koko")
    db.set_state(s.user_id, f"can:{size}")
    last = s.cans[-1].emoji if s.cans else None
    await show(cb, v.picker_text(f"can{size}"), v.picker_kb(v.CAN_EMOJIS, last, "b:view"))


@router.callback_query(F.data == "b:finish")
async def finish_prompt(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    if not s.cans:
        return await alert(cb, "Lisää ensin vähintään yksi tölkki.")
    db.set_state(s.user_id, "stone")
    skip = [v.b("🚫 Ilman voimakiveä", "ns")]
    await show(cb, v.picker_text("stone"), v.picker_kb(v.STONE_EMOJIS, None, "b:view", skip))


@router.callback_query(F.data == "ns")
async def no_stone(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    s = db.active_staff(uid)
    if db.get_state(uid) != "stone" or s is None or not s.cans:
        return await alert(cb, "Tämä valinta on jo tehty.")
    db.set_state(uid, None)
    db.finish_staff(s.id, None)
    await show_done(cb, db, s.id)


async def apply_emoji(event: Event, db: Database, uid: int, emoji: str) -> bool:
    """Consume the pending emoji request. False if there was none (e.g. double press)."""
    kind, _, arg = (db.get_state(uid) or "").partition(":")
    s = db.active_staff(uid)
    if kind == "can" and s:
        db.add_can(s.id, int(arg), emoji)
        await builder(event, db)  # clears the state
    elif kind == "emoji" and owns_can(db, uid, int(arg)):
        db.update_can(int(arg), emoji=emoji)
        await builder(event, db)
    elif kind == "stone" and s and s.cans:
        db.set_state(uid, None)
        db.finish_staff(s.id, emoji)
        await show_done(event, db, s.id)
    else:
        return False
    return True


@router.callback_query(F.data.startswith("e:"))
async def emoji_button(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    if not await apply_emoji(cb, db, uid, (cb.data or "")[2:]):
        await alert(cb, "Tämä valinta on jo tehty.")


@router.callback_query(F.data.startswith("c:"))
async def set_category(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    _, can_id, key = (cb.data or "").split(":")
    if key in CATEGORIES and owns_can(db, uid, int(can_id)):
        db.update_can(int(can_id), category=key)
    await builder(cb, db)


@router.callback_query(F.data.startswith("b:undo:"))
async def undo(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    can_id = int((cb.data or "").split(":")[2])
    if owns_can(db, uid, can_id):  # the id makes a double press remove only one can
        db.remove_can(can_id)
    await builder(cb, db)


@router.callback_query(F.data == "b:edit")
async def edit_list(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    if not s.cans:
        return await builder(cb, db)
    db.set_state(s.user_id, None)
    await show(cb, v.edit_text(s), v.edit_kb(s))


@router.callback_query(F.data.startswith("b:can:"))
async def can_menu(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    can_id = int((cb.data or "").split(":")[2])
    can = next((c for c in s.cans if c.id == can_id), None)
    if can is None:
        return await edit_list(cb, db)
    db.set_state(s.user_id, None)
    n = s.cans.index(can) + 1
    await show(
        cb,
        f"Tölkki {n}: {can.emoji}, {fmt_litres(can.size_cl)}",
        v.can_menu_kb(can.id, can.size_cl),
    )


@router.callback_query(F.data.startswith(("b:cemoji:", "b:csize:", "b:cdel:")))
async def can_action(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    _, action, raw = (cb.data or "").split(":")
    can_id = int(raw)
    if not owns_can(db, uid, can_id):
        return await edit_list(cb, db)
    if action == "cemoji":
        db.set_state(uid, f"emoji:{can_id}")
        await show(cb, v.picker_text("edit"), v.picker_kb(v.CAN_EMOJIS, None, f"b:can:{can_id}"))
    elif action == "csize":
        s = db.active_staff(uid)
        can = next(c for c in s.cans if c.id == can_id)  # type: ignore[union-attr]
        db.update_can(can_id, size_cl=50 if can.size_cl == 33 else 33)
        await can_menu(cb, db)
    else:
        db.remove_can(can_id)
        await edit_list(cb, db)


@router.callback_query(F.data == "b:start")
async def start_time_prompt(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    db.set_state(s.user_id, "start")
    await show(
        cb,
        "⏱ Milloin aloitit? Valitse tai kirjoita kellonaika (esim. <code>18.30</code>).",
        v.start_time_kb(),
    )


@router.callback_query(F.data.startswith("t:"))
async def start_time_button(cb: CallbackQuery, db: Database) -> None:
    if (s := await active_or_alert(cb, db)) is None:
        return
    db.set_started(s.id, utcnow() - timedelta(minutes=int((cb.data or "").split(":")[1])))
    await builder(cb, db)


@router.callback_query(F.data == "b:drop")
async def drop_ask(cb: CallbackQuery, db: Database) -> None:
    who(db, cb)
    text = (
        "Mitä yritykselle tehdään?\n\n"
        "Epäonnistunut yritys jää tilastoihin mutta ei näy galleriassa. "
        "Poistettu yritys häviää kokonaan."
    )
    markup = v.kb(
        [v.b("Epäonnistui", "b:drop:f")],
        [v.b("Poista kokonaan", "b:drop:d")],
        [v.b("↩️ Takaisin", "b:view")],
    )
    await show(cb, text, markup)


@router.callback_query(F.data.in_({"b:drop:f", "b:drop:d"}))
async def drop_do(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    s = db.active_staff(uid)
    if s is None:
        return await alert(cb, "Sauva ei ole kesken.")
    if cb.data == "b:drop:f" and db.fail_staff(s.id, uid):
        text = "Yritys kirjattiin epäonnistuneeksi ja se näkyy tilastoissa."
    else:
        db.discard_staff(s.id, uid)
        text = "Yritys poistettiin."
    db.set_state(uid, None)
    await show(cb, text, menu_for(db, uid))


# --- finished staff --------------------------------------------------------------------


async def show_done(event: Event, db: Database, staff_id: int) -> None:
    uid = who(db, event)
    s = db.get_staff(staff_id)
    if s is None or s.user_id != uid or not s.done:
        return
    await show(event, v.done_text(s, db.get_height(uid), bool(db.user_groups(uid))), v.done_kb(s))


@router.callback_query(F.data.startswith("ss:"))
async def stone_size(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    _, raw, key = (cb.data or "").split(":")
    s = db.get_staff(int(raw))
    if s and s.user_id == uid and s.done and key in STONE_SIZES:
        db.set_stone_size(s.id, key)
    await show_done(cb, db, int(raw))


# --- text input (emoji, time, own height) -------------------------------------------------


@router.message(PRIVATE, F.text, ~F.text.startswith("/"))
async def on_text(message: Message, db: Database) -> None:
    uid = who(db, message)
    text = message.text or ""
    kind, _, _ = (db.get_state(uid) or "").partition(":")
    if kind in ("can", "emoji", "stone"):
        if (emoji := single_emoji(text)) is None:
            await message.answer("Lähetä yksi emoji tai käytä nappeja.")
        else:
            await apply_emoji(message, db, uid, emoji)
    elif kind == "start" and (s := db.active_staff(uid)):
        when = parse_clock(text, utcnow())
        if when is None:
            await message.answer("Kirjoita kellonaika muodossa <code>18.30</code>.")
        else:
            db.set_started(s.id, when)
            await builder(message, db)
    elif kind == "myheight":
        if (cm := parse_height_cm(text)) is None:
            await message.answer(
                "En ymmärtänyt pituutta. Kirjoita esimerkiksi <code>180</code> tai <code>1,80 m</code>."
            )
        else:
            db.set_height(uid, cm)
            db.set_state(uid, None)
            await my(message, db)
    else:
        await message.answer("Valitse jatko valikosta.", reply_markup=menu_for(db, uid))


# --- my staffs -------------------------------------------------------------------------


@router.message(Command("my"), PRIVATE)
@router.callback_query(F.data == "m:my")
async def my(event: Event, db: Database) -> None:
    uid = who(db, event)
    db.set_state(uid, None)
    done = db.attempts_for_users([uid])
    height = db.get_height(uid)
    text = (
        v.stats_text(compute_stats(done), "Omat tilastot") + f"\n\nOma pituus: {fmt_height(height)}"
    )
    rows = [
        [
            v.b(
                f"{fmt_date(s.finished_at or s.failed_at)} · {v.cans_text(len(s.cans))} "  # type: ignore[arg-type]
                + ("epäonnistui" if s.failed else s.stone_emoji or ""),
                f"v:0:{s.id}",
            )
        ]
        for s in db.own_staffs(uid, 8)
    ]
    rows.append([v.b("Oma pituus", "my:height"), v.b("Poista tietoni", "my:wipe")])
    rows.append([v.MENU_BTN])
    await show(event, text, v.kb(*rows))


@router.callback_query(F.data == "my:height")
async def my_height_prompt(cb: CallbackQuery, db: Database) -> None:
    db.set_state(who(db, cb), "myheight")
    await show(
        cb,
        "Kirjoita oma pituutesi, esimerkiksi <code>180</code>.",
        v.kb([v.b("↩️ Takaisin", "m:my")]),
    )


@router.callback_query(F.data == "my:wipe")
async def wipe_ask(cb: CallbackQuery, db: Database) -> None:
    who(db, cb)
    await show(
        cb,
        "Poistetaanko kaikki tietosi? Sauvat, tölkit ja ryhmäjäsenyydet poistuvat, eikä niitä voi palauttaa.",
        v.confirm_kb("my:wipe:y", "m:my", "Poista kaikki"),
    )


@router.callback_query(F.data == "my:wipe:y")
async def wipe_do(cb: CallbackQuery, db: Database) -> None:
    db.delete_user(who(db, cb))
    await show(
        cb,
        "Tietosi on poistettu.",
        v.kb([v.MENU_BTN]),
    )


async def own_view(event: Event, db: Database, staff_id: int) -> None:
    uid = who(db, event)
    s = db.get_staff(staff_id)
    if s is None or s.user_id != uid or not (s.done or s.failed):
        return await show(event, "Sauvaa ei löytynyt.", v.kb([v.b("↩️ Omat", "m:my")]))
    kb = v.kb(
        [v.b("🗑 Poista", f"d:{s.id}"), v.b("↩️ Omat sauvat", "m:my")],
    )
    await show(event, v.full_view_text(s, db.get_height(uid)), kb)


@router.callback_query(F.data.startswith("d:"))
async def delete_staff(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    parts = (cb.data or "").split(":")
    if len(parts) == 3:  # confirmed
        db.discard_staff(int(parts[1]), uid)
        return await my(cb, db)
    await show(
        cb,
        "Poistetaanko tämä sauva pysyvästi?",
        v.confirm_kb(f"d:{parts[1]}:y", f"v:0:{parts[1]}", "Poista"),
    )


# --- gallery ---------------------------------------------------------------------------


@router.message(Command("gallery"))
@router.callback_query(F.data == "m:gallery")
async def gallery_entry(event: Event, db: Database) -> None:
    uid = who(db, event)
    if chat_of(event) != uid:  # in a group: that group's gallery
        return await show_gallery(event, db, chat_of(event), 0)
    groups = db.user_groups(uid)
    if len(groups) == 1:
        return await show_gallery(event, db, groups[0][0], 0)
    if not groups:
        text = "Galleria näyttää ryhmän jäsenten sauvat. Kirjoita ensin /join ryhmässä."
        return await show(event, text, v.kb([v.MENU_BTN]))
    rows = [[v.b(f"🖼 {title}", f"g:{chat_id}:0")] for chat_id, title in groups]
    await show(event, "Minkä ryhmän galleria avataan?", v.kb(*rows, [v.MENU_BTN]))


async def show_gallery(event: Event, db: Database, chat_id: int, offset: int) -> None:
    uid = who(db, event)
    if not may_see_group(db, event, uid, chat_id):
        return await show(event, "Liity ensin komennolla /join ryhmässä.", v.kb([v.MENU_BTN]))
    total = db.gallery_count(chat_id)
    staffs = db.gallery(chat_id, v.GALLERY_PAGE, offset)
    if not staffs:
        text = "Galleria on tyhjä. Ensimmäinen valmis sauva ilmestyy tähän. Komento /join lisää sinut mukaan."
        return await show(event, text, v.kb([v.MENU_BTN]) if chat_of(event) == uid else None)
    text = v.gallery_text(staffs, db.group_title(chat_id), total, offset)
    await show(event, text, v.gallery_kb(staffs, chat_id, offset, total))


@router.callback_query(F.data.startswith("g:"))
async def gallery_page(cb: CallbackQuery, db: Database) -> None:
    _, chat_id, offset = (cb.data or "").split(":")
    await show_gallery(cb, db, int(chat_id), int(offset))


@router.callback_query(F.data.startswith("v:"))
async def view_staff(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    _, raw_chat, raw_id = (cb.data or "").split(":")
    chat_id, staff_id = int(raw_chat), int(raw_id)
    if chat_id == 0:
        return await own_view(cb, db, staff_id)
    s = db.group_staff(chat_id, staff_id) if may_see_group(db, cb, uid, chat_id) else None
    if s is None:
        return await alert(cb, "Sauvaa ei löydy tästä galleriasta.")
    rows = []
    if len(db.group_staffs_of(chat_id, s.user_id)) > 1:
        rows.append([v.b("📜 Edelliset yritykset", f"h:{chat_id}:{s.user_id}")])
    rows.append([v.b("◀️ Galleria", f"g:{chat_id}:0")])
    await show(cb, v.full_view_text(s, db.get_height(uid)), v.kb(*rows))


@router.callback_query(F.data.startswith("h:"))
async def history(cb: CallbackQuery, db: Database) -> None:
    uid = who(db, cb)
    _, raw_chat, raw_user = (cb.data or "").split(":")
    chat_id = int(raw_chat)
    if not may_see_group(db, cb, uid, chat_id):
        return await alert(cb, "Ei pääsyä.")
    staffs = db.group_staffs_of(chat_id, int(raw_user))
    if not staffs:
        return await alert(cb, "Ei näytettäviä sauvoja.")
    rows = [
        [
            v.b(
                f"{fmt_date(s.finished_at)} · {len(s.cans)} tölkkiä {s.stone_emoji or ''}",
                f"v:{chat_id}:{s.id}",
            )
        ]  # type: ignore[arg-type]
        for s in staffs[:10]
    ]
    rows.append([v.b("◀️ Galleria", f"g:{chat_id}:0")])
    await show(cb, f"<b>{escape(staffs[0].user_name)}</b>, aiemmat yritykset", v.kb(*rows))


# --- statistics ------------------------------------------------------------------------


@router.message(Command("stats"))
@router.callback_query(F.data == "m:stats")
async def stats_entry(event: Event, db: Database) -> None:
    uid = who(db, event)
    if chat_of(event) != uid:
        return await show_group_stats(event, db, chat_of(event))
    text = v.stats_text(compute_stats(db.attempts_for_users([uid])), "Omat tilastot")
    rows = [[v.b(f"👥 {title}", f"s:g:{chat_id}")] for chat_id, title in db.user_groups(uid)]
    await show(event, text, v.kb(*rows, [v.MENU_BTN]))


async def show_group_stats(event: Event, db: Database, chat_id: int) -> None:
    uid = who(db, event)
    if not may_see_group(db, event, uid, chat_id):
        return await show(event, "Liity ensin komennolla /join ryhmässä.", v.kb([v.MENU_BTN]))
    staffs = db.group_staffs(chat_id)  # attempts of opted-in members only
    text = v.stats_text(
        compute_stats(staffs), f"Tilastot, {db.group_title(chat_id)}", leaderboard(staffs)
    )
    if not db.group_members(chat_id):
        text += "\n\nKukaan ei ole vielä liittynyt. Komento /join lisää sinut."
    await show(event, text, v.kb([v.b("🖼 Galleria", f"g:{chat_id}:0")]))


@router.callback_query(F.data.startswith("s:g:"))
async def group_stats_cb(cb: CallbackQuery, db: Database) -> None:
    await show_group_stats(cb, db, int((cb.data or "").split(":")[2]))
