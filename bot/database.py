from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiosqlite

from .services.models import DetailedMessage, ReputationEntry, ReputationSummary


class Database:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.execute("PRAGMA journal_mode = WAL;")
        await self.init_models()
        self._logger.info("Connected to database at %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._logger.info("Database connection closed")

    async def init_models(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                type TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                last_processed_message_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                request_count INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                last_request_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reputation_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sentiment TEXT NOT NULL,
                has_photo INTEGER DEFAULT 0,
                has_media INTEGER DEFAULT 0,
                content TEXT,
                author_id INTEGER,
                author_username TEXT,
                message_date INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(target, chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS manual_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                chat_id INTEGER,
                positive_delta INTEGER DEFAULT 0,
                negative_delta INTEGER DEFAULT 0,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS requests_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target TEXT,
                chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reputation_entries_target_chat
                ON reputation_entries(target, chat_id);
            CREATE INDEX IF NOT EXISTS idx_reputation_entries_created_at
                ON reputation_entries(created_at);
            """
        )
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def register_group(self, chat_id: int, title: Optional[str], username: Optional[str], chat_type: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO groups (chat_id, title, username, type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title=excluded.title,
                username=excluded.username,
                type=excluded.type
            """,
            (chat_id, title, username, chat_type),
        )
        await self.conn.commit()

    async def deactivate_group(self, chat_id: int) -> None:
        await self.conn.execute("UPDATE groups SET is_active = 0 WHERE chat_id = ?", (chat_id,))
        await self.conn.commit()

    async def activate_group(self, chat_id: int) -> None:
        await self.conn.execute("UPDATE groups SET is_active = 1 WHERE chat_id = ?", (chat_id,))
        await self.conn.commit()

    async def ensure_user(self, user_id: int, username: Optional[str], first_name: Optional[str],
                          last_name: Optional[str]) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
            """,
            (user_id, username, first_name, last_name),
        )
        await self.conn.commit()

    async def increment_user_requests(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET request_count = request_count + 1, last_request_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )
        await self.conn.commit()

    async def set_user_blocked(self, user_id: int, blocked: bool) -> None:
        await self.conn.execute("UPDATE users SET blocked = ? WHERE user_id = ?", (int(blocked), user_id))
        await self.conn.commit()

    async def is_user_blocked(self, user_id: int) -> bool:
        async with self.conn.execute("SELECT blocked FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return False
            return bool(row[0])

    async def log_request(self, user_id: int, target: str, chat_id: Optional[int]) -> None:
        await self.conn.execute(
            "INSERT INTO requests_log (user_id, target, chat_id) VALUES (?, ?, ?)",
            (user_id, target, chat_id),
        )
        await self.conn.commit()
        self._logger.debug(
            "Logged reputation request: user_id=%s target=%s chat_id=%s",
            user_id,
            target,
            chat_id,
        )

    async def store_reputation_entries(self, entries: Iterable[ReputationEntry]) -> int:
        if not entries:
            self._logger.debug("No reputation entries to store")
            return 0
        query = (
            "INSERT OR IGNORE INTO reputation_entries (target, chat_id, message_id, sentiment, has_photo, has_media, "
            "content, author_id, author_username, message_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        count = 0
        await self.conn.execute("BEGIN")
        try:
            for entry in entries:
                self._logger.debug(
                    "Saving reputation entry: target=%s chat_id=%s message_id=%s sentiment=%s",
                    entry.target,
                    entry.chat_id,
                    entry.message_id,
                    entry.sentiment,
                )
                params = (
                    entry.target.lower(),
                    entry.chat_id,
                    entry.message_id,
                    entry.sentiment,
                    int(entry.has_photo),
                    int(entry.has_media),
                    entry.content,
                    entry.author_id,
                    entry.author_username,
                    int(entry.message_date.timestamp()) if entry.message_date else None,
                )
                cursor = await self.conn.execute(query, params)
                count += cursor.rowcount
        except Exception:
            await self.conn.rollback()
            self._logger.exception("Failed to store reputation entries")
            raise
        else:
            await self.conn.commit()
        if count:
            self._logger.info("Stored %s new reputation entries", count)
        else:
            self._logger.debug("No new reputation entries stored (possibly duplicates)")
        return count

    async def add_manual_adjustment(self, target: str, chat_id: Optional[int], positive: int, negative: int,
                                    note: Optional[str], created_by: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO manual_adjustments (target, chat_id, positive_delta, negative_delta, note, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (target.lower(), chat_id, positive, negative, note, created_by),
        )
        await self.conn.commit()

    async def recent_manual_adjustments(self, limit: int = 10) -> List[Dict[str, Any]]:
        sql = (
            "SELECT target, chat_id, positive_delta, negative_delta, note, created_at, created_by "
            "FROM manual_adjustments ORDER BY created_at DESC LIMIT ?"
        )
        result: List[Dict[str, Any]] = []
        async with self.conn.execute(sql, (limit,)) as cursor:
            async for row in cursor:
                result.append(
                    {
                        "target": row["target"],
                        "chat_id": row["chat_id"],
                        "positive_delta": row["positive_delta"],
                        "negative_delta": row["negative_delta"],
                        "note": row["note"],
                        "created_at": row["created_at"],
                        "created_by": row["created_by"],
                    }
                )
        return result

    async def find_group_by_title(self, title: str) -> Optional[Tuple[int, str]]:
        async with self.conn.execute(
            "SELECT chat_id, title FROM groups WHERE lower(title) = ? OR lower(username) = ?",
            (title.lower(), title.lower().lstrip("@")),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return row[0], row[1]

    async def get_group_title(self, chat_id: int) -> Optional[str]:
        async with self.conn.execute("SELECT title FROM groups WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None

    async def fetch_summary(
        self,
        target: str,
        chat_id: Optional[int] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ReputationSummary:
        target_key = target.lower()
        params: List[Any] = [target_key]
        where_clause = "target = ?"
        if chat_id is not None:
            where_clause += " AND chat_id = ?"
            params.append(chat_id)

        sentiment_sql = f"""
            SELECT
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative,
                SUM(CASE WHEN sentiment = 'positive' AND (has_photo = 1 OR has_media = 1) THEN 1 ELSE 0 END) AS positive_with_media,
                SUM(CASE WHEN sentiment = 'negative' AND (has_photo = 1 OR has_media = 1) THEN 1 ELSE 0 END) AS negative_with_media
            FROM reputation_entries
            WHERE {where_clause}
        """
        async with self.conn.execute(sentiment_sql, params) as cursor:
            row = await cursor.fetchone()
            if row is None:
                positive = negative = positive_with_media = negative_with_media = 0
            else:
                positive, negative, positive_with_media, negative_with_media = [row[idx] or 0 for idx in range(4)]

        adjustment_sql = """
            SELECT COALESCE(SUM(positive_delta), 0), COALESCE(SUM(negative_delta), 0)
            FROM manual_adjustments
            WHERE target = ? {chat_filter}
        """.format(chat_filter="AND chat_id = ?" if chat_id is not None else "")
        adj_params = [target_key]
        if chat_id is not None:
            adj_params.append(chat_id)
        async with self.conn.execute(adjustment_sql, adj_params) as cursor:
            row = await cursor.fetchone()
            pos_adj, neg_adj = (row[0] or 0, row[1] or 0) if row else (0, 0)

        positive = max(0, (positive or 0) + pos_adj)
        negative = max(0, (negative or 0) + neg_adj)
        positive_with_media = max(0, min(positive, positive_with_media))
        negative_with_media = max(0, min(negative, negative_with_media))

        details_sql = f"""
            SELECT chat_id, message_id, sentiment, has_photo, has_media, content, author_username, created_at
            FROM reputation_entries
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        detail_limit = max(0, limit)
        detail_offset = max(0, offset)
        detail_params = params + [detail_limit, detail_offset]
        details: List[DetailedMessage] = []
        async with self.conn.execute(details_sql, detail_params) as cursor:
            async for row in cursor:
                chat_id_val = row["chat_id"]
                message_id = row["message_id"]
                link = build_message_link(chat_id_val, message_id)
                details.append(
                    DetailedMessage(
                        message_id=message_id,
                        chat_id=chat_id_val,
                        sentiment=row["sentiment"],
                        has_photo=bool(row["has_photo"]),
                        has_media=bool(row["has_media"]),
                        content=row["content"] or "",
                        author_username=row["author_username"],
                        link=link,
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )

        count_sql = f"SELECT COUNT(*) FROM reputation_entries WHERE {where_clause}"
        async with self.conn.execute(count_sql, params) as cursor:
            count_row = await cursor.fetchone()
            details_total = count_row[0] if count_row else 0

        chat_title = None
        if chat_id is not None:
            async with self.conn.execute("SELECT title FROM groups WHERE chat_id = ?", (chat_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    chat_title = row[0]

        self._logger.debug(
            "Fetched summary: target=%s chat_id=%s positive=%s negative=%s details=%s",
            target,
            chat_id,
            positive,
            negative,
            len(details),
        )

        return ReputationSummary(
            target=target,
            chat_id=chat_id,
            chat_title=chat_title,
            positive=positive,
            negative=negative,
            positive_with_media=positive_with_media,
            negative_with_media=negative_with_media,
            details=details,
            details_total=details_total,
        )

    async def fetch_statistics(self) -> Dict[str, Any]:
        async with self.conn.execute("SELECT COUNT(*) FROM groups WHERE is_active = 1") as cursor:
            active_groups = (await cursor.fetchone())[0]
        async with self.conn.execute("SELECT COUNT(*) FROM reputation_entries") as cursor:
            total_entries = (await cursor.fetchone())[0]
        async with self.conn.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with self.conn.execute("SELECT COUNT(*) FROM requests_log") as cursor:
            total_requests = (await cursor.fetchone())[0]
        return {
            "active_groups": active_groups,
            "total_entries": total_entries,
            "total_users": total_users,
            "total_requests": total_requests,
        }

    async def fetch_enhanced_statistics(self, top_limit: int = 5) -> Dict[str, Any]:
        base_stats = await self.fetch_statistics()

        async with self.conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END), 0) AS positive_total,
                COALESCE(SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END), 0) AS negative_total,
                MIN(created_at) AS first_entry,
                MAX(created_at) AS last_entry
            FROM reputation_entries
            """
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                positive_total = row["positive_total"] or 0
                negative_total = row["negative_total"] or 0
                first_raw = row["first_entry"]
                last_raw = row["last_entry"]
            else:
                positive_total = negative_total = 0
                first_raw = last_raw = None

        first_entry = datetime.fromisoformat(first_raw) if first_raw else None
        last_entry = datetime.fromisoformat(last_raw) if last_raw else None

        total_entries = base_stats["total_entries"]
        active_days = 0
        if first_entry and last_entry:
            active_days = max((last_entry.date() - first_entry.date()).days + 1, 1)
        daily_average = (total_entries / active_days) if active_days else 0.0
        balance_total = positive_total - negative_total
        positive_share = round((positive_total / total_entries) * 100) if total_entries else 0

        async with self.conn.execute(
            """
            SELECT COUNT(*) AS recent_count
            FROM reputation_entries
            WHERE created_at >= datetime('now', '-30 days')
            """
        ) as cursor:
            row = await cursor.fetchone()
            recent_30_days = row["recent_count"] if row else 0

        top_limit = max(1, top_limit)
        top_sql = """
            SELECT
                target,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative,
                COUNT(*) AS total
            FROM reputation_entries
            GROUP BY target
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
        """
        top_targets: List[Dict[str, Any]] = []
        async with self.conn.execute(top_sql, (top_limit,)) as cursor:
            async for row in cursor:
                total = row["total"] or 0
                if total <= 0:
                    continue
                positive = row["positive"] or 0
                negative = row["negative"] or 0
                balance = positive - negative
                share = round((positive / total) * 100) if total else 0
                top_targets.append(
                    {
                        "target": row["target"],
                        "total": total,
                        "positive": positive,
                        "negative": negative,
                        "balance": balance,
                        "positive_share": share,
                    }
                )

        total_users = base_stats["total_users"]
        total_requests = base_stats["total_requests"]
        avg_requests_per_user = (
            (total_requests / total_users) if total_users else 0.0
        )

        base_stats.update(
            {
                "positive_total": positive_total,
                "negative_total": negative_total,
                "balance_total": balance_total,
                "positive_share": positive_share,
                "first_entry_at": first_entry,
                "last_entry_at": last_entry,
                "active_days": active_days,
                "daily_average": daily_average,
                "recent_30_days": recent_30_days,
                "avg_requests_per_user": avg_requests_per_user,
                "top_targets": top_targets,
            }
        )
        return base_stats

    async def top_users(self, limit: int = 10) -> List[Dict[str, Any]]:
        sql = (
            "SELECT user_id, username, first_name, last_name, request_count, blocked, last_request_at "
            "FROM users ORDER BY request_count DESC LIMIT ?"
        )
        result: List[Dict[str, Any]] = []
        async with self.conn.execute(sql, (limit,)) as cursor:
            async for row in cursor:
                result.append({
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "first_name": row["first_name"],
                    "last_name": row["last_name"],
                    "request_count": row["request_count"],
                    "blocked": bool(row["blocked"]),
                    "last_request_at": row["last_request_at"],
                })
        return result

    async def active_group_ids(self) -> List[int]:
        result: List[int] = []
        async with self.conn.execute("SELECT chat_id FROM groups WHERE is_active = 1") as cursor:
            async for row in cursor:
                result.append(row["chat_id"])
        return result

    async def active_user_ids(self) -> List[int]:
        result: List[int] = []
        async with self.conn.execute("SELECT user_id FROM users WHERE blocked = 0") as cursor:
            async for row in cursor:
                result.append(row["user_id"])
        return result

    async def list_groups(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        sql = "SELECT chat_id, title, username, is_active, added_at FROM groups ORDER BY added_at DESC"
        async with self.conn.execute(sql) as cursor:
            async for row in cursor:
                result.append({
                    "chat_id": row["chat_id"],
                    "title": row["title"],
                    "username": row["username"],
                    "is_active": bool(row["is_active"]),
                    "added_at": row["added_at"],
                })
        return result

    async def toggle_pause(self, value: bool) -> None:
        await self.conn.execute(
            "INSERT INTO settings(key, value) VALUES('paused', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("1" if value else "0",),
        )
        await self.conn.commit()
        self._logger.info("Bot pause state set to %s", value)

    async def is_paused(self) -> bool:
        async with self.conn.execute("SELECT value FROM settings WHERE key = 'paused'") as cursor:
            row = await cursor.fetchone()
            if row is None:
                return False
            paused = row["value"] == "1"
            self._logger.debug("Pause state queried: %s", paused)
            return paused

    async def set_last_processed_message(self, chat_id: int, message_id: int) -> None:
        await self.conn.execute(
            "UPDATE groups SET last_processed_message_id = ? WHERE chat_id = ?",
            (message_id, chat_id),
        )
        await self.conn.commit()

    async def last_processed_message(self, chat_id: int) -> Optional[int]:
        async with self.conn.execute(
            "SELECT last_processed_message_id FROM groups WHERE chat_id = ?",
            (chat_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None


def build_message_link(chat_id: int, message_id: int) -> str:
    if str(chat_id).startswith("-100"):
        internal_id = str(chat_id)[4:]
        return f"https://t.me/c/{internal_id}/{message_id}"
    return f"https://t.me/{chat_id}/{message_id}"
