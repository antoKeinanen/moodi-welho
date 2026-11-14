"""Statistics computed from individual physical cans (never from rendered emoji)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from .staff import Staff


@dataclass
class Stats:
    degrees: int = 0
    failed: int = 0
    failed_cans: int = 0
    cans_33: int = 0
    cans_50: int = 0
    avg_cans: float | None = None
    avg_duration: timedelta | None = None
    avg_height_cm: float | None = None
    top_category: str | None = None
    stones: int = 0
    stone_sizes: Counter[str] = field(default_factory=Counter)

    @property
    def success_rate(self) -> float | None:
        """Share of finished attempts among all ended attempts (0..1)."""
        total = self.degrees + self.failed
        return self.degrees / total if total else None

    @property
    def cans(self) -> int:
        return self.cans_33 + self.cans_50

    @property
    def share_33(self) -> float | None:
        """Share of 0.33 L cans among all cans (0..1)."""
        return self.cans_33 / self.cans if self.cans else None


def compute_stats(staffs: list[Staff]) -> Stats:
    """Degree stats use finished staffs only. Failed attempts are counted separately."""
    done = [s for s in staffs if s.done]
    failed = [s for s in staffs if s.failed]
    failed_cans = sum(len(s.cans) for s in failed)
    if not done:
        return Stats(failed=len(failed), failed_cans=failed_cans)
    all_cans = [c for s in done for c in s.cans]
    durations = [s.duration for s in done if s.duration is not None]
    heights = [s.height_cm for s in done if s.height_cm]
    categories = Counter(c.category for c in all_cans if c.category)
    sizes = Counter(s.stone_size for s in done if s.stone_size)
    return Stats(
        degrees=len(done),
        failed=len(failed),
        failed_cans=failed_cans,
        cans_33=sum(1 for c in all_cans if c.size_cl == 33),
        cans_50=sum(1 for c in all_cans if c.size_cl == 50),
        avg_cans=len(all_cans) / len(done),
        avg_duration=sum(durations, timedelta()) / len(durations) if durations else None,
        avg_height_cm=sum(heights) / len(heights) if heights else None,
        top_category=categories.most_common(1)[0][0] if categories else None,
        stones=sum(1 for s in done if s.stone_emoji),
        stone_sizes=sizes,
    )


def leaderboard(staffs: list[Staff], limit: int = 5) -> list[tuple[str, int, int]]:
    """Members ranked by completed degrees: [(name, degrees, failed attempts)], best first.

    People who have only failed attempts are included too.
    """
    names: dict[int, str] = {}
    degrees: Counter[int] = Counter()
    failed: Counter[int] = Counter()
    for s in staffs:
        names[s.user_id] = s.user_name
        degrees[s.user_id] += s.done
        failed[s.user_id] += s.failed
    ranked = sorted(names, key=lambda u: (-degrees[u], names[u].lower()))
    return [(names[u], degrees[u], failed[u]) for u in ranked[:limit]]
