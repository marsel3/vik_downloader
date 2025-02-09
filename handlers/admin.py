from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards import get_admin_keyboard, get_cancel_keyboard
from database import get_admin_list, get_users_stats, get_all_users
import asyncio

admin_router = Router()

class AdminFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in await get_admin_list()

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())

async def send_admin_panel(message: Message):
    stats = await get_users_stats()
    
    stats_text = (
        "📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"📈 Новых за день: {stats['daily']}\n"
        f"📊 Новых за неделю: {stats['weekly']}\n"
        f"📋 Новых за месяц: {stats['monthly']}"
    )
    
    await message.answer(
        stats_text,
        reply_markup=get_admin_keyboard()
    )

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    await send_admin_panel(message)

@admin_router.callback_query(F.data == "refresh_stats")
async def refresh_stats(callback: CallbackQuery):
    stats = await get_users_stats()
    
    stats_text = (
        "📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"📈 Новых за день: {stats['daily']}\n"
        f"📊 Новых за неделю: {stats['weekly']}\n"
        f"📋 Новых за месяц: {stats['monthly']}"
    )
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=get_admin_keyboard()
    )

@admin_router.callback_query(F.data == "broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📤 Отправьте сообщение для рассылки.\n"
        "Поддерживаются форматы:\n"
        "- Текст\n"
        "- Фото с текстом\n"
        "- Фото без текста\n\n"
        "Текст будет сохранен с HTML форматированием.",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BroadcastStates.waiting_for_content)

@admin_router.message(BroadcastStates.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext):
    await state.clear()  # Сразу очищаем состояние
    status_message = await message.answer("⏳ Начинаю рассылку...")
    
    users = await get_all_users()
    success_count = 0
    error_count = 0
    
    for user_id in users:
        try:
            if message.photo:
                if message.caption:
                    await message.bot.send_photo(
                        user_id,
                        message.photo[-1].file_id,
                        caption=message.html_text,
                        parse_mode="HTML"
                    )
                else:
                    await message.bot.send_photo(
                        user_id,
                        message.photo[-1].file_id
                    )
            else:
                await message.bot.send_message(
                    user_id,
                    message.html_text,
                    parse_mode="HTML"
                )
            success_count += 1
            await asyncio.sleep(0.05)
            
        except Exception as e:
            error_count += 1
            continue
    
    # Отправляем результат и открываем админ-панель
    await status_message.edit_text(
        f"✅ Рассылка завершена\n\n"
        f"📨 Успешно отправлено: {success_count}\n"
        f"❌ Ошибок: {error_count}"
    )
    await send_admin_panel(message)

@admin_router.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()  # Удаляем сообщение с кнопкой отмены
    await send_admin_panel(callback.message)