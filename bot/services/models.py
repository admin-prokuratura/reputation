from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass(slots=True)
class ReputationEntry:
    target: str
    chat_id: int
    message_id: int
    sentiment: str
    has_photo: bool
    has_media: bool
    content: str
    author_id: Optional[int]
    author_username: Optional[str]
    message_date: Optional[datetime]


@dataclass(slots=True)
class DetailedMessage:
    message_id: int
    chat_id: int
    sentiment: str
    has_photo: bool
    has_media: bool
    content: str
    author_username: Optional[str]
    link: str
    created_at: datetime


@dataclass(slots=True)
class ReputationSummary:
    target: str
    chat_id: Optional[int]
    chat_title: Optional[str]
    positive: int
    negative: int
    positive_with_media: int
    negative_with_media: int
    details: List[DetailedMessage]

    @property
    def total(self) -> int:
        return self.positive + self.negative

    def has_any(self) -> bool:
        return self.total > 0


@dataclass(slots=True)
class BroadcastPayload:
    text: str
    parse_mode: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    photo_path: Optional[str] = None

    @classmethod
    def from_form(cls, text: str, button_text: Optional[str] = None, button_url: Optional[str] = None,
                  parse_mode: Optional[str] = "HTML", photo_path: Optional[str] = None) -> "BroadcastPayload":
        return cls(text=text, button_text=button_text, button_url=button_url, parse_mode=parse_mode,
                   photo_path=photo_path)
