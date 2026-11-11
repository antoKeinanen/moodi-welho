"""Statistics computed from individual physical cans (never from rendered emoji)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from .staff import Staff


@dataclass
class Stats:
    degrees: int = 0
    cans_33: int = 0
    cans_50: int = 0
    avg_cans: float | None = None
    avg_duration: timedelta | None = None
    avg_height_cm: float | None = None
    top_category: str | None = None
    stones: int = 0
    stone_sizes: Counter[str] = field(default_factory=Counter)

    @property
    def cans(self) -> int:
        return self.cans_33 + self.cans_50

    @property
    def share_33(self) -> float | None:
        """Share of 0.33 L cans among all cans (0..1)."""
        return self.cans_33 / self.cans if self.cans else None


def compute_stats(staffs: list[Staff]) -> Stats:
    """Stats over *finished* staffs only."""
    done = [s for s in staffs if s.done]
    if not done:
        return Stats()
    all_cans = [c for s in done for c in s.cans]
    durations = [s.duration for s in done if s.duration is not None]
    heights = [s.height_cm for s in done if s.height_cm]
    categories = Counter(c.category for c in all_cans if c.category)
    sizes = Counter(s.stone_size for s in done if s.stone_size)
    return Stats(
        degrees=len(done),
        cans_33=sum(1 for c in all_cans if c.size_cl == 33),
        cans_50=sum(1 for c in all_cans if c.size_cl == 50),
        avg_cans=len(all_cans) / len(done),
        avg_duration=sum(durations, timedelta()) / len(durations) if durations else None,
        avg_height_cm=sum(heights) / len(heights) if heights else None,
        top_category=categories.most_common(1)[0][0] if categories else None,
        stones=sum(1 for s in done if s.stone_emoji),
        stone_sizes=sizes,
    )


def leaderboard(staffs: list[Staff], limit: int = 5) -> list[tuple[str, int]]:
    """People with the most completed degrees: [(name, degrees)], best first."""
    counts = Counter((s.user_id, s.user_name) for s in staffs if s.done)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][1].lower()))
    return [(name, n) for (_, name), n in ranked[:limit]]
