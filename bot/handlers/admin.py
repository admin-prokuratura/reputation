from __future__ import annotations

import shlex

from aiogram import Bot, Router
from aiogram.filters import Command, Text
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import Settings
from ..database import Database
from ..services.formatters import escape_html

router = Router(name="admin")


def is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


def build_admin_keyboard(paused: bool) -> InlineKeyboardMarkup:
    pause_label = "▶️ Возобновить" if paused else "⏸ Пауза"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
            [InlineKeyboardButton(text=pause_label, callback_data="admin:pause")],
            [InlineKeyboardButton(text="⭐ Управление репутацией", callback_data="admin:reputation")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="💬 Группы", callback_data="admin:groups")],
        ]
    )


@router.message(Command("admin"))
async def admin_panel(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    paused = await db.is_paused()
    keyboard = build_admin_keyboard(paused)
    await message.answer("Панель администратора:", reply_markup=keyboard)


@router.callback_query(Text(startswith="admin:"))
async def admin_actions(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    action = (callback.data or "").split(":", 1)[1]
    if action == "stats":
        stats = await db.fetch_statistics()
        text = (
            "📊 <b>Статистика</b>\n"
            f"Активных групп: <b>{stats['active_groups']}</b>\n"
            f"Сообщений в базе: <b>{stats['total_entries']}</b>\n"
            f"Пользователей: <b>{stats['total_users']}</b>\n"
            f"Запросов: <b>{stats['total_requests']}</b>"
        )
        await callback.message.answer(text)
        await callback.answer()
        return

    if action == "users":
        users = await db.top_users()
        if not users:
            text = "Пока нет пользователей."
        else:
            lines = ["👥 <b>ТОП пользователей</b>"]
            for item in users:
                username = f"@{escape_html(item['username'])}" if item['username'] else "—"
                status = "🚫" if item['blocked'] else "✅"
                lines.append(
                    f"{status} {username} — {item['request_count']} запросов (ID: <code>{item['user_id']}</code>)"
                )
            lines.append(
                "\nКоманды: <code>/block &lt;user_id&gt;</code> / <code>/unblock &lt;user_id&gt;</code>"
            )
            text = "\n".join(lines)
        await callback.message.answer(text)
        await callback.answer()
        return

    if action == "pause":
        current = await db.is_paused()
        await db.toggle_pause(not current)
        new_keyboard = build_admin_keyboard(not current)
        try:
            await callback.message.edit_reply_markup(new_keyboard)
        except Exception:
            await callback.message.answer("Панель обновлена.", reply_markup=new_keyboard)
        await callback.answer("Состояние обновлено")
        return

    if action == "reputation":
        text = (
            "⭐ <b>Управление репутацией</b>\n"
            "Используйте команду <code>/adjust username +10 -3 [chat_id]</code> чтобы добавить или списать баллы.\n"
            "Для обнуления можно указать отрицательное значение, равное текущему количеству."
        )
        await callback.message.answer(text)
        await callback.answer()
        return

    if action == "broadcast":
        text = (
            "📣 <b>Рассылка</b>\n"
            "Ответьте на сообщение и введите <code>/broadcast groups</code> или <code>/broadcast users</code>.\n"
            "Дополнительно можно указать параметры: <code>--button-text</code> и <code>--button-url</code>."
        )
        await callback.message.answer(text)
        await callback.answer()
        return

    if action == "groups":
        groups = await db.list_groups()
        if not groups:
            text = "Групп пока нет. Добавьте бота и используйте /id, чтобы получить идентификатор."
        else:
            lines = ["💬 <b>Группы</b>"]
            for chat in groups[:20]:
                status = "✅" if chat["is_active"] else "⏸"
                title = escape_html(chat["title"] or "Без названия")
                lines.append(
                    f"{status} {title} — ID: <code>{chat['chat_id']}</code>"
                )
            lines.append("\nУдалить группу: <code>/drop_group &lt;chat_id&gt;</code>")
            text = "\n".join(lines)
        await callback.message.answer(text)
        await callback.answer()
        return

    await callback.answer()


@router.message(Command("block"))
async def block_user(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("Использование: /block &lt;user_id&gt;")
        return
    user_id = int(args[1])
    await db.set_user_blocked(user_id, True)
    await message.reply(f"Пользователь {user_id} заблокирован.")


@router.message(Command("unblock"))
async def unblock_user(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("Использование: /unblock &lt;user_id&gt;")
        return
    user_id = int(args[1])
    await db.set_user_blocked(user_id, False)
    await message.reply(f"Пользователь {user_id} разблокирован.")


@router.message(Command("adjust"))
async def adjust_reputation(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    args = shlex.split(message.text)
    if len(args) < 4:
        await message.reply(
            "Использование: <code>/adjust username +10 -3 [chat_id]</code>",
            parse_mode="HTML",
        )
        return
    target = args[1].lstrip("@")
    try:
        positive = int(args[2])
        negative = int(args[3])
    except ValueError:
        await message.reply("Укажите числовые значения для корректировок.")
        return
    chat_id = int(args[4]) if len(args) > 4 and args[4].lstrip("-+").isdigit() else None
    note = "Ручная корректировка"
    await db.add_manual_adjustment(target, chat_id, positive, negative, note, message.from_user.id)
    await message.reply("Корректировка сохранена.")


@router.message(Command("drop_group"))
async def drop_group(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].lstrip("-+").isdigit():
        await message.reply("Использование: /drop_group &lt;chat_id&gt;")
        return
    chat_id = int(args[1])
    await db.deactivate_group(chat_id)
    await message.reply(f"Группа {chat_id} переведена в архив.")


@router.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    args = shlex.split(message.text)
    if len(args) < 2:
        await message.reply(
            "Использование: <code>/broadcast groups</code> или <code>/broadcast users</code> (командой ответьте на сообщение).",
            parse_mode="HTML",
        )
        return
    scope = args[1]
    button_text = None
    button_url = None
    if "--button-text" in args:
        idx = args.index("--button-text")
        if idx + 1 < len(args):
            button_text = args[idx + 1]
    if "--button-url" in args:
        idx = args.index("--button-url")
        if idx + 1 < len(args):
            button_url = args[idx + 1]

    if not message.reply_to_message:
        await message.reply("Эту команду нужно отправлять ответом на сообщение, которое хотите разослать.")
        return

    if scope == "groups":
        targets = await db.active_group_ids()
    elif scope == "users":
        targets = await db.active_user_ids()
    else:
        await message.reply("Укажите scope: groups или users")
        return

    reply = message.reply_to_message
    markup = None
    if button_text and button_url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=button_text, url=button_url)]]
        )

    sent = 0
    for target in targets:
        try:
            await bot.copy_message(
                chat_id=target,
                from_chat_id=reply.chat.id,
                message_id=reply.message_id,
                reply_markup=markup,
            )
            sent += 1
        except Exception:
            continue
    await message.reply(f"Рассылка отправлена {sent} получателям.")
