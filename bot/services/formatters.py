from __future__ import annotations

import math
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .models import DetailedMessage, ReputationSummary


def format_summary(summary: ReputationSummary) -> str:
    target = summary.target
    if summary.chat_title:
        header = f"<b>Репутация «{escape_html(target)}»</b>\nВ чате: <b>{escape_html(summary.chat_title)}</b>"
    else:
        header = f"<b>Репутация «{escape_html(target)}»</b>"
    lines = [header, ""]
    lines.append(
        f"🟢 <b>Положительная:</b> {summary.positive} шт. ({summary.positive_with_media} с медиа)"
    )
    lines.append(
        f"🔴 <b>Отрицательная:</b> {summary.negative} шт. ({summary.negative_with_media} с медиа)"
    )
    balance = summary.positive - summary.negative
    lines.append(f"⚖️ <b>Баланс:</b> {balance:+d}")
    lines.append("")
    if summary.total == 0:
        lines.append("ℹ️ Пока нет отзывов. Спросите коллег — возможно, у них появится информация.")
    elif summary.negative > summary.positive:
        lines.append("⚠️ <i>Будьте аккуратнее при работе!</i>")
    else:
        if balance > 0:
            lines.append(
                "✅ <i>Репутация выглядит достойно: положительных отзывов больше, чем отрицательных.</i>"
            )
        else:
            lines.append(
                "✅ <i>Репутация выглядит достойно: отрицательных отзывов не больше положительных.</i>"
            )
    return "\n".join(lines)


def format_detail_messages(
    details: list[DetailedMessage],
    total: int,
    page: int,
    page_size: int,
) -> str:
    if total == 0:
        return "Пока нет сообщений с репутацией."

    total_pages = max(1, math.ceil(total / page_size))
    rows = [f"<b>Детальный анализ</b> — страница {page + 1} из {total_pages}"]
    if details:
        start_index = page * page_size + 1
        end_index = start_index + len(details) - 1
        rows.append(f"Показаны записи {start_index}–{end_index} из {total}.")
        rows.append("")
    else:
        rows.append("На этой странице ещё нет записей.")
        return "\n".join(rows)

    for index, item in enumerate(details, start=start_index):
        sentiment_icon = "🟢" if item.sentiment == "positive" else "🔴"
        media_hint = "📷" if item.has_photo else ("📎" if item.has_media else "")
        raw_author = item.author_username or "аноним"
        if raw_author != "аноним" and not raw_author.startswith("@"):
            author = f"@{raw_author}"
        else:
            author = raw_author
        timestamp = item.created_at.strftime("%d.%m.%Y %H:%M")
        rows.append(
            f"{index}. {sentiment_icon}{media_hint} <a href='{item.link}'>Сообщение</a> — {escape_html(author)} · {timestamp}"
        )
    return "\n".join(rows)


def build_detail_keyboard(
    target: str,
    chat_id: Optional[int],
    page: int = 0,
    total: Optional[int] = None,
    page_size: int = 10,
    include_entry_button: bool = True,
) -> InlineKeyboardMarkup:
    payload_base = f"detail:{target}:{chat_id if chat_id is not None else 'all'}"
    buttons: list[list[InlineKeyboardButton]] = []
    if include_entry_button:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔍 Детальный анализ",
                    callback_data=f"{payload_base}:{page}",
                )
            ]
        )

    if total is not None:
        total_pages = max(1, math.ceil(total / page_size))
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"{payload_base}:{page - 1}",
                )
            )
        nav_row.append(InlineKeyboardButton(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="Вперёд ➡️",
                    callback_data=f"{payload_base}:{page + 1}",
                )
            )
        if nav_row:
            buttons.append(nav_row)

    if not buttons:
        buttons.append([
            InlineKeyboardButton(text="🔁 Обновить", callback_data=f"{payload_base}:{page}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_rep_command_keyboard(target: str, chat_query: Optional[str]) -> InlineKeyboardMarkup:
    buttons = []
    buttons.append(
        [
            InlineKeyboardButton(
                text="Посмотреть всю репутацию",
                switch_inline_query_current_chat=f"rep {target}",
            )
        ]
    )
    if chat_query:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"Посмотреть в «{chat_query}»",
                    switch_inline_query_current_chat=f"rep {target} \"{chat_query}\"",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
