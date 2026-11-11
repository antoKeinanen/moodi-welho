"""Finnish texts and inline keyboards. No database or Telegram I/O here."""

from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Markup

from .staff import (
    CATEGORIES,
    STONE_SIZES,
    Staff,
    fmt_date,
    fmt_duration,
    fmt_height,
    fmt_litres,
    fmt_time,
    render_stack,
)
from .stats import Stats

CAN_EMOJIS = "🍺🍻🥤🧃🍹🍋🍎🍊🍏🍇🍓🍑🫐🥭🍍🥥🍒🧋🥛🥫"
STONE_EMOJIS = "💎🔮💍🧿⭐🪨🌟💠🔥🍀🧊🐉"
GALLERY_PAGE = 3
PAGE_CHARS = 3400  # text budget for one gallery page; split between its cards

HELP = (
    "<b>Velho Tutkinto</b>\n\n"
    "Rakenna velhon sauva pinoamalla tölkkejä, kunnes sauva yltää omaan pituuteesi. "
    "Jokaisella tölkillä on oma emoji. Ensimmäinen tölkki on alimpana ja voimakivi päällimmäisenä.\n\n"
    "1. Aloita sauva komennolla /new yksityisviestissä.\n"
    "2. Lisää tölkit napeilla. Tölkki 0,33 l on yksi emoji ja 0,5 l kaksi.\n"
    "3. Lopuksi valitse voimakivi tai jätä se pois.\n\n"
    "Ryhmässä komento /join lisää sinut ryhmän tilastoihin ja galleriaan, ja /leave poistaa sinut. "
    "Sauvasi näkyvät ryhmässä vain, jos olet liittynyt.\n\n"
    "Komennot: /new, /my, /gallery, /stats, /help"
)


def kb(*rows: list[Btn]) -> Markup:
    return Markup(inline_keyboard=[r for r in rows if r])


def b(text: str, data: str) -> Btn:
    return Btn(text=text, callback_data=data)


def grid(buttons: list[Btn], cols: int) -> list[list[Btn]]:
    return [buttons[i : i + cols] for i in range(0, len(buttons), cols)]


MENU_BTN = b("🏠 Valikko", "m:menu")


def menu_kb(has_active: bool) -> Markup:
    return kb(
        [b("▶️ Jatka sauvaa" if has_active else "🧙 Uusi sauva", "b:view")],
        [b("🖼 Galleria", "m:gallery"), b("📊 Tilastot", "m:stats")],
        [b("👤 Omat sauvat", "m:my"), b("❓ Ohje", "m:help")],
    )


def confirm_kb(yes: str, no: str, label: str) -> Markup:
    return kb([b(f"✅ {label}", yes), b("↩️ Ei", no)])


# --- builder ---------------------------------------------------------------------------


def counts_line(s: Staff) -> str:
    return f"{len(s.cans)} tölkkiä ({s.count(33)} × 0,33 l, {s.count(50)} × 0,5 l)"


def height_line(s: Staff, goal_cm: int | None = None) -> str:
    line = f"Pituus noin {fmt_height(s.height_cm)}"
    if goal_cm:
        reached = " saavutettu" if s.height_cm >= goal_cm else ""
        line += f" (tavoite {fmt_height(goal_cm)}{reached})"
    return line


def builder_text(s: Staff, now: datetime, goal_cm: int | None = None) -> str:
    head = f"<b>Sauva työn alla</b>\nAloitettu {fmt_time(s.started_at)} "
    head += f"({fmt_duration(now - s.started_at)} sitten)"
    if not s.cans:
        return head + "\n\nSauva on tyhjä. Lisää ensimmäinen tölkki, se tulee sauvan alimmaiseksi."
    stack = render_stack(s.cans, ground=True)
    return f"{head}\n{counts_line(s)}\n{height_line(s, goal_cm)}\n\n{stack}"


def builder_kb(s: Staff) -> Markup:
    rows = [[b("🥫 + 0,33 l", "b:add:33"), b("🍺 + 0,5 l", "b:add:50")]]
    if s.cans:
        last = s.cans[-1]
        if last.category is None:
            tags = [b(f"{e} {n}", f"c:{last.id}:{k}") for k, (e, n) in CATEGORIES.items()]
            rows += grid(tags, 3)  # optional: what was the last can?
        rows.append([b("↩️ Kumoa viimeisin", f"b:undo:{last.id}"), b("✏️ Muokkaa", "b:edit")])
    rows.append([b("⏱ Alkuaika", "b:start")] + ([b("🏁 Valmis", "b:finish")] if s.cans else []))
    rows.append([b("🗑 Hylkää", "b:drop"), MENU_BTN])
    return kb(*rows)


def picker_kb(
    options: str, last_emoji: str | None, back: str, extra: list[Btn] | None = None
) -> Markup:
    rows = []
    if last_emoji:
        rows.append([b(f"🔁 Sama kuin äsken {last_emoji}", f"e:{last_emoji}")])
    rows += grid([b(e, f"e:{e}") for e in options], 6)
    rows.append(extra or [])
    rows.append([b("↩️ Takaisin", back)])
    return kb(*rows)


def picker_text(kind: str) -> str:
    what = {
        "can33": "<b>Tölkki 0,33 l</b> (yksi emoji)",
        "can50": "<b>Tölkki 0,5 l</b> (kaksi emojia)",
        "stone": "<b>Sauvan huippu</b>\nVoimakiveksi kelpaa mikä tahansa emoji.",
        "edit": "<b>Uusi emoji tölkille</b>",
    }[kind]
    return f"{what}\n\nValitse emoji napista tai lähetä oma emoji viestinä."


def start_time_kb() -> Markup:
    opts = [("15 min", 15), ("30 min", 30), ("1 h", 60), ("2 h", 120), ("3 h", 180), ("4 h", 240)]
    return kb(
        *grid([b(f"{t} sitten", f"t:{m}") for t, m in opts], 3),
        [b("↩️ Takaisin", "b:view")],
    )


def edit_kb(s: Staff) -> Markup:
    # Top of the staff first, like the stack. Numbers count from the bottom.
    items = [b(f"{i}. {c.emoji}", f"b:can:{c.id}") for i, c in enumerate(s.cans, 1)]
    return kb(*grid(items[::-1], 4), [b("↩️ Takaisin", "b:view")])


def edit_text(s: Staff) -> str:
    head = "<b>Muokkaa</b>\nValitse tölkki. Numerointi alkaa alimmasta tölkistä.\n\n"
    return head + render_stack(s.cans, ground=True)


def can_menu_kb(can_id: int, size_cl: int) -> Markup:
    other = 50 if size_cl == 33 else 33
    return kb(
        [b("😀 Vaihda emoji", f"b:cemoji:{can_id}")],
        [b(f"📏 Vaihda kooksi {fmt_litres(other)}", f"b:csize:{can_id}")],
        [b("🗑 Poista tölkki", f"b:cdel:{can_id}")],
        [b("↩️ Takaisin", "b:edit")],
    )


# --- finished staff --------------------------------------------------------------------


def staff_details(s: Staff, viewer_height: int | None = None) -> str:
    lines = [f"Kesto {fmt_duration(s.duration)}", counts_line(s)]
    if s.stone_emoji:
        size = STONE_SIZES.get(s.stone_size or "", "koko ei tiedossa")
        lines.append(f"Voimakivi {s.stone_emoji}, {size}")
    height = height_line(s)
    if viewer_height:
        height += f" ({round(s.height_cm - viewer_height):+d} cm omaan pituuteesi verrattuna)"
    lines.append(height)
    return "\n".join(lines)


def done_text(s: Staff, owner_height: int | None, in_group: bool) -> str:
    text = (
        "<b>Velho Tutkinto suoritettu</b>\n\n"
        f"{render_stack(s.cans, s.stone_emoji, ground=True)}\n\n"
        f"{staff_details(s, owner_height)}"
    )
    if not in_group:
        text += "\n\nKomento /join ryhmässä näyttää sauvasi ryhmän galleriassa ja tilastoissa."
    return text


def done_kb(s: Staff) -> Markup:
    rows = []
    if s.stone_emoji and not s.stone_size:
        sizes = [("S", "Kivi pieni"), ("M", "Kivi keski"), ("L", "Kivi iso")]
        rows.append([b(label, f"ss:{s.id}:{k}") for k, label in sizes])
    rows.append([b("🧙 Uusi sauva", "b:view"), b("🖼 Galleria", "m:gallery")])
    rows.append([MENU_BTN])
    return kb(*rows)


# --- gallery ---------------------------------------------------------------------------


def card(s: Staff, max_chars: int) -> str:
    stack = render_stack(s.cans, s.stone_emoji, max_chars=max_chars, ground=True)
    return (
        f"<b>{escape(s.user_name)}</b>, {fmt_date(s.finished_at or s.started_at)}, "
        f"kesto {fmt_duration(s.duration)}\n"
        f"{len(s.cans)} tölkkiä, pituus noin {fmt_height(s.height_cm)}\n{stack}"
    )


def gallery_text(staffs: list[Staff], title: str, total: int, offset: int) -> str:
    head = f"<b>Galleria, {escape(title)}</b>\nSauvat {offset + 1}-{offset + len(staffs)} / {total}"
    budget = PAGE_CHARS // len(staffs) - 150  # every card shows its whole staff if it fits
    return head + "\n\n" + "\n\n".join(card(s, budget) for s in staffs)


def gallery_kb(staffs: list[Staff], chat_id: int, offset: int, total: int) -> Markup:
    open_row = [b(f"🔍 {s.user_name[:12]}", f"v:{chat_id}:{s.id}") for s in staffs]
    nav = []
    if offset > 0:
        nav.append(b("◀️ Uudemmat", f"g:{chat_id}:{max(offset - GALLERY_PAGE, 0)}"))
    if offset + GALLERY_PAGE < total:
        nav.append(b("Vanhemmat ▶️", f"g:{chat_id}:{offset + GALLERY_PAGE}"))
    return kb(open_row, nav, [b("📊 Tilastot", f"s:g:{chat_id}")])


def full_view_text(s: Staff, viewer_height: int | None = None) -> str:
    return (
        f"<b>{escape(s.user_name)}</b>, {fmt_date(s.finished_at or s.started_at)}\n\n"
        f"{render_stack(s.cans, s.stone_emoji, ground=True)}\n\n{staff_details(s, viewer_height)}"
    )


# --- statistics ------------------------------------------------------------------------


def stats_text(st: Stats, title: str, board: list[tuple[str, int]] | None = None) -> str:
    head = f"<b>{escape(title)}</b>\n\n"
    if not st.degrees:
        return head + "Valmiita sauvoja ei ole vielä."
    lines = [
        f"Valmiita tutkintoja: {st.degrees}",
        f"Tölkkejä yhteensä: {st.cans} ({st.cans_33} × 0,33 l, {st.cans_50} × 0,5 l)",
    ]
    if st.share_33 is not None:
        share = round(st.share_33 * 100)
        lines.append(f"Tölkkien osuudet: 0,33 l {share} %, 0,5 l {100 - share} %")
    if st.avg_cans is not None:
        lines.append(f"Tölkkejä per tutkinto: {st.avg_cans:.1f}".replace(".", ","))
    lines.append(f"Keskimääräinen kesto: {fmt_duration(st.avg_duration)}")
    if st.avg_height_cm:
        lines.append(f"Sauvan keskipituus: noin {fmt_height(st.avg_height_cm)}")
    if st.top_category:
        lines.append(f"Suosituin juomalaji: {CATEGORIES[st.top_category][1]}")
    if st.stones:
        sizes = ", ".join(f"{STONE_SIZES[k]} {v}" for k, v in sorted(st.stone_sizes.items()))
        lines.append(f"Voimakiviä: {st.stones}" + (f" ({sizes})" if sizes else ""))
    if board:
        lines += ["", "<b>Tuloslista</b>"]
        lines += [f"{i}. {escape(n)}, {c} tutkintoa" for i, (n, c) in enumerate(board, 1)]
    return head + "\n".join(lines)
