"""SQLite storage. Plain sqlite3: the bot is small and every query is instant."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .staff import Can, Staff

# Append new migrations to the list; `PRAGMA user_version` tracks how many have been applied.
MIGRATIONS = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,            -- Telegram user id
        name TEXT NOT NULL,
        height_cm INTEGER,
        state TEXT                          -- what the bot is waiting for (survives restarts)
    );
    CREATE TABLE groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL
    );
    -- /join: the only thing that makes a person's staffs visible in a group
    CREATE TABLE memberships (
        chat_id INTEGER NOT NULL REFERENCES groups(chat_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        joined_at TEXT NOT NULL,
        PRIMARY KEY (chat_id, user_id)
    );
    CREATE TABLE staffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        started_at TEXT NOT NULL,
        finished_at TEXT,                   -- NULL = unfinished attempt
        stone_emoji TEXT,
        stone_size TEXT,
        height_cm INTEGER
    );
    CREATE UNIQUE INDEX one_active_staff ON staffs(user_id) WHERE finished_at IS NULL;
    CREATE TABLE cans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL REFERENCES staffs(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,          -- 1 = bottom of the staff
        size_cl INTEGER NOT NULL CHECK (size_cl IN (33, 50)),
        emoji TEXT NOT NULL,
        category TEXT
    );
    CREATE INDEX cans_by_staff ON cans(staff_id, position);
    """,
    # staff height is now estimated from the cans instead of stored
    "ALTER TABLE staffs DROP COLUMN height_cm;",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Database:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(script)
            self.conn.execute(f"PRAGMA user_version = {i}")
        self.conn.commit()

    def _run(self, sql: str, *args: object) -> sqlite3.Cursor:
        with self.conn:  # commits
            return self.conn.execute(sql, args)

    # --- users & state ---

    def upsert_user(self, user_id: int, name: str) -> None:
        self._run(
            "INSERT INTO users(id, name) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            user_id,
            name,
        )

    def get_state(self, user_id: int) -> str | None:
        row = self.conn.execute("SELECT state FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["state"] if row else None

    def set_state(self, user_id: int, state: str | None) -> None:
        self._run("UPDATE users SET state = ? WHERE id = ?", state, user_id)

    def get_height(self, user_id: int) -> int | None:
        row = self.conn.execute("SELECT height_cm FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["height_cm"] if row else None

    def set_height(self, user_id: int, cm: int | None) -> None:
        self._run("UPDATE users SET height_cm = ? WHERE id = ?", cm, user_id)

    def delete_user(self, user_id: int) -> None:
        """Erase everything about a person (cascades to memberships, staffs and cans)."""
        self._run("DELETE FROM users WHERE id = ?", user_id)

    # --- groups ---

    def join(self, chat_id: int, title: str, user_id: int, now: datetime | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO groups(chat_id, title) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title",
                (chat_id, title),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?, ?, ?)",
                (chat_id, user_id, (now or utcnow()).isoformat()),
            )

    def leave(self, chat_id: int, user_id: int) -> bool:
        return (
            self._run(
                "DELETE FROM memberships WHERE chat_id = ? AND user_id = ?", chat_id, user_id
            ).rowcount
            > 0
        )

    def is_member(self, chat_id: int, user_id: int) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM memberships WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
            ).fetchone()
            is not None
        )

    def user_groups(self, user_id: int) -> list[tuple[int, str]]:
        rows = self.conn.execute(
            "SELECT g.chat_id, g.title FROM groups g JOIN memberships m USING (chat_id) "
            "WHERE m.user_id = ? ORDER BY g.title",
            (user_id,),
        )
        return [(r["chat_id"], r["title"]) for r in rows]

    def group_title(self, chat_id: int) -> str:
        row = self.conn.execute("SELECT title FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
        return row["title"] if row else "ryhmä"

    # --- staffs ---

    def _load(self, where: str, args: tuple = (), tail: str = "") -> list[Staff]:
        rows = self.conn.execute(
            "SELECT s.*, u.name AS user_name FROM staffs s JOIN users u ON u.id = s.user_id "
            f"WHERE {where} {tail}",
            args,
        ).fetchall()
        staffs = {
            r["id"]: Staff(
                id=r["id"],
                user_id=r["user_id"],
                user_name=r["user_name"],
                started_at=datetime.fromisoformat(r["started_at"]),
                finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
                stone_emoji=r["stone_emoji"],
                stone_size=r["stone_size"],
            )
            for r in rows
        }
        if staffs:
            marks = ",".join("?" * len(staffs))
            for c in self.conn.execute(
                f"SELECT * FROM cans WHERE staff_id IN ({marks}) ORDER BY position", tuple(staffs)
            ):
                staffs[c["staff_id"]].cans.append(
                    Can(c["id"], c["size_cl"], c["emoji"], c["category"])
                )
        return [staffs[r["id"]] for r in rows]  # keep the query's ordering

    def get_staff(self, staff_id: int) -> Staff | None:
        found = self._load("s.id = ?", (staff_id,))
        return found[0] if found else None

    def active_staff(self, user_id: int) -> Staff | None:
        found = self._load("s.user_id = ? AND s.finished_at IS NULL", (user_id,))
        return found[0] if found else None

    def start_staff(self, user_id: int, now: datetime | None = None) -> Staff:
        """Start a staff, or return the one already in progress."""
        if (active := self.active_staff(user_id)) is not None:
            return active
        cur = self._run(
            "INSERT INTO staffs(user_id, started_at) VALUES (?, ?)",
            user_id,
            (now or utcnow()).isoformat(),
        )
        return self.get_staff(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def discard_staff(self, staff_id: int, user_id: int) -> None:
        self._run("DELETE FROM staffs WHERE id = ? AND user_id = ?", staff_id, user_id)

    def set_started(self, staff_id: int, when: datetime) -> None:
        self._run(
            "UPDATE staffs SET started_at = ? WHERE id = ? AND finished_at IS NULL",
            when.isoformat(),
            staff_id,
        )

    def finish_staff(self, staff_id: int, stone: str | None, now: datetime | None = None) -> bool:
        """Stamp the finish time, with an optional stone on top. False if already finished."""
        return (
            self._run(
                "UPDATE staffs SET finished_at = ?, stone_emoji = ? "
                "WHERE id = ? AND finished_at IS NULL "
                "AND EXISTS (SELECT 1 FROM cans WHERE staff_id = ?)",
                (now or utcnow()).isoformat(),
                stone,
                staff_id,
                staff_id,
            ).rowcount
            > 0
        )

    def set_stone_size(self, staff_id: int, size: str) -> None:
        self._run("UPDATE staffs SET stone_size = ? WHERE id = ?", size, staff_id)

    # --- cans ---

    def add_can(self, staff_id: int, size_cl: int, emoji: str) -> Can:
        cur = self._run(
            "INSERT INTO cans(staff_id, position, size_cl, emoji) VALUES "
            "(?, (SELECT COALESCE(MAX(position), 0) + 1 FROM cans WHERE staff_id = ?), ?, ?)",
            staff_id,
            staff_id,
            size_cl,
            emoji,
        )
        return Can(cur.lastrowid, size_cl, emoji)  # type: ignore[arg-type]

    def can_owner(self, can_id: int) -> tuple[int, int] | None:
        """(user_id, staff_id) of an *unfinished* staff's can, else None."""
        row = self.conn.execute(
            "SELECT s.user_id, s.id FROM cans c JOIN staffs s ON s.id = c.staff_id "
            "WHERE c.id = ? AND s.finished_at IS NULL",
            (can_id,),
        ).fetchone()
        return (row["user_id"], row["id"]) if row else None

    def remove_can(self, can_id: int) -> bool:
        """Delete a can and close the gap, so positions stay 1..n. False if already gone."""
        with self.conn:
            row = self.conn.execute(
                "SELECT staff_id, position FROM cans WHERE id = ?", (can_id,)
            ).fetchone()
            if row is None:
                return False
            self.conn.execute("DELETE FROM cans WHERE id = ?", (can_id,))
            self.conn.execute(
                "UPDATE cans SET position = position - 1 WHERE staff_id = ? AND position > ?",
                (row["staff_id"], row["position"]),
            )
        return True

    def update_can(
        self,
        can_id: int,
        *,
        emoji: str | None = None,
        size_cl: int | None = None,
        category: str | None = None,
    ) -> None:
        self._run(
            "UPDATE cans SET emoji = COALESCE(?, emoji), size_cl = COALESCE(?, size_cl), "
            "category = COALESCE(?, category) WHERE id = ?",
            emoji,
            size_cl,
            category,
            can_id,
        )

    # --- finished staffs, always scoped by who consented ---

    def own_staffs(self, user_id: int, limit: int = 10) -> list[Staff]:
        return self._load(
            "s.user_id = ? AND s.finished_at IS NOT NULL",
            (user_id,),
            f"ORDER BY s.finished_at DESC, s.id DESC LIMIT {int(limit)}",
        )

    def finished_for_users(self, user_ids: list[int]) -> list[Staff]:
        if not user_ids:
            return []
        marks = ",".join("?" * len(user_ids))
        return self._load(f"s.finished_at IS NOT NULL AND s.user_id IN ({marks})", tuple(user_ids))

    def group_members(self, chat_id: int) -> list[int]:
        rows = self.conn.execute("SELECT user_id FROM memberships WHERE chat_id = ?", (chat_id,))
        return [r["user_id"] for r in rows]

    def group_staffs(self, chat_id: int) -> list[Staff]:
        """All finished staffs of the group's opted-in members."""
        return self.finished_for_users(self.group_members(chat_id))

    _IN_GROUP = (
        "s.finished_at IS NOT NULL AND s.user_id IN "
        "(SELECT user_id FROM memberships WHERE chat_id = ?)"
    )

    def gallery(self, chat_id: int, limit: int, offset: int) -> list[Staff]:
        return self._load(
            self._IN_GROUP,
            (chat_id,),
            f"ORDER BY s.finished_at DESC, s.id DESC LIMIT {int(limit)} OFFSET {int(offset)}",
        )

    def gallery_count(self, chat_id: int) -> int:
        return self.conn.execute(
            f"SELECT COUNT(*) FROM staffs s WHERE {self._IN_GROUP}", (chat_id,)
        ).fetchone()[0]

    def group_staff(self, chat_id: int, staff_id: int) -> Staff | None:
        found = self._load(f"{self._IN_GROUP} AND s.id = ?", (chat_id, staff_id))
        return found[0] if found else None

    def group_staffs_of(self, chat_id: int, user_id: int) -> list[Staff]:
        return self._load(
            f"{self._IN_GROUP} AND s.user_id = ?",
            (chat_id, user_id),
            "ORDER BY s.finished_at DESC, s.id DESC",
        )
