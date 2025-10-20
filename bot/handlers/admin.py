from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Dict, Literal, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import Settings
from ..database import Database
from ..services.formatters import escape_html

router = Router(name="admin")


@dataclass
class PendingReputation:
    stage: Literal["await_data"]
    prompt_message_id: int


@dataclass
class PendingBroadcast:
    scope: Literal["groups", "users"]
    stage: Literal[
        "await_content",
        "await_button_choice",
        "await_button_text",
        "await_button_url",
    ]
    prompt_message_id: int
    content_chat_id: Optional[int] = None
    content_message_id: Optional[int] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None


pending_reputation: Dict[int, PendingReputation] = {}
pending_broadcast: Dict[int, PendingBroadcast] = {}


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


def build_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for item in users:
        user_id = item["user_id"]
        blocked = bool(item["blocked"])
        action = "unblock" if blocked else "block"
        label = "Разблокировать" if blocked else "Заблокировать"
        emoji = "✅" if blocked else "🚫"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{emoji} {label} {user_id}",
                    callback_data=f"admin:user:{action}:{user_id}",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:users:refresh"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_groups_keyboard(groups: list[dict[str, object]]) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for group in groups[:20]:
        chat_id = group["chat_id"]
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Удалить {chat_id}",
                    callback_data=f"admin:group:drop:{chat_id}",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:groups:refresh"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_broadcast_scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователям", callback_data="admin:broadcast:scope:users")],
            [InlineKeyboardButton(text="💬 Группам", callback_data="admin:broadcast:scope:groups")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")],
        ]
    )


def build_broadcast_button_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="admin:broadcast:add_button:yes")],
            [InlineKeyboardButton(text="➡️ Отправить без кнопки", callback_data="admin:broadcast:add_button:no")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:broadcast:cancel")],
        ]
    )


def format_users_list(users: list[dict[str, object]]) -> str:
    if not users:
        return "Пока нет пользователей."
    lines = ["👥 <b>ТОП пользователей</b>"]
    for item in users:
        username = f"@{escape_html(item['username'])}" if item['username'] else "—"
        status = "🚫" if item['blocked'] else "✅"
        lines.append(
            f"{status} {username} — {item['request_count']} запросов (ID: <code>{item['user_id']}</code>)"
        )
    lines.append("\nИспользуйте кнопки ниже, чтобы ограничить или вернуть доступ.")
    return "\n".join(lines)


def format_groups_list(groups: list[dict[str, object]]) -> str:
    if not groups:
        return "Групп пока нет. Добавьте бота и используйте /id, чтобы получить идентификатор."
    lines = ["💬 <b>Группы</b>"]
    for chat in groups[:20]:
        status = "✅" if chat["is_active"] else "⏸"
        title = escape_html(chat["title"] or "Без названия")
        lines.append(f"{status} {title} — ID: <code>{chat['chat_id']}</code>")
    lines.append("\nВыберите группу ниже, чтобы перевести её в архив.")
    return "\n".join(lines)


@router.message(Command("admin"))
async def admin_panel(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    paused = await db.is_paused()
    keyboard = build_admin_keyboard(paused)
    await message.answer("Панель администратора:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("admin:"))
async def admin_actions(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    raw_data = callback.data or ""
    if raw_data.count(":") > 1:
        raise SkipHandler
    action = raw_data.split(":", 1)[1]
    if action == "home":
        paused = await db.is_paused()
        keyboard = build_admin_keyboard(paused)
        await callback.message.edit_text("Панель администратора:", reply_markup=keyboard)
        await callback.answer()
        return

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
        text = format_users_list(users)
        keyboard = build_users_keyboard(users) if users else InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
        )
        await callback.message.answer(text, reply_markup=keyboard)
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
            "Нажмите кнопку ниже, чтобы добавить ручную корректировку или посмотреть последние действия."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Новая корректировка", callback_data="admin:reputation:new")],
                [InlineKeyboardButton(text="📄 Последние корректировки", callback_data="admin:reputation:history")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")],
            ]
        )
        await callback.message.answer(text, reply_markup=keyboard)
        await callback.answer()
        return

    if action == "broadcast":
        text = (
            "📣 <b>Рассылка</b>\n"
            "Выберите получателей. После выбора бот попросит отправить сообщение для рассылки."
        )
        await callback.message.answer(text, reply_markup=build_broadcast_scope_keyboard())
        await callback.answer()
        return

    if action == "groups":
        groups = await db.list_groups()
        text = format_groups_list(groups)
        keyboard = build_groups_keyboard(groups) if groups else InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
        )
        await callback.message.answer(text, reply_markup=keyboard)
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(F.data.startswith("admin:user:"))
async def handle_user_actions(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    action, target_id = parts[2], parts[3]
    if not target_id.isdigit():
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    target_user_id = int(target_id)
    if action == "block":
        await db.set_user_blocked(target_user_id, True)
        await callback.answer("Пользователь заблокирован")
    elif action == "unblock":
        await db.set_user_blocked(target_user_id, False)
        await callback.answer("Доступ возвращён")
    else:
        await callback.answer()
        return
    users = await db.top_users()
    text = format_users_list(users)
    keyboard = build_users_keyboard(users) if users else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin:users:refresh")
async def refresh_users(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    users = await db.top_users()
    text = format_users_list(users)
    keyboard = build_users_keyboard(users) if users else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("admin:group:"))
async def handle_group_actions(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    action, chat_id_raw = parts[2], parts[3]
    if not chat_id_raw.lstrip("-+").isdigit():
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    chat_id = int(chat_id_raw)
    if action == "drop":
        await db.deactivate_group(chat_id)
        await callback.answer("Группа переведена в архив")
    else:
        await callback.answer()
        return
    groups = await db.list_groups()
    text = format_groups_list(groups)
    keyboard = build_groups_keyboard(groups) if groups else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin:groups:refresh")
async def refresh_groups(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    groups = await db.list_groups()
    text = format_groups_list(groups)
    keyboard = build_groups_keyboard(groups) if groups else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home")]]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Обновлено")


@router.callback_query(F.data == "admin:reputation:new")
async def request_manual_adjustment(callback: CallbackQuery, settings: Settings) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    prompt = await callback.message.answer(
        "Введите данные для корректировки в формате: <code>username +10 -3 [chat_id]</code>",
        parse_mode="HTML",
    )
    pending_reputation[user.id] = PendingReputation(stage="await_data", prompt_message_id=prompt.message_id)
    await callback.answer("Ожидаю данные")


@router.callback_query(F.data == "admin:reputation:history")
async def show_manual_adjustments(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    adjustments = await db.recent_manual_adjustments()
    if not adjustments:
        text = "Пока нет ручных корректировок."
    else:
        lines = ["📄 <b>Последние корректировки</b>"]
        for item in adjustments:
            username = item["target"]
            pos = item["positive_delta"]
            neg = item["negative_delta"]
            chat = item.get("chat_id")
            creator = item.get("created_by")
            created_at = item.get("created_at")
            parts = [f"👤 <code>{escape_html(username)}</code>"]
            if chat:
                parts.append(f"в чате <code>{chat}</code>")
            parts.append(f"+{pos} / -{neg}")
            if creator:
                parts.append(f"от <code>{creator}</code>")
            if created_at:
                parts.append(created_at)
            lines.append(" ".join(parts))
        text = "\n".join(lines)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:broadcast:scope:"))
async def choose_broadcast_scope(callback: CallbackQuery, settings: Settings) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    scope = (callback.data or "").split(":")[-1]
    if scope not in {"groups", "users"}:
        await callback.answer()
        return
    prompt = await callback.message.answer(
        "Отправьте сообщение, которое нужно разослать. Оно может содержать текст, фото или другие вложения.",
    )
    pending_broadcast[user.id] = PendingBroadcast(
        scope=scope,
        stage="await_content",
        prompt_message_id=prompt.message_id,
    )
    await callback.answer("Жду сообщение")


@router.callback_query(F.data.startswith("admin:broadcast:add_button:"))
async def broadcast_button_choice(callback: CallbackQuery, settings: Settings, bot: Bot, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    state = pending_broadcast.get(user.id)
    if not state:
        await callback.answer("Нет активной рассылки", show_alert=True)
        return
    choice = (callback.data or "").split(":")[-1]
    if choice == "yes":
        state.stage = "await_button_text"
        prompt = await callback.message.answer("Введите текст кнопки")
        state.prompt_message_id = prompt.message_id
        await callback.answer("Жду текст кнопки")
        return
    if choice == "no":
        await perform_broadcast(callback.message, bot, db, user.id, state)
        await callback.answer("Рассылка отправлена")
        return
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:cancel")
async def cancel_broadcast(callback: CallbackQuery, settings: Settings) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    if user.id in pending_broadcast:
        pending_broadcast.pop(user.id)
    await callback.answer("Рассылка отменена")
    await callback.message.answer("Рассылка отменена.")


async def perform_broadcast(message: Message, bot: Bot, db: Database, admin_id: int, state: PendingBroadcast) -> None:
    if state.content_chat_id is None or state.content_message_id is None:
        await message.answer("Нет сообщения для рассылки.")
        pending_broadcast.pop(admin_id, None)
        return
    if state.scope == "groups":
        targets = await db.active_group_ids()
    else:
        targets = await db.active_user_ids()
    markup = None
    if state.button_text and state.button_url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=state.button_text, url=state.button_url)]]
        )
    sent = 0
    for target in targets:
        try:
            await bot.copy_message(
                chat_id=target,
                from_chat_id=state.content_chat_id,
                message_id=state.content_message_id,
                reply_markup=markup,
            )
            sent += 1
        except Exception:
            continue
    pending_broadcast.pop(admin_id, None)
    await message.answer(f"Рассылка отправлена {sent} получателям.")


@router.message()
async def handle_admin_inputs(message: Message, settings: Settings, db: Database, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        raise SkipHandler
    user_id = message.from_user.id
    rep_state = pending_reputation.get(user_id)
    if rep_state and rep_state.stage == "await_data":
        args = shlex.split(message.text or "")
        if len(args) < 3:
            await message.reply(
                "Не удалось распознать данные. Используйте формат: <code>username +10 -3 [chat_id]</code>",
                parse_mode="HTML",
            )
            return
        target = args[0].lstrip("@")
        try:
            positive = int(args[1])
            negative = int(args[2])
        except ValueError:
            await message.reply("Укажите числовые значения для корректировок.")
            return
        chat_id = int(args[3]) if len(args) > 3 and args[3].lstrip("-+").isdigit() else None
        note = "Ручная корректировка"
        await db.add_manual_adjustment(target, chat_id, positive, negative, note, user_id)
        pending_reputation.pop(user_id, None)
        await message.reply("Корректировка сохранена.")
        return

    broadcast_state = pending_broadcast.get(user_id)
    if not broadcast_state:
        raise SkipHandler
    if broadcast_state.stage == "await_content":
        broadcast_state.content_chat_id = message.chat.id
        broadcast_state.content_message_id = message.message_id
        broadcast_state.stage = "await_button_choice"
        await message.reply("Добавить кнопку к рассылке?", reply_markup=build_broadcast_button_choice())
        return
    if broadcast_state.stage == "await_button_text":
        if not message.text:
            await message.reply("Текст кнопки не может быть пустым.")
            return
        broadcast_state.button_text = message.text
        broadcast_state.stage = "await_button_url"
        prompt = await message.reply("Отправьте ссылку для кнопки")
        broadcast_state.prompt_message_id = prompt.message_id
        return
    if broadcast_state.stage == "await_button_url":
        if not message.text:
            await message.reply("Ссылка не может быть пустой.")
            return
        broadcast_state.button_url = message.text
        broadcast_state.stage = "await_button_choice"
        await perform_broadcast(message, bot, db, user_id, broadcast_state)
        return

    raise SkipHandler
