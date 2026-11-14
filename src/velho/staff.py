"""Domain model and pure helpers: staffs, emoji-stack rendering, input parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import emoji as emoji_lib

TZ = ZoneInfo("Europe/Helsinki")
SIZES = (33, 50)  # centilitres
TELEGRAM_LIMIT = 4096
MAX_STACK_CHARS = 3000  # leaves room for the header text around a stack

CATEGORIES: dict[str, tuple[str, str]] = {
    "beer": ("🍺", "Olut"),
    "lonkero": ("🍹", "Lonkero"),
    "seltzer": ("🫧", "Seltzer"),
    "cider": ("🍏", "Siideri"),
    "nonalc": ("🧃", "Alkoholiton"),
    "other": ("🥫", "Muu"),
}
# Rough physical can heights (cm), used to estimate how tall a staff is.
CAN_HEIGHT_CM = {33: 11.5, 50: 16.0}
STONE_SIZES = {"S": "pieni", "M": "keskikokoinen", "L": "iso"}


@dataclass(frozen=True)
class Can:
    """One physical can. A 0.5 L can is *one* can but takes two rows in the stack."""

    id: int
    size_cl: int
    emoji: str
    category: str | None = None

    @property
    def rows(self) -> int:
        return 2 if self.size_cl == 50 else 1


@dataclass
class Staff:
    id: int
    user_id: int
    user_name: str
    started_at: datetime
    finished_at: datetime | None = None
    failed_at: datetime | None = None  # attempt given up; kept for statistics
    stone_emoji: str | None = None
    stone_size: str | None = None
    cans: list[Can] = field(default_factory=list)  # bottom → top, in the order added

    @property
    def done(self) -> bool:
        return self.finished_at is not None

    @property
    def failed(self) -> bool:
        return self.failed_at is not None

    @property
    def duration(self) -> timedelta | None:
        end = self.finished_at or self.failed_at
        return end - self.started_at if end else None

    @property
    def height_cm(self) -> float:
        """Estimated staff height: 0.33 L ≈ 11.5 cm, 0.5 L ≈ 16 cm per can (stone not counted)."""
        return sum(CAN_HEIGHT_CM[c.size_cl] for c in self.cans)

    def count(self, size_cl: int) -> int:
        return sum(1 for c in self.cans if c.size_cl == size_cl)


# --- rendering -------------------------------------------------------------------------


def utf16_len(text: str) -> int:
    """Telegram measures message length in UTF-16 units."""
    return len(text.encode("utf-16-le")) // 2


def stack_rows(cans: list[Can], stone: str | None = None) -> list[str]:
    """Emoji rows from the TOP down: stone first, last can next, first can last."""
    rows = [stone] if stone else []
    for can in reversed(cans):
        rows.extend([can.emoji] * can.rows)
    return rows


def render_stack(
    cans: list[Can],
    stone: str | None = None,
    *,
    max_rows: int | None = None,
    max_chars: int = MAX_STACK_CHARS,
    ground: bool = False,
) -> str:
    """Vertical emoji stack, one emoji per line, first can at the bottom, stone on top.

    Too long stacks are cut from the *bottom*, so the top (and the stone) always stays visible.
    """
    rows = stack_rows(cans, stone)
    shown: list[str] = []
    used = 0
    for row in rows[: max_rows or len(rows)]:
        cost = utf16_len(row) + 1
        if used + cost > max_chars:
            break
        shown.append(row)
        used += cost
    hidden = len(rows) - len(shown)
    if hidden:
        shown.append(f"⋮ (+{hidden} alempaa)")
    elif ground and rows:
        shown.append("🟫")
    return "\n".join(shown)


# --- input parsing ---------------------------------------------------------------------


def single_emoji(text: str | None) -> str | None:
    """Return the text if it is exactly one emoji, else None."""
    text = (text or "").strip()
    if text and emoji_lib.purely_emoji(text) and emoji_lib.emoji_count(text) == 1:
        return text
    return None


def parse_height_cm(text: str) -> int | None:
    """'182', '182 cm', '1,82' and '1.82 m' all mean 182 cm."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(cm|m)?\s*", text.lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    cm = round(value * 100) if m.group(2) == "m" or value < 3 else round(value)
    return cm if 10 <= cm <= 300 else None


def parse_clock(text: str, now: datetime) -> datetime | None:
    """'18:30' or '18.30' → the most recent such local time that is not in the future."""
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    local_now = now.astimezone(TZ)
    t = local_now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if t > local_now:
        t -= timedelta(days=1)
    return t.astimezone(now.tzinfo)


# --- Finnish formatting ----------------------------------------------------------------


def fmt_litres(size_cl: int) -> str:
    return "0,33 l" if size_cl == 33 else "0,5 l"


def fmt_duration(td: timedelta | None) -> str:
    if td is None:
        return "–"
    minutes = max(int(td.total_seconds() // 60), 0)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def fmt_height(cm: float | None) -> str:
    return "–" if cm is None else f"{cm / 100:.2f}".replace(".", ",") + " m"


def fmt_time(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%H.%M")


def fmt_date(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{local.day}.{local.month}."
