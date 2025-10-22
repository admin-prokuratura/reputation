from __future__ import annotations

import asyncio

from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from .config import Settings
from .database import Database
from .handlers import admin, basic, callbacks, reputation
from .logging import setup_logging
from .services.account_pool import PyrogramAccountPool
from .services.reputation_fetcher import ReputationFetcher


async def main() -> None:
    settings = Settings.load()
    setup_logging(settings.log_level, settings.log_file)
    bot = Bot(settings.token, parse_mode=ParseMode.HTML)
    db = Database(settings.database_path)
    await db.connect()
    if settings.paused:
        await db.toggle_pause(True)

    session_dir = Path("data") / "pyrogram_sessions"
    account_pool = PyrogramAccountPool(db, session_dir)
    api_id_raw = await db.get_setting("pyrogram_api_id")
    api_hash = await db.get_setting("pyrogram_api_hash")
    api_id = int(api_id_raw) if api_id_raw else None
    await account_pool.configure(api_id, api_hash)

    fetcher = ReputationFetcher(db, account_pool)

    dp = Dispatcher()
    dp["settings"] = settings
    dp["db"] = db
    dp["account_pool"] = account_pool
    dp["reputation_fetcher"] = fetcher

    dp.include_router(basic.router)
    dp.include_router(reputation.router)
    dp.include_router(callbacks.router)
    dp.include_router(admin.router)

    try:
        await dp.start_polling(bot)
    finally:
        await account_pool.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
