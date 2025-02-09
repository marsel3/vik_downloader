import asyncio
import asyncpg
from aiogram.types import BotCommand

from config import DB_HOST, DB_USER, DB_PASS, DB_NAME, DB_PORT
from handlers.user import user_router
from handlers.admin import admin_router
from loader import bot, dp


async def on_startup() -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
    ])
    
    dp["db"] = await asyncpg.create_pool(
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        host=DB_HOST,
        port=DB_PORT,
        max_size=100
    )


async def on_shutdown() -> None:
    if "db" in dp.workflow_data:
        await dp["db"].close()


async def main() -> None:
    dp.include_routers(admin_router, user_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())