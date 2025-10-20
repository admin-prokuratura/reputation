from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.types.chat_member_updated import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus

from ..config import Settings
from ..database import Database

router = Router(name="basic")


@router.message(CommandStart())
async def on_start(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        return
    text = (
        "Не работаю по личке."
    )
    if settings.admin_ids and message.from_user and message.from_user.id in settings.admin_ids:
        text += (
            "\n\nВы являетесь администратором. Откройте /admin для панели управления."
        )
    await message.answer(text)


@router.message(Command("id"))
async def chat_id(message: Message, settings: Settings) -> None:
    if message.chat.type == "private" and (
        not message.from_user or message.from_user.id not in settings.admin_ids
    ):
        return
    await message.reply(f"ID этого чата: <code>{message.chat.id}</code>")


@router.my_chat_member()
async def on_chat_member(update: ChatMemberUpdated, db: Database) -> None:
    chat = update.chat
    status = update.new_chat_member.status
    if status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}:
        await db.register_group(chat.id, chat.title, chat.username, chat.type)
    elif status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED, ChatMemberStatus.RESTRICTED}:
        await db.deactivate_group(chat.id)
