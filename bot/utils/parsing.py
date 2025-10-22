from __future__ import annotations

import re
import shlex
from typing import Optional, Tuple

_TRIM_CHARS = ",;:!.\u2014\u2013"  # strip common punctuation around tokens


_COMMAND_PATTERN = re.compile(r"^/(?:rep|r)(?:@[\w\d_]{3,32})?$")


def parse_rep_arguments(text: str) -> Tuple[Optional[str], Optional[str]]:
    stripped = text.lstrip(" \t" + _TRIM_CHARS)
    parts = shlex.split(stripped)
    cleaned: list[str] = []
    for part in parts:
        candidate = part.strip(_TRIM_CHARS)
        if candidate:
            cleaned.append(candidate)
    if not cleaned:
        return None, None

    first = cleaned[0].lower()
    if _COMMAND_PATTERN.match(first):
        cleaned = cleaned[1:]
    if not cleaned:
        return None, None

    target = cleaned[0]
    chat_title = cleaned[1] if len(cleaned) > 1 else None
    return target, chat_title


_INLINE_PREFIX = re.compile(r"^(?:[+\-/]?)(?:rep|r)\b", re.IGNORECASE)


def parse_inline_query(query: str) -> Tuple[Optional[str], Optional[str]]:
    query = query.strip()
    query = query.lstrip(_TRIM_CHARS)
    if not query:
        return None, None

    match = _INLINE_PREFIX.match(query)
    if match:
        query = query[match.end() :].strip()

    return parse_rep_arguments(query)
