from __future__ import annotations

import hashlib
import shlex
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram import Client, errors

from ..config import Settings
from ..database import Database
from ..services.account_pool import PyrogramAccountPool
from ..services.formatters import build_detail_keyboard, escape_html, format_summary

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
stats_target_cache: Dict[str, str] = {}


@dataclass
class PendingApiConfig:
    stage: Literal["await_credentials"]
    prompt_message_id: int


@dataclass
class PendingAccount:
    stage: Literal["await_phone", "await_code", "await_password"]
    prompt_message_id: int
    session_name: Optional[str] = None
    phone_number: Optional[str] = None
    phone_code_hash: Optional[str] = None
    client: Optional[Client] = None


pending_api: Dict[int, PendingApiConfig] = {}
pending_accounts: Dict[int, PendingAccount] = {}


async def _reset_pending_account(user_id: int) -> None:
    state = pending_accounts.pop(user_id, None)
    if state and state.client:
        try:
            await state.client.disconnect()
        except Exception:
            pass



def _format_date(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime("%d.%m.%Y")


def format_enhanced_statistics(stats: Dict[str, Any]) -> str:
    lines = ["📊 <b>Статистика</b>"]
    lines.append(f"Активных групп: <b>{stats['active_groups']}</b>")
    lines.append(f"Всего отзывов: <b>{stats['total_entries']}</b>")
    lines.append(
        f"Положительных: <b>{stats['positive_total']}</b> · Отрицательных: <b>{stats['negative_total']}</b>"
    )
    lines.append(
        f"Баланс: <b>{stats['balance_total']:+d}</b> · Доля позитивных: <b>{stats['positive_share']}%</b>"
    )
    lines.append(
        "Пользователей: "
        f"<b>{stats['total_users']}</b> (≈ {stats['avg_requests_per_user']:.1f} запросов на человека)"
    )
    lines.append(f"Всего запросов: <b>{stats['total_requests']}</b>")
    first_formatted = _format_date(stats.get("first_entry_at"))
    last_formatted = _format_date(stats.get("last_entry_at"))
    if first_formatted and last_formatted:
        lines.append(
            f"Период наблюдений: <b>{first_formatted}</b> – <b>{last_formatted}</b>"
            f" ({stats['active_days']} дн.)"
        )
    lines.append(f"Средний поток в день: <b>{stats['daily_average']:.1f}</b>")
    lines.append(f"Добавлено за 30 дней: <b>{stats['recent_30_days']}</b>")
    if stats['top_targets']:
        lines.append("")
        lines.append("🏅 <b>ТОП участников по отзывам</b>")
        for index, item in enumerate(stats['top_targets'], start=1):
            target = escape_html(item['target'])
            lines.append(
                f"{index}. <code>{target}</code> — {item['total']} шт."
                f" (баланс {item['balance']:+d}, 🟢 {item['positive_share']}%)"
            )
        lines.append("")
        lines.append("Выберите участника кнопкой ниже, чтобы открыть подробный отчёт.")
    else:
        lines.append("")
        lines.append("Пока нет участников с отзывами.")
    return "\n".join(lines)


def build_stats_keyboard(top_targets: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineKeyboardButton]] = []
    if len(stats_target_cache) > 1000:
        stats_target_cache.clear()
    for index, item in enumerate(top_targets, start=1):
        target = item["target"]
        token = hashlib.sha1(target.lower().encode("utf-8")).hexdigest()[:10]
        stats_target_cache[token] = target
        label_target = target if len(target) <= 24 else f"{target[:23]}…"
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{index}. {label_target} ({item['total']})",
                    callback_data=f"admin:stats:target:{token}",
                )
            ]
        )
    inline_keyboard.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats:refresh"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


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
            [InlineKeyboardButton(text="Настройка аккаунта", callback_data="admin:accounts")],
            [InlineKeyboardButton(text="💬 Группы", callback_data="admin:groups")],
        ]
    )

def build_account_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 API ID/Hash", callback_data="admin:accounts:api")],
            [InlineKeyboardButton(text="\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0430\u043a\u043a\u0430\u0443\u043d\u0442", callback_data="admin:accounts:add")],
            [InlineKeyboardButton(text="\u0421\u043f\u0438\u0441\u043e\u043a \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u043e\u0432", callback_data="admin:accounts:list")],
            [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data="admin:home")],
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

async def format_account_list(db: Database) -> str:
    accounts = await db.list_pyrogram_accounts()
    if not accounts:
        return 'Аккаунты не настроены.'
    rows = ['Сохранённые аккаунты:']
    for item in accounts:
        status = 'активен' if item['is_active'] else 'отключён'
        phone = item['phone_number'] or '\u2014'
        rows.append(f"\u2022 {phone} — {status}")
    rows.append("")
    rows.append('Новые аккаунты потребуют действительный API ID/Hash и вход через код.')
    return '\n'.join(rows)




@router.message(Command("admin"))
async def admin_panel(message: Message, settings: Settings, db: Database) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        return
    paused = await db.is_paused()
    keyboard = build_admin_keyboard(paused)
    await message.answer("Панель администратора:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("admin:"))
async def admin_actions(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
    account_pool: PyrogramAccountPool,
) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    raw_data = callback.data or ""
    parts = raw_data.split(":")
    if len(parts) < 2:
        raise SkipHandler
    action = parts[1]
    extra = parts[2:]
    if action == "home":
        paused = await db.is_paused()
        keyboard = build_admin_keyboard(paused)
        await callback.message.edit_text("Панель администратора:", reply_markup=keyboard)
        await callback.answer()
        return

    if action == "stats":
        stats = await db.fetch_enhanced_statistics()
        text = format_enhanced_statistics(stats)
        keyboard = build_stats_keyboard(stats["top_targets"])
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
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

    if action == "accounts":
        if not extra:
            text = await format_account_list(db)
            keyboard = build_account_keyboard()
            await callback.message.answer(text, reply_markup=keyboard)
            await callback.answer()
            return
        sub_action = extra[0]
        if sub_action == "api":
            prompt = await callback.message.answer("Введите API ID и API Hash через пробел")
            pending_api[user.id] = PendingApiConfig(stage="await_credentials", prompt_message_id=prompt.message_id)
            await callback.answer("Ожидаю данные")
            return
        if sub_action == "add":
            api_id = await db.get_setting("pyrogram_api_id")
            api_hash = await db.get_setting("pyrogram_api_hash")
            if not api_id or not api_hash:
                await callback.answer("Сначала настройте API ID/Hash через меню", show_alert=True)
                return

            prompt = await callback.message.answer("Отправьте номер телефона в формате +71234567890")
            pending_accounts[user.id] = PendingAccount(stage="await_phone", prompt_message_id=prompt.message_id)
            await callback.answer("Ожидаю номер")
            return
        if sub_action == "list":
            text = await format_account_list(db)
            keyboard = build_account_keyboard()
            await callback.message.answer(text, reply_markup=keyboard)
            await callback.answer()
            return
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


@router.callback_query(F.data == "admin:stats:refresh")
async def refresh_stats(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    stats = await db.fetch_enhanced_statistics()
    text = format_enhanced_statistics(stats)
    keyboard = build_stats_keyboard(stats["top_targets"])
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("admin:stats:target:"))
async def show_stats_target(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    user = callback.from_user
    if not user or not is_admin(user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    token = parts[3]
    target = stats_target_cache.get(token)
    if not target:
        await callback.answer("Данные устарели. Нажмите «Обновить».", show_alert=True)
        return
    summary = await db.fetch_summary(target)
    text = format_summary(summary)
    keyboard = build_detail_keyboard(summary.target, summary.chat_id)
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    await callback.answer("Готово")


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
async def handle_admin_inputs(
    message: Message,
    settings: Settings,
    db: Database,
    bot: Bot,
    account_pool: PyrogramAccountPool,
) -> None:
    if not message.from_user or not is_admin(message.from_user.id, settings):
        raise SkipHandler
    user_id = message.from_user.id

    api_state = pending_api.get(user_id)
    if api_state and api_state.stage == "await_credentials":
        tokens = shlex.split(message.text or "")
        if len(tokens) < 2:
            await message.reply("Please send API ID and API Hash separated by space.")
            return
        try:
            api_id = int(tokens[0])
        except ValueError:
            await message.reply("API ID must be a number.")
            return
        api_hash = tokens[1]
        await db.set_setting("pyrogram_api_id", str(api_id))
        await db.set_setting("pyrogram_api_hash", api_hash)
        pending_api.pop(user_id, None)
        await account_pool.configure(api_id, api_hash)
        await message.reply("API credentials saved.")
        return

    account_state = pending_accounts.get(user_id)
    if account_state:
        if account_state.stage == "await_phone":
            phone = (message.text or "").strip()
            if not phone:
                await message.reply("Please send a phone number in international format, e.g. +1234567890.")
                return
            api_id_raw = await db.get_setting("pyrogram_api_id")
            api_hash = await db.get_setting("pyrogram_api_hash")
            if not api_id_raw or not api_hash:
                await message.reply("Configure API ID / Hash first.")
                await _reset_pending_account(user_id)
                return
            try:
                api_id = int(api_id_raw)
            except ValueError:
                await message.reply("Stored API ID is invalid. Configure it again.")
                await _reset_pending_account(user_id)
                return
            clean_phone = "".join(ch for ch in phone if ch.isdigit())
            if not clean_phone:
                await message.reply("Phone number must contain digits.")
                return
            session_dir = Path("data") / "pyrogram_sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_name = f"account_{clean_phone}_{int(time.time())}"
            client = Client(
                name=session_name,
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(session_dir.resolve()),
                no_updates=True,
            )
            try:
                await client.connect()
                sent = await client.send_code(phone)
            except errors.FloodWait as exc:
                await message.reply(f"Too many attempts. Try again in {exc.value} seconds.")
                await client.disconnect()
                await _reset_pending_account(user_id)
                return
            except errors.PhoneNumberInvalid:
                await message.reply("Telegram rejected this phone number.")
                await client.disconnect()
                await _reset_pending_account(user_id)
                return
            except Exception:
                await message.reply("Failed to send the confirmation code. Try again later.")
                await client.disconnect()
                await _reset_pending_account(user_id)
                return
            account_state.client = client
            account_state.phone_number = phone
            account_state.phone_code_hash = sent.phone_code_hash
            account_state.session_name = session_name
            account_state.stage = "await_code"
            await message.reply("Enter the confirmation code from Telegram.")
            return
        if account_state.stage == "await_code":
            code = (message.text or "").replace(" ", "")
            if not code:
                await message.reply("Please enter the code that Telegram sent.")
                return
            client = account_state.client
            if client is None:
                await message.reply("Session lost. Start over.")
                await _reset_pending_account(user_id)
                return
            try:
                await client.sign_in(
                    account_state.phone_number,
                    code,
                    phone_code_hash=account_state.phone_code_hash,
                )
            except errors.FloodWait as exc:
                await message.reply(f"Too many attempts. Try again in {exc.value} seconds.")
                return
            except errors.SessionPasswordNeeded:
                account_state.stage = "await_password"
                await message.reply("This account has a password. Send the password now.")
                return
            except errors.PhoneCodeInvalid:
                await message.reply("Invalid code. Try again.")
                return
            except Exception:
                await message.reply("Sign-in failed. Try again later.")
                await _reset_pending_account(user_id)
                return
            await client.disconnect()
            session_name = account_state.session_name or f"account_{int(time.time())}"
            phone_number = account_state.phone_number
            pending_accounts.pop(user_id, None)
            await db.add_pyrogram_account(session_name, phone_number)
            await account_pool.refresh()
            await message.reply("Account added.")
            return
        if account_state.stage == "await_password":
            password = message.text or ""
            if not password:
                await message.reply("Please provide the two-factor password.")
                return
            client = account_state.client
            if client is None:
                await message.reply("Session lost. Start over.")
                await _reset_pending_account(user_id)
                return
            try:
                await client.check_password(password)
            except errors.PasswordHashInvalid:
                await message.reply("Incorrect password. Try again.")
                return
            except Exception:
                await message.reply("Failed to confirm password.")
                await _reset_pending_account(user_id)
                return
            await client.disconnect()
            session_name = account_state.session_name or f"account_{int(time.time())}"
            phone_number = account_state.phone_number
            pending_accounts.pop(user_id, None)
            await db.add_pyrogram_account(session_name, phone_number)
            await account_pool.refresh()
            await message.reply("Account added.")
            return
        return

    rep_state = pending_reputation.get(user_id)
    if rep_state and rep_state.stage == "await_data":
        args = shlex.split(message.text or "")
        if len(args) < 3:
            await message.reply("Usage: username +10 -3 [chat_id]")
            return
        target = args[0].lstrip("@")
        try:
            positive = int(args[1])
            negative = int(args[2])
        except ValueError:
            await message.reply("Adjustments must be numbers.")
            return
        chat_id = int(args[3]) if len(args) > 3 and args[3].lstrip("-+").isdigit() else None
        note = "Manual adjustment via admin panel"
        await db.add_manual_adjustment(target, chat_id, positive, negative, note, user_id)
        pending_reputation.pop(user_id, None)
        await message.reply("Adjustment saved.")
        return

    broadcast_state = pending_broadcast.get(user_id)
    if broadcast_state:
        if broadcast_state.stage == "await_content":
            broadcast_state.content_chat_id = message.chat.id
            broadcast_state.content_message_id = message.message_id
            broadcast_state.stage = "await_button_choice"
            await message.reply("Add a button to the broadcast?", reply_markup=build_broadcast_button_choice())
            return
        if broadcast_state.stage == "await_button_text":
            if not message.text:
                await message.reply("Send the button caption.")
                return
            broadcast_state.button_text = message.text
            broadcast_state.stage = "await_button_url"
            prompt = await message.reply("Send the button URL.")
            broadcast_state.prompt_message_id = prompt.message_id
            return
        if broadcast_state.stage == "await_button_url":
            if not message.text:
                await message.reply("Send the button URL.")
                return
            broadcast_state.button_url = message.text
            broadcast_state.stage = "await_button_choice"
            await perform_broadcast(message, bot, db, user_id, broadcast_state)
            return
        return

    raise SkipHandler
