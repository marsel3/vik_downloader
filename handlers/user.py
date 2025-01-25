from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.filters import Command
import asyncio
from datetime import datetime
import os
import tempfile
import time
import shutil
import yt_dlp
from database import *
from keyboards import get_download_keyboard, estimate_video_size, format_size
from download_service import downloader

user_router = Router()

async def download_audio(url: str, output_path: str) -> bool:
    """Скачивает аудио из видео"""
    try:
        ydl_opts = {
            'format': 'worstaudio/worst',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'audio_format': 'mp3',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        return True
    except Exception as e:
        print(f"Error in download_audio: {e}")
        return False

def get_initial_caption(info: dict) -> str:
    """Формирует начальное сообщение с информацией о видео"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    
    duration = int(info.get('duration', '0'))
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    if hours > 0:
        duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        duration_str = f"{minutes}:{seconds:02d}"

    return (
        f"<code>🍿 {title}</code>\n"
        f"🔗 {source_url}\n"
        f"👤 Автор: #{author.replace(' ', '_')}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
        f"⏱ Продолжительность: {duration_str}"
    )

def get_download_caption(info: dict, file_type: str, quality: str = None) -> str:
    """Формирует сообщение после скачивания"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    
    duration = int(info.get('duration', '0'))
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    if hours > 0:
        duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        duration_str = f"{minutes}:{seconds:02d}"

    resolutions = {
        "144": "256x144",
        "240": "426x240",
        "360": "640x360",
        "480": "852x480",
        "720": "1280x720",
        "1080": "1920x1080"
    }

    quality_str = ""
    if file_type == "video" and quality:
        quality_str = f"\n📺 Качество: {resolutions.get(quality, '')}"
    elif file_type == "audio":
        quality_str = "\n💿 Тип: Аудио"

    return (
        f"<code>🍿 {title}</code>\n"
        f"🔗 {source_url}\n"
        f"👤 Автор: #{author.replace(' ', '_')}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
        f"⏱ Продолжительность: {duration_str}"
        f"{quality_str}"
    )

@user_router.message(Command("start"))
async def cmd_start(message: Message):
    if not await check_user_exists(message.from_user.id):
        await add_user(message.from_user.id, message.from_user.username)
    await message.answer("👋 Привет! Отправь мне ссылку на видео, и я помогу тебе его скачать.")


@user_router.message(
    lambda message: message.text and any(
        platform in message.text.lower() 
        for platform in [
            'vk.com/video', 
            'vk.com/clip', 
            'youtube.com', 
            'youtu.be',
            'instagram.com',
            'tiktok.com'
        ]
    )
)
async def process_video_url(message: Message):
    processing_msg = None
    try:
        # Определяем платформу
        url = message.text.strip()
        platform = None
        
        if 'vk.com' in url:
            platform = 'vk'
        elif 'youtube.com' in url or 'youtu.be' in url:
            platform = 'youtube'
        elif 'instagram.com' in url:
            platform = 'instagram'
        elif 'tiktok.com' in url:
            platform = 'tiktok'

        processing_msg = await message.answer("⏳ Получаю информацию о видео...")
        
        # Проверяем, есть ли видео в базе
        video_info = await get_video(url)
        
        if not video_info:
            info = await downloader.get_video_info(url)
            if not info:
                if processing_msg:
                    await processing_msg.edit_text("❌ Не удалось получить информацию о видео. Попробуйте позже.")
                return

            # Создаем словарь с данными
            video_data = {
                'source_url': url,
                'title': info.get('title', 'Без названия'),
                'author': info.get('author', 'Unknown'),
                'duration': info.get('duration', '0'),
                'thumbnail': info.get('thumbnail', ''),
                'platform': platform
            }

            video_id = await add_video(
                url=url,
                title=video_data['title'],
                author=video_data['author'],
                duration=video_data['duration'],
                thumbnail=video_data['thumbnail']
            )
        else:
            video_id = video_info['video_id']
            info = await downloader.get_video_info(url)
            if not info:
                if processing_msg:
                    await processing_msg.edit_text("❌ Не удалось получить информацию о видео. Попробуйте позже.")
                return
            
            video_data = {
                'source_url': url,
                'title': info.get('title', 'Без названия'),
                'author': info.get('author', 'Unknown'),
                'duration': info.get('duration', '0'),
                'thumbnail': info.get('thumbnail', ''),
                'platform': platform
            }

        # Формируем сообщение и клавиатуру
        caption = get_initial_caption(video_data)
        keyboard = await get_download_keyboard(video_id, info)

        # Удаляем сообщение о загрузке
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception as e:
                print(f"Error deleting processing message: {e}")

        # Отправляем итоговое сообщение
        try:
            await message.answer_photo(
                photo=video_data['thumbnail'],
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Error sending photo message: {e}")
            await message.answer(
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
    except Exception as e:
        print(f"Error in process_video_url: {e}")
        if processing_msg:
            try:
                await processing_msg.edit_text("❌ Произошла ошибка при обработке видео")
            except Exception as edit_error:
                print(f"Error editing processing message: {edit_error}")
                try:
                    await message.answer("❌ Произошла ошибка при обработке видео")
                except Exception as send_error:
                    print(f"Error sending error message: {send_error}")


@user_router.callback_query(F.data.startswith("dl_"))
async def process_download(callback: CallbackQuery):
    # Сразу отвечаем на callback, чтобы избежать timeout
    await callback.answer()
    
    try:
        _, video_id, format_id, file_type = callback.data.split("_")
        video_id = int(video_id)
    except ValueError:
        return
    
    try:
        # Проверяем кэш
        file_info = await get_file(video_id, format_id, file_type)
        db_video = await get_video_by_id(video_id)
        
        if not db_video:
            await callback.message.answer("❌ Видео не найдено")
            return

        # Создаем словарь с данными о видео
        video_data = {
            'title': db_video['title'],
            'author': db_video['author'],
            'duration': db_video['duration'],
            'source_url': db_video['source_url'],
            'thumbnail': db_video['thumbnail_url']
        }

        # Проверяем предполагаемый размер файла
        estimated_size = estimate_video_size(float(db_video['duration']), format_id)
        if estimated_size > 2000 * 1024 * 1024:  # 2000 MB в байтах
            await callback.message.answer(
                "⚠️ Файл слишком большой (более 2GB). Выберите меньшее качество."
            )
            return

        if file_info:
            try:
                caption = get_download_caption(video_data, file_type, format_id)
                
                if file_type == 'video':
                    msg = await callback.message.answer_video(
                        video=file_info['telegram_file_id'],
                        caption=caption,
                        parse_mode="HTML"
                    )
                else:
                    msg = await callback.message.answer_audio(
                        audio=file_info['telegram_file_id'],
                        caption=caption,
                        parse_mode="HTML"
                    )
                await callback.message.delete()
                return
            except Exception as e:
                print(f"Error sending cached file: {e}")

        # Создаём временную директорию
        temp_dir = tempfile.mkdtemp()
        temp_path = None

        try:
            # Начинаем загрузку
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n📥⌛️ Скачиваю из источника ⌛️📥",
                parse_mode="HTML",
                reply_markup=None
            )

            file_name = f"video_{int(time.time())}"
            temp_path = os.path.join(temp_dir, file_name)

            is_tiktok = 'tiktok.com' in db_video['source_url']
            is_youtube = 'youtube.com' in db_video['source_url'] or 'youtu.be' in db_video['source_url']

            if file_type == 'video':
                temp_path += '.mp4'
                if is_tiktok:
                    ydl_opts = {
                        'format': 'best',
                        'outtmpl': temp_path,
                        'quiet': True,
                        'no_warnings': True,
                    }
            elif is_youtube:
                ydl_opts = {
                    'format': 'best[ext=mp4]',
                    'outtmpl': temp_path,
                    'no_check_certificate': True,
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': 30,
                    'retries': 10,
                    'fragment_retries': 10
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    await asyncio.get_event_loop().run_in_executor(
                        None, 
                        lambda: ydl.download([db_video['source_url']])
                    )
            else:
                temp_path += '.mp3'
                success = await download_audio(video_data['source_url'], temp_path)
                if not success:
                    raise Exception("Failed to download audio")

            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                raise Exception("File not downloaded correctly")

            caption = get_download_caption(video_data, file_type, format_id)

            if file_type == 'video':
                msg = await callback.message.answer_video(
                    video=FSInputFile(temp_path),
                    caption=caption,
                    parse_mode="HTML"
                )
                file_id = msg.video.file_id
            else:
                msg = await callback.message.answer_audio(
                    audio=FSInputFile(temp_path),
                    caption=caption,
                    parse_mode="HTML"
                )
                file_id = msg.audio.file_id

            await callback.message.delete()

            # Сохраняем в базу
            file_size = os.path.getsize(temp_path)
            new_file_id = await add_file(
                video_id=video_id,
                telegram_file_id=file_id,
                file_type=file_type,
                size=file_size,
                quality=format_id
            )

            await add_download(
                user_id=callback.from_user.id,
                video_id=video_id,
                file_id=new_file_id
            )

        except Exception as e:
            print(f"Download error: {e}")
            # Если произошла ошибка, возвращаем клавиатуру
            info = await downloader.get_video_info(video_data['source_url'])
            keyboard = await get_download_keyboard(video_id, info)
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n❌ Ошибка при скачивании",
                parse_mode="HTML",
                reply_markup=keyboard
            )

        finally:
            # Очищаем временные файлы
            try:
                for root, dirs, files in os.walk(temp_dir, topdown=False):
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                        except: pass
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except: pass
                try:
                    if os.path.exists(temp_dir):
                        os.rmdir(temp_dir)
                except: pass
            except Exception as e:
                print(f"Error cleaning temp files: {e}")

    except Exception as e:
        print(f"Error in process_download: {e}")
        

@user_router.message()
async def process_unknown_message(message: Message):
    await message.answer("Отправьте мне ссылку на видео, и я помогу вам его скачать.")