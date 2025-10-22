from __future__ import annotations

import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import List

from aiogram.types import Message

from .models import ReputationEntry


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedReputation:
    target: str
    sentiment: str


KEYWORDS = (
    "rep",
    "\u0440\u0435\u043f",
    "\u0440\u0435\u043f\u0443\u0442\u0430\u0446\u0438\u044f",
    "\u0440\u0435\u043f\u0443",
)
RE_PATTERNS = [
    re.compile(
        r"(?P<sign>[+-]+)\s*(?:rep|\u0440\u0435\u043f)\b\s*(?P<target>@?[\w\d_]{3,64})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<target>@?[\w\d_]{3,64})\s*(?P<sign>[+-]+)\s*(?:rep|\u0440\u0435\u043f|\u0440\u0435\u043f\u0443|\u0440\u0435\u043f\u0443\u0442\u0430\u0446(?:\u0438\u044e|\u0438\u044f))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<sign>[+-]+)\s*(?:\u0440\u0435\u043f\u0443|\u0440\u0435\u043f\u0443\u0442\u0430\u0446(?:\u0438\u044e|\u0438\u044f))\b\s*(?P<target>@?[\w\d_]{3,64})",
        re.IGNORECASE,
    ),
]

SIGN_ONLY_PATTERN = re.compile(
    r"(?P<sign>[+-]+)\s*(?:rep|\u0440\u0435\u043f|\u0440\u0435\u043f\u0443|\u0440\u0435\u043f\u0443\u0442\u0430\u0446(?:\u0438\u044e|\u0438\u044f))\b",
    re.IGNORECASE,
)

MENTION_PATTERN = re.compile(r"@([\w\d_]{3,64})")
TOKEN_PATTERN = re.compile(
    r"(?P<sign>[+-]+)\s*(?:rep|\u0440\u0435\u043f|\u0440\u0435\u043f\u0443|\u0440\u0435\u043f\u0443\u0442\u0430\u0446(?:\u0438\u044e|\u0438\u044f))\b|(?P<mention>@[\w\d_]{3,64})",
    re.IGNORECASE,
)


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("@"):
        target = target[1:]
    return target.lower()


def _resolve_sentiment(sign: str) -> str:
    plus_count = sign.count("+")
    minus_count = sign.count("-")
    if plus_count >= minus_count:
        return "positive"
    return "negative"


def extract_reputation(text: str) -> List[ParsedReputation]:
    if not text:
        logger.debug("No text present in message for reputation extraction")
        return []
    lowered = text.lower()
    if not any(keyword in lowered for keyword in KEYWORDS):
        logger.debug("No reputation keywords detected in text: %s", text)
        return []

    sentiments: OrderedDict[str, str] = OrderedDict()

    def register(target: str, sentiment: str) -> None:
        existing = sentiments.get(target)
        if existing == sentiment:
            return
        sentiments[target] = sentiment

    for pattern in RE_PATTERNS:
        for match in pattern.finditer(text):
            sign = match.group("sign")
            raw_target = match.group("target")
            if not raw_target:
                continue
            sentiment = _resolve_sentiment(sign)
            register(normalize_target(raw_target), sentiment)

    pending_mentions: List[str] = []
    current_sign: str | None = None

    for token in TOKEN_PATTERN.finditer(text):
        if token.group("sign"):
            sign = token.group("sign")
            sentiment = _resolve_sentiment(sign)
            if pending_mentions:
                for pending in pending_mentions:
                    register(pending, sentiment)
                pending_mentions.clear()
            current_sign = sentiment
        else:
            mention = normalize_target(token.group("mention"))
            if current_sign is not None:
                register(mention, current_sign)
            elif mention not in pending_mentions:
                pending_mentions.append(mention)

    matches = [
        ParsedReputation(target=target, sentiment=sentiment)
        for target, sentiment in sentiments.items()
    ]

    if matches:
        logger.debug("Reputation matches extracted: %s", matches)
    return matches


def build_entries_from_message(message: Message) -> List[ReputationEntry]:
    text = message.text or message.caption or ""
    parsed = extract_reputation(text)
    if not parsed and message.reply_to_message and message.reply_to_message.from_user:
        reply_user = message.reply_to_message.from_user
        if not getattr(reply_user, "is_bot", False):
            match = SIGN_ONLY_PATTERN.search(text)
            if match:
                target_username = reply_user.username or str(reply_user.id)
                sentiment = _resolve_sentiment(match.group("sign"))
                parsed.append(
                    ParsedReputation(
                        target=normalize_target(target_username),
                        sentiment=sentiment,
                    )
                )
                logger.debug(
                    "Sign-only reputation detected via reply: sign=%s target=%s",
                    match.group("sign"),
                    target_username,
                )
    if not parsed:
        logger.debug(
            "No reputation entries detected for message_id=%s",
            message.message_id,
        )
        return []

    has_photo = bool(message.photo)
    has_media = bool(message.video or message.document or message.animation)
    entries: List[ReputationEntry] = []
    for item in parsed:
        entry = ReputationEntry(
            target=item.target,
            chat_id=message.chat.id,
            message_id=message.message_id,
            sentiment=item.sentiment,
            has_photo=has_photo,
            has_media=has_media,
            content=text,
            author_id=message.from_user.id if message.from_user else None,
            author_username=message.from_user.username if message.from_user else None,
            message_date=message.date,
        )
        entries.append(entry)
        logger.debug("Prepared reputation entry for storage: %s", entry)
    return entries
