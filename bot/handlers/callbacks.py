from __future__ import annotations

import math
from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from ..database import Database
from ..services.formatters import build_detail_keyboard, format_detail_messages

router = Router(name="callbacks")


@router.callback_query(F.data.startswith("detail:"))
async def detail_view(callback: CallbackQuery, db: Database) -> None:
    payload = callback.data or ""
    parts = payload.split(":")
    if len(parts) < 3:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    _, target, chat_raw, *rest = parts

    chat_id: Optional[int]
    if chat_raw == "all":
        chat_id = None
    else:
        try:
            chat_id = int(chat_raw)
        except ValueError:
            chat_id = None

    try:
        page = int(rest[0]) if rest else 0
    except ValueError:
        page = 0
    page = max(page, 0)
    page_size = 10
    offset = page * page_size

    summary = await db.fetch_summary(target, chat_id, limit=page_size, offset=offset)
    total_pages = max(1, math.ceil(summary.details_total / page_size)) if summary.details_total else 1
    if summary.details_total and page >= total_pages:
        page = total_pages - 1
        offset = page * page_size
        summary = await db.fetch_summary(target, chat_id, limit=page_size, offset=offset)
    detail_text = format_detail_messages(summary.details, summary.details_total, page, page_size)
    keyboard = build_detail_keyboard(
        target,
        chat_id,
        page=page,
        total=summary.details_total,
        page_size=page_size,
        include_entry_button=False,
    )

    if callback.message is not None:
        await callback.message.answer(
            detail_text,
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
        await callback.answer("Готово")
        return

    if callback.from_user is not None:
        try:
            await callback.bot.send_message(
                callback.from_user.id,
                detail_text,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            await callback.answer(
                "Чтобы получить детали, напишите боту в личку и отправьте команду /start.",
                show_alert=True,
            )
            return
        await callback.answer("Отправил сообщение в личку")
        return

    await callback.answer("Не удалось отправить детали", show_alert=True)
