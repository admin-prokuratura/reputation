from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..database import Database
from ..services.formatters import format_detail_messages

router = Router(name="callbacks")


@router.callback_query(F.data.startswith("detail:"))
async def detail_view(callback: CallbackQuery, db: Database) -> None:
    payload = callback.data or ""
    try:
        _, target, chat_raw = payload.split(":", 2)
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return

    chat_id: Optional[int]
    if chat_raw == "all":
        chat_id = None
    else:
        try:
            chat_id = int(chat_raw)
        except ValueError:
            chat_id = None

    summary = await db.fetch_summary(target, chat_id, limit=50)
    detail_text = format_detail_messages(summary.details, limit=50)

    if callback.message is not None:
        await callback.message.answer(detail_text, disable_web_page_preview=True)
        await callback.answer("Готово")
        return

    if callback.from_user is not None:
        await callback.bot.send_message(
            callback.from_user.id,
            detail_text,
            disable_web_page_preview=True,
        )
        await callback.answer("Отправил сообщение в личку")
        return

    await callback.answer("Не удалось отправить детали", show_alert=True)
