from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN, LOCAL_API_URL

#local_server = TelegramAPIServer.from_base(LOCAL_API_URL)
session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_API_URL))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()