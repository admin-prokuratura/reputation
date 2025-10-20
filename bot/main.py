from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Settings
from .database import Database
from .handlers import admin, basic, callbacks, reputation


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    settings = Settings.load()
    bot = Bot(settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db = Database(settings.database_path)
    await db.connect()
    if settings.paused:
        await db.toggle_pause(True)

    dp = Dispatcher()
    dp["settings"] = settings
    dp["db"] = db

    dp.include_router(basic.router)
    dp.include_router(reputation.router)
    dp.include_router(callbacks.router)
    dp.include_router(admin.router)

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
