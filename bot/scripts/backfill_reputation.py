from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence

from pyrogram import Client, errors
from pyrogram.enums import ChatType
from pyrogram.types import Chat, Message

from bot.database import Database
from bot.services.models import ReputationEntry
from bot.services.reputation_detector import ParsedReputation, SIGN_ONLY_PATTERN, extract_reputation


LOGGER = logging.getLogger("backfill")

SAFE_DELAY = 0.45  # seconds between message fetches
BATCH_COOLDOWN_EVERY = 60  # apply extended sleep after this many processed messages
BATCH_COOLDOWN_DURATION = 8.0  # seconds
HISTORY_CHUNK_SIZE = 100  # pyrogram fetch limit per request


def _resolve_sentiment(sign: str) -> str:
    plus_count = sign.count("+")
    minus_count = sign.count("-")
    return "positive" if plus_count >= minus_count else "negative"


def _normalize_target(value: str) -> str:
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    return value.lower()


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
        sentiment = _resolve_sentiment(match.group("sign"))
        return [ParsedReputation(target=_normalize_target(username), sentiment=sentiment)]
    return []


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
    author_username = author.username if author else None
    author_id = author.id if author else None

    content = message.text or message.caption or ""
    entries: List[ReputationEntry] = []
    for item in parsed:
        entries.append(
            ReputationEntry(
                target=item.target,
                chat_id=chat_id,
                message_id=message.id,
                sentiment=item.sentiment,
                has_photo=has_photo,
                has_media=has_media,
                content=content,
                author_id=author_id,
                author_username=author_username,
                message_date=message.date,
            )
        )
    return entries


async def _register_group(db: Database, chat: Chat) -> None:
    chat_type_map = {
        ChatType.PRIVATE: "private",
        ChatType.GROUP: "group",
        ChatType.SUPERGROUP: "supergroup",
        ChatType.CHANNEL: "channel",
        ChatType.BOT: "bot",
    }
    chat_type = chat_type_map.get(chat.type, "group")
    await db.register_group(chat.id, chat.title, chat.username, chat_type)


async def _respect_rate_limits(counter: int) -> None:
    await asyncio.sleep(SAFE_DELAY)
    if counter % BATCH_COOLDOWN_EVERY == 0:
        await asyncio.sleep(BATCH_COOLDOWN_DURATION)


async def _backfill_chat(
    client: Client,
    db: Database,
    chat_reference: str,
    *,
    limit: Optional[int],
    offset_id: int,
    update_last_processed: bool,
) -> None:
    LOGGER.info("Processing chat %s", chat_reference)
    try:
        chat = await client.get_chat(chat_reference)
    except errors.FloodWait as exc:
        LOGGER.warning("Flood wait while resolving %s: sleeping for %ss", chat_reference, exc.value)
        await asyncio.sleep(exc.value + 1)
        chat = await client.get_chat(chat_reference)
    except errors.RPCError as exc:
        LOGGER.error("Unable to resolve chat %s: %s", chat_reference, exc)
        return

    await _register_group(db, chat)

    processed = 0
    stored = 0
    max_message_id = offset_id

    remaining = limit
    current_offset = offset_id

    while remaining is None or remaining > 0:
        chunk_size = HISTORY_CHUNK_SIZE
        if remaining is not None:
            chunk_size = min(chunk_size, remaining)
        try:
            messages = await client.get_chat_history(chat.id, limit=chunk_size, offset_id=current_offset)
        except errors.FloodWait as exc:
            LOGGER.warning("Flood wait while fetching history for %s: sleeping %ss", chat_reference, exc.value)
            await asyncio.sleep(exc.value + 1)
            continue
        if not messages:
            break

        # get_chat_history returns newest -> oldest; process oldest first
        for message in reversed(messages):
            processed += 1
            max_message_id = max(max_message_id, message.id)
            try:
                entries = await _build_entries(message, chat.id)
            except Exception:  # pragma: no cover - unexpected parsing errors shouldn't abort
                LOGGER.exception("Failed to parse message %s in chat %s", message.id, chat_reference)
                await _respect_rate_limits(processed)
                continue

            if entries:
                inserted = await db.store_reputation_entries(entries)
                if inserted:
                    stored += inserted
            await _respect_rate_limits(processed)

        current_offset = messages[-1].id
        if remaining is not None:
            remaining -= len(messages)
            if remaining <= 0:
                break

    LOGGER.info(
        "Chat %s processed messages=%s stored_entries=%s",
        chat_reference,
        processed,
        stored,
    )
    if update_last_processed and max_message_id:
        await db.set_last_processed_message(chat.id, max_message_id)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill reputation history from Telegram using Pyrogram.")
    parser.add_argument(
        "--api-id",
        type=int,
        help="Telegram API ID (or set PYROGRAM_API_ID env var).",
    )
    parser.add_argument(
        "--api-hash",
        help="Telegram API HASH (or set PYROGRAM_API_HASH env var).",
    )
    parser.add_argument(
        "--session",
        default="reputation_backfill",
        help="Path or name for the Pyrogram session file.",
    )
    parser.add_argument(
        "--database",
        default="data/reputation.db",
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--chats",
        nargs="+",
        required=True,
        help="List of chat usernames or numeric IDs to scan.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of messages to fetch from each chat (default: all).",
    )
    parser.add_argument(
        "--offset-id",
        type=int,
        default=0,
        help="Start scanning from messages with ID greater than this value.",
    )
    parser.add_argument(
        "--update-last-processed",
        action="store_true",
        help="Update the 'last_processed_message_id' for each chat after backfill.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    parser.add_argument(
        "--safe-delay",
        type=float,
        default=SAFE_DELAY,
        help="Base delay (seconds) between processed messages to minimise flood limits.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    global SAFE_DELAY
    SAFE_DELAY = max(0.2, args.safe_delay)

    api_id = args.api_id or os.getenv("PYROGRAM_API_ID") or os.getenv("TELEGRAM_API_ID")
    api_hash = args.api_hash or os.getenv("PYROGRAM_API_HASH") or os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "API credentials are required. Provide --api-id/--api-hash or set PYROGRAM_API_ID/PYROGRAM_API_HASH."
        )
    api_id = int(api_id)

    session_path = Path(args.session)
    session_name = session_path.stem
    workdir = session_path.parent if session_path.parent != Path("") else Path(".")

    db = Database(Path(args.database))
    await db.connect()

    try:
        async with Client(
            name=session_name,
            api_id=api_id,
            api_hash=api_hash,
            workdir=str(workdir.resolve()),
            no_updates=True,
        ) as client:
            for chat in args.chats:
                await _backfill_chat(
                    client,
                    db,
                    chat,
                    limit=args.limit,
                    offset_id=args.offset_id,
                    update_last_processed=args.update_last_processed,
                )
    finally:
        await db.close()


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
