import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import drive
from bot.config import load_settings
from bot.handlers import build_router
from bot.llm import LLM
from bot.storage import Storage
from bot.throttle import ThrottleMiddleware


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    storage = Storage(settings.db_path)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    llm = LLM(settings.groq_api_key, settings.groq_model, settings.groq_fallback_model, settings.timezone)
    dp = Dispatcher(settings=settings, storage_db=storage, llm=llm)
    throttle = ThrottleMiddleware(settings.throttle_seconds)
    dp.message.middleware(throttle)
    dp.callback_query.middleware(throttle)
    dp.include_router(build_router())

    try:
        await drive.sync_folder(storage, settings.drive_folder_id)
    except Exception:
        logging.exception("Перша синхронізація з Google Диском не вдалася")
    sync_task = asyncio.create_task(
        drive.sync_forever(storage, settings.drive_folder_id, settings.drive_sync_minutes)
    )

    try:
        await dp.start_polling(bot)
    finally:
        sync_task.cancel()
        storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
