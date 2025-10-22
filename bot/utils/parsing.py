from __future__ import annotations

import re
import shlex
from typing import Optional, Tuple


def parse_rep_arguments(text: str) -> Tuple[Optional[str], Optional[str]]:
    parts = shlex.split(text)
    if not parts:
        return None, None
    first = parts[0].lower()
    if first in {"/rep", "/r"}:
        parts = parts[1:]
    if not parts:
        return None, None
    target = parts[0]
    chat_title = parts[1] if len(parts) > 1 else None
    return target, chat_title


_INLINE_PREFIX = re.compile(r"^(?:[+\-/]?)(?:rep|r)\b", re.IGNORECASE)


def parse_inline_query(query: str) -> Tuple[Optional[str], Optional[str]]:
    query = query.strip()
    if not query:
        return None, None

    match = _INLINE_PREFIX.match(query)
    if match:
        query = query[match.end() :].strip()

    return parse_rep_arguments(query)
