from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from aiogram.types import Message

from .models import ReputationEntry


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


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("@"):
        target = target[1:]
    return target.lower()


def extract_reputation(text: str) -> List[ParsedReputation]:
    matches: List[ParsedReputation] = []
    if not text:
        return matches
    lowered = text.lower()
    if not any(keyword in lowered for keyword in KEYWORDS):
        return matches
    for pattern in RE_PATTERNS:
        for match in pattern.finditer(text):
            sign = match.group("sign")
            raw_target = match.group("target")
            if not raw_target:
                continue
            sentiment = "positive" if sign == "+" else "negative"
            matches.append(ParsedReputation(target=normalize_target(raw_target), sentiment=sentiment))
    return matches


def build_entries_from_message(message: Message) -> List[ReputationEntry]:
    text = message.text or message.caption or ""
    parsed = extract_reputation(text)
    if not parsed:
        return []

    has_photo = bool(message.photo)
    has_media = bool(message.video or message.document or message.animation)
    entries: List[ReputationEntry] = []
    for item in parsed:
        entries.append(
            ReputationEntry(
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
        )
    return entries
