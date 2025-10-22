from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from pyrogram.errors import FloodWait
from pyrogram.types import Message

from ..database import Database
from .account_pool import PyrogramAccountPool
from .models import ReputationEntry
from .reputation_detector import ParsedReputation, SIGN_ONLY_PATTERN, extract_reputation

LOGGER = logging.getLogger(__name__)


async def _parse_reputation_from_message(message: Message) -> List[ParsedReputation]:
    text = (message.text or message.caption or "").strip()
    parsed = extract_reputation(text)
    if parsed:
        return parsed

    reply = message.reply_to_message
    if reply and reply.from_user and not reply.from_user.is_bot:
        match = SIGN_ONLY_PATTERN.search(text)
        if not match:
            return []
        username = reply.from_user.username or str(reply.from_user.id)
        sentiment = "positive" if match.group("sign").count("+") >= match.group("sign").count("-") else "negative"
        parsed.append(ParsedReputation(target=username.lower().lstrip("@"), sentiment=sentiment))
    return parsed


def _detect_media(message: Message) -> tuple[bool, bool]:
    has_photo = message.photo is not None
    has_media = any(
        [
            message.video,
            message.document,
            message.animation,
            message.audio,
            message.voice,
            message.video_note,
        ]
    )
    return has_photo, has_media


async def _build_entries(message: Message, chat_id: int) -> List[ReputationEntry]:
    parsed = await _parse_reputation_from_message(message)
    if not parsed:
        return []

    has_photo, has_media = _detect_media(message)
    author = message.from_user
    author_id = author.id if author else None
    username = author.username if author else None
    content = message.text or message.caption or ""

    entries: List[ReputationEntry] = []
    for item in parsed:
        entries.append(
            ReputationEntry(
                target=item.target.lower(),
                chat_id=chat_id,
                message_id=message.id,
                sentiment=item.sentiment,
                has_photo=has_photo,
                has_media=has_media,
                content=content,
                author_id=author_id,
                author_username=username,
                message_date=message.date,
            )
        )
    return entries


class ReputationFetcher:
    def __init__(self, db: Database, pool: PyrogramAccountPool, per_chat_limit: int = 200) -> None:
        self._db = db
        self._pool = pool
        self._per_chat_limit = per_chat_limit

    async def refresh_target(self, target: str, chat_id: Optional[int] = None) -> None:
        target = target.lstrip("@").lower()
        try:
            client = await self._pool.acquire()
        except RuntimeError:
            LOGGER.debug("ReputationFetcher skipped: no accounts configured")
            return

        chat_ids = [chat_id] if chat_id else await self._db.active_group_ids()
        for cid in chat_ids:
            await self._refresh_chat(client, cid, target)

    async def _refresh_chat(self, client, chat_id: int, target: str) -> None:
        try:
            iterator = client.search_messages(chat_id, query=target, limit=self._per_chat_limit)
        except FloodWait as exc:
            LOGGER.warning("Flood wait while searching chat %s: sleeping %ss", chat_id, exc.value)
            await asyncio.sleep(exc.value + 1)
            iterator = client.search_messages(chat_id, query=target, limit=self._per_chat_limit)

        async for message in iterator:
            try:
                entries = await _build_entries(message, chat_id)
            except Exception:
                LOGGER.exception("Failed to parse message %s in chat %s", message.id, chat_id)
                continue
            if entries:
                await self._db.store_reputation_entries(entries)
