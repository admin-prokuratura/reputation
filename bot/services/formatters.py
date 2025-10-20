from __future__ import annotations

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
        f"<b>Положительная:</b> {summary.positive} шт. ({summary.positive_with_media} с медиа)"
    )
    lines.append(
        f"<b>Отрицательная:</b> {summary.negative} шт. ({summary.negative_with_media} с медиа)"
    )
    lines.append("")
    if summary.total == 0:
        lines.append("ℹ️ Пока нет отзывов. Спросите коллег — возможно, у них появится информация.")
    elif summary.negative > summary.positive:
        lines.append("⚠️ <i>Будьте аккуратнее при работе!</i>")
    else:
        lines.append("✅ <i>Репутация выглядит достойно.</i>")
    return "\n".join(lines)


def format_detail_messages(details: list[DetailedMessage], limit: int = 30) -> str:
    if not details:
        return "Пока нет сообщений с репутацией."
    rows = ["<b>Детальный анализ</b>"]
    for item in details[:limit]:
        sentiment_icon = "🟢" if item.sentiment == "positive" else "🔴"
        media_hint = "📷" if item.has_photo else ("📎" if item.has_media else "")
        raw_author = item.author_username or "аноним"
        if raw_author != "аноним" and not raw_author.startswith("@"):
            author = f"@{raw_author}"
        else:
            author = raw_author
        rows.append(
            f"{sentiment_icon}{media_hint} <a href='{item.link}'>Сообщение</a> — {escape_html(author)}"
        )
    return "\n".join(rows)


def build_detail_keyboard(target: str, chat_id: Optional[int]) -> InlineKeyboardMarkup:
    payload = f"detail:{target}:{chat_id if chat_id is not None else 'all'}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔍 Детальный анализ", callback_data=payload)]]
    )
    return keyboard


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
