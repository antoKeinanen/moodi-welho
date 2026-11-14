from datetime import UTC, datetime

from velho.staff import (
    Can,
    parse_clock,
    parse_height_cm,
    render_stack,
    single_emoji,
    stack_rows,
    utf16_len,
)

EXAMPLE = [Can(1, 33, "🍎"), Can(2, 50, "🥤"), Can(3, 33, "🍋"), Can(4, 50, "🍺")]


def test_example_staff_from_spec():
    # Top to bottom: stone, 0.5 L beer (2 rows), 0.33 L lemon, 0.5 L drink (2 rows), apple at bottom
    expected = ["💎", "🍺", "🍺", "🍋", "🥤", "🥤", "🍎"]
    assert stack_rows(EXAMPLE, "💎") == expected
    assert render_stack(EXAMPLE, "💎") == "\n".join(expected)


def test_first_can_is_bottom_and_stone_on_top():
    rows = stack_rows(EXAMPLE, "🔮")
    assert rows[0] == "🔮"
    assert rows[-1] == "🍎"


def test_no_stone_while_building():
    assert stack_rows(EXAMPLE)[0] == "🍺"


def test_half_litre_is_one_can_two_rows():
    can = Can(1, 50, "🍺")
    assert can.rows == 2
    assert stack_rows([can]) == ["🍺", "🍺"]


def test_long_stack_is_cut_from_the_bottom_and_keeps_stone():
    cans = [Can(i, 33, "🍎") for i in range(100)]
    text = render_stack(cans, "💎", max_rows=5)
    lines = text.split("\n")
    assert lines[0] == "💎"
    assert len(lines) == 6 and "+96" in lines[-1]


def test_stack_respects_char_budget():
    cans = [Can(i, 50, "🍺") for i in range(2000)]
    text = render_stack(cans, "💎")
    assert utf16_len(text) <= 3100
    assert text.startswith("💎")


def test_ground_only_when_nothing_hidden():
    assert render_stack(EXAMPLE, ground=True).endswith("🟫")
    assert "🟫" not in render_stack(EXAMPLE, ground=True, max_rows=2)


def test_single_emoji():
    assert single_emoji("🍺") == "🍺"
    assert single_emoji(" 👨‍👩‍👧 ") == "👨‍👩‍👧"
    assert single_emoji("🍺🍺") is None
    assert single_emoji("a") is None
    assert single_emoji("🍺 hei") is None


def test_parse_height():
    assert parse_height_cm("182") == 182
    assert parse_height_cm("182 cm") == 182
    assert parse_height_cm("1,82") == 182
    assert parse_height_cm("1.82 m") == 182
    assert parse_height_cm("abc") is None
    assert parse_height_cm("5000") is None


def test_parse_clock_never_in_the_future():
    now = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)  # 20:00 in Helsinki
    assert parse_clock("19.30", now) == datetime(2026, 11, 11, 17, 30, tzinfo=UTC)
    assert parse_clock("21:00", now) == datetime(2026, 11, 10, 19, 0, tzinfo=UTC)  # yesterday
    assert parse_clock("25:00", now) is None


def test_gallery_card_shows_whole_staff_when_it_fits():
    from datetime import UTC, datetime

    from velho.staff import Staff
    from velho.views import gallery_text

    cans = [Can(i, 50, "🍺") for i in range(20)] + [Can(99, 33, "🍎")]
    t = datetime(2026, 1, 1, tzinfo=UTC)
    staffs = [Staff(i, i, f"U{i}", t, finished_at=t, stone_emoji="💎", cans=cans) for i in range(3)]
    text = gallery_text(staffs, "Ryhmä", 3, 0)
    assert text.count("🍺") == 40 * 3 and "alempaa" not in text
    assert utf16_len(text) < 4096
