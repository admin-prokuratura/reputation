from __future__ import annotations

import shlex
from typing import Optional, Tuple


def parse_rep_arguments(text: str) -> Tuple[Optional[str], Optional[str]]:
    parts = shlex.split(text)
    if not parts:
        return None, None
    if parts[0].lower() == "/rep":
        parts = parts[1:]
    if not parts:
        return None, None
    target = parts[0]
    chat_title = parts[1] if len(parts) > 1 else None
    return target, chat_title


def parse_inline_query(query: str) -> Tuple[Optional[str], Optional[str]]:
    query = query.strip()
    if not query:
        return None, None
    if query.lower().startswith("rep"):
        query = query[3:].strip()
    return parse_rep_arguments(query)
