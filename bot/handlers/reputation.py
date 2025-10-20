from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
                           Message)

from ..config import Settings
from ..database import Database
from ..services.formatters import (build_detail_keyboard, build_rep_command_keyboard,
                                   escape_html, format_summary)
from ..services.reputation_detector import build_entries_from_message
from ..services.models import ReputationSummary
from ..utils.parsing import parse_inline_query, parse_rep_arguments

router = Router(name="reputation")


@router.message(F.chat.type.in_({"group", "supergroup"}) & (F.text | F.caption))
async def capture_reputation(message: Message, db: Database) -> None:
    if await db.is_paused():
        return
    await db.register_group(message.chat.id, message.chat.title, message.chat.username, message.chat.type)
    entries = build_entries_from_message(message)
    if not entries:
        return
    stored = await db.store_reputation_entries(entries)
    if stored:
        await db.set_last_processed_message(message.chat.id, message.message_id)


@router.message(Command("rep"))
async def rep_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return

    if message.chat.type == "private" and message.from_user.id not in settings.admin_ids:
        await message.answer(
            "ℹ️ Поиск репутации доступен только в чатах. Добавьте бота в группу и используйте команду там."
        )
        return
    await db.ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    if await db.is_user_blocked(message.from_user.id):
        await message.reply("🚫 Ваш доступ к боту ограничен. Обратитесь к администратору.")
        return

    text = message.text or ""
    target, chat_query = parse_rep_arguments(text)
    if not target:
        await message.reply(
            "Использование: <code>/rep username \"Название чата\"</code> или просто <code>/rep username</code>."
        )
        return

    keyboard = build_rep_command_keyboard(target.lstrip("@"), chat_query)
    await message.reply(
        "Выберите, какую репутацию нужно показать. Можно также открыть inline-режим и набрать запрос вручную.",
        reply_markup=keyboard,
    )


def build_inline_article(summary: ReputationSummary) -> InlineQueryResultArticle:
    message_text = format_summary(summary)
    keyboard = build_detail_keyboard(summary.target, summary.chat_id)
    return InlineQueryResultArticle(
        id=f"summary-{summary.target}-{summary.chat_id or 'all'}",
        title=f"Репутация {summary.target}",
        description=f"Положительных: {summary.positive} | Отрицательных: {summary.negative}",
        input_message_content=InputTextMessageContent(
            message_text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        ),
        reply_markup=keyboard,
    )


async def resolve_chat_id(db: Database, chat_query: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    if not chat_query:
        return None, None
    stripped = chat_query.strip()
    if stripped.lstrip("-+").isdigit():
        chat_id = int(stripped)
        title = await db.get_group_title(chat_id)
        return chat_id, title
    found = await db.find_group_by_title(stripped)
    if found:
        return found[0], found[1]
    return None, None


@router.inline_query()
async def inline_rep(query: InlineQuery, db: Database, settings: Settings) -> None:
    user = query.from_user
    if user:
        await db.ensure_user(user.id, user.username, user.first_name, user.last_name)
        if await db.is_user_blocked(user.id):
            await query.answer(
                [],
                is_personal=True,
                switch_pm_text="Доступ ограничен",
                switch_pm_parameter="blocked",
                cache_time=10,
            )
            return

    if await db.is_paused():
        await query.answer(
            [],
            is_personal=True,
            switch_pm_text="Бот на паузе",
            switch_pm_parameter="paused",
            cache_time=10,
        )
        return

    target, chat_query = parse_inline_query(query.query)
    if not target:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="hint",
                    title="Как искать репутацию",
                    description="Введи: rep username или rep username \"Название чата\"",
                    input_message_content=InputTextMessageContent(
                        message_text="Введите запрос в формате <code>rep username</code> или добавьте название чата в кавычках.",
                        parse_mode="HTML",
                    ),
                )
            ],
            cache_time=5,
        )
        return

    target_clean = target.lstrip("@")
    chat_id, chat_title = await resolve_chat_id(db, chat_query)
    summary = await db.fetch_summary(target_clean, chat_id)
    note_prefix = ""
    if chat_query and chat_id is None:
        note_prefix = f"Чат «{escape_html(chat_query)}» не найден. \n\n"
    if chat_title and not summary.chat_title:
        summary.chat_title = chat_title
    article = build_inline_article(summary)
    if note_prefix:
        message_text = note_prefix + format_summary(summary)
        article = InlineQueryResultArticle(
            id=f"summary-{summary.target}-{summary.chat_id or 'all'}",
            title=f"Репутация {summary.target}",
            description=f"Положительных: {summary.positive} | Отрицательных: {summary.negative}",
            input_message_content=InputTextMessageContent(
                message_text=message_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            ),
            reply_markup=build_detail_keyboard(summary.target, summary.chat_id),
        )

    await query.answer([article], cache_time=5, is_personal=True)

    if user:
        await db.increment_user_requests(user.id)
        await db.log_request(user.id, target_clean, chat_id)


