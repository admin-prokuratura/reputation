from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List

from aiogram.types import Message

from .models import ReputationEntry


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedReputation:
    target: str
    sentiment: str


KEYWORDS = ("rep", "реп", "репутация", "репу")
RE_PATTERNS = [
    re.compile(r"(?P<sign>[+-])\s*(?:rep|реп)\s*(?P<target>@?[\w\d_]{3,64})", re.IGNORECASE),
    re.compile(r"(?P<target>@?[\w\d_]{3,64})\s*(?P<sign>[+-])\s*(?:rep|реп)", re.IGNORECASE),
    re.compile(r"(?P<sign>[+-])\s*(?:репу|репутацию)\s*(?P<target>@?[\w\d_]{3,64})", re.IGNORECASE),
]

SIGN_ONLY_PATTERN = re.compile(
    r"(?P<sign>[+-])\s*(?:rep|реп|репу|репутац(?:ию|ия))\b",
    re.IGNORECASE,
)

MENTION_PATTERN = re.compile(r"@([\w\d_]{3,64})")


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("@"):
        target = target[1:]
    return target.lower()


def extract_reputation(text: str) -> List[ParsedReputation]:
    matches: List[ParsedReputation] = []
    if not text:
        logger.debug("No text present in message for reputation extraction")
        return matches
    lowered = text.lower()
    if not any(keyword in lowered for keyword in KEYWORDS):
        logger.debug("No reputation keywords detected in text: %s", text)
        return matches
    for pattern in RE_PATTERNS:
        for match in pattern.finditer(text):
            sign = match.group("sign")
            raw_target = match.group("target")
            if not raw_target:
                continue
            sentiment = "positive" if sign == "+" else "negative"
            matches.append(ParsedReputation(target=normalize_target(raw_target), sentiment=sentiment))

    if matches:
        logger.debug("Reputation matches extracted: %s", matches)
        negative_mentions = {item.target for item in matches if item.sentiment == "negative"}
        mentions_in_text: List[str] = []
        for mention_match in MENTION_PATTERN.finditer(text):
            normalized = normalize_target(mention_match.group(0))
            if normalized not in mentions_in_text:
                mentions_in_text.append(normalized)
        if len(mentions_in_text) >= 2 and negative_mentions:
            for mention in mentions_in_text:
                if mention not in negative_mentions:
                    matches.append(ParsedReputation(target=mention, sentiment="negative"))
                    negative_mentions.add(mention)
        logger.debug("Final matches after mention balancing: %s", matches)
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
                sentiment = "positive" if match.group("sign") == "+" else "negative"
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
        logger.debug("No reputation entries detected for message_id=%s", message.message_id)
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
