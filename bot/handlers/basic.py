from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.types.chat_member_updated import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus
from html import escape

from ..config import Settings
from ..database import Database

router = Router(name="basic")


MENU_INFO_BUTTON = "Информация"
MENU_INSTRUCTION_BUTTON = "Инструкция"

PRIVATE_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MENU_INFO_BUTTON), KeyboardButton(text=MENU_INSTRUCTION_BUTTON)]],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def on_start(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        return
    text = "\n".join(
        [
            "Привет! Я бот «Ник бота». Я создан для защиты ваших сделок.",
            "",
            "Нажмите кнопку ниже, чтобы узнать подробнее, или отправьте команду <code>/r @username</code> для проверки репутации.",
        ]
    )
    if settings.admin_ids and message.from_user and message.from_user.id in settings.admin_ids:
        text += (
            "\n\nВы являетесь администратором. Откройте /admin для панели управления."
        )
    await message.answer(text, reply_markup=PRIVATE_MENU)


@router.message(F.text == MENU_INFO_BUTTON)
async def show_information(message: Message, db: Database) -> None:
    if message.chat.type != "private":
        return
    groups = await db.list_groups()
    active = [item for item in groups if item.get("is_active")]
    if not active:
        text = "ℹ️ Пока бот не отслеживает ни один чат. Добавьте его в группу, чтобы начать сбор репутации."
    else:
        lines = ["ℹ️ <b>Бот отслеживает следующие чаты:</b>"]
        for group in active:
            title = group.get("title") or ""
            username = group.get("username")
            identifier = f"ID {group['chat_id']}"
            if title and username:
                display = f"{escape(title)} (@{escape(username)})"
            elif title:
                display = escape(title)
            elif username:
                display = f"@{escape(username)}"
            else:
                display = identifier
            lines.append(f"• {display}")
        text = "\n".join(lines)
    await message.answer(text, reply_markup=PRIVATE_MENU)


@router.message(F.text == MENU_INSTRUCTION_BUTTON)
async def show_instruction(message: Message) -> None:
    if message.chat.type != "private":
        return
    text = "\n".join(
        [
            "🛡 <b>Как проверить репутацию</b>",
            "",
            "1. Отправьте команду <code>/r @username</code> — бот покажет все найденные отзывы.",
            "2. Чтобы сузить поиск до конкретного чата, добавьте его название: <code>/r @username \"Название чата\"</code>.",
            "3. Команда доступна как в группах, так и в личных сообщениях с ботом.",
        ]
    )
    await message.answer(text, reply_markup=PRIVATE_MENU)


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
