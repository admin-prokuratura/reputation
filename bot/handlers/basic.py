from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.types.chat_member_updated import ChatMemberUpdated

from ..config import Settings
from ..database import Database

router = Router(name="basic")

MENU_INFO_BUTTON = "Active Groups"
MENU_INSTRUCTION_BUTTON = "How It Works"

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
            "Welcome! This bot helps the Apex community track reputation feedback.",
            "",
            "Use <code>/r @username</code> to request the latest reputation summary after completing the required channel subscriptions.",
        ]
    )
    if settings.admin_ids and message.from_user and message.from_user.id in settings.admin_ids:
        text += "\n\nYou have administrator privileges. Open /admin to manage the bot."
    await message.answer(text, reply_markup=PRIVATE_MENU)


@router.message(F.text == MENU_INFO_BUTTON)
async def show_information(message: Message, db: Database) -> None:
    if message.chat.type != "private":
        return
    groups = await db.list_groups()
    active = [item for item in groups if item.get("is_active")]
    if not active:
        text = (
            "No active groups are registered yet. Invite the bot to a group and run /id so the "
            "administrators can approve it."
        )
    else:
        lines = ["<b>Active reputation groups</b>"]
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
            "<b>How to request a reputation summary</b>",
            "",
            "1. In the group chat send <code>/r @username</code> to see the current balance.",
            "2. To limit the search to a specific chat provide its title: <code>/r @username \"Community\"</code>.",
            "3. Inline mode works everywhere: type <code>@your_bot rep username</code> and choose a result.",
        ]
    )
    await message.answer(text, reply_markup=PRIVATE_MENU)


@router.message(Command("id"))
async def chat_id(message: Message, settings: Settings) -> None:
    if message.chat.type == "private" and (
        not message.from_user or message.from_user.id not in settings.admin_ids
    ):
        return
    await message.reply(f"Chat ID: <code>{message.chat.id}</code>")


@router.my_chat_member()
async def on_chat_member(update: ChatMemberUpdated, db: Database) -> None:
    chat = update.chat
    status = update.new_chat_member.status
    if status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}:
        await db.register_group(chat.id, chat.title, chat.username, chat.type)
    elif status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED, ChatMemberStatus.RESTRICTED}:
        await db.deactivate_group(chat.id)
