import os
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
import asyncio
import tempfile
from datetime import datetime, timedelta
from collections import defaultdict
import yt_dlp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
from config import tik_tok_proxy
from database import (
    check_user_exists,
    add_user,
    get_video,
    add_video,
    get_file,
    add_file,
    add_download,
    get_video_by_id
)
from keyboards import check_subscription, get_download_keyboard, get_subscribe_keyboard
from download_service import downloader, VideoDownloadError


SUPPORTED_PLATFORMS = {
    'vk.com/video': 'vk',
    'vk.com/clip': 'vk', 
    'youtube.com': 'youtube',
    'youtu.be': 'youtube',
    'instagram.com': 'instagram',
    'tiktok.com': 'tiktok'
}

MAX_RETRY_ATTEMPTS = 3
TEMP_FILE_PREFIX = "video_download_"

user_router = Router()


class VideoDownloadError(Exception):
    """Пользовательская ошибка для проблем с загрузкой видео"""
    pass


@user_router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery) -> None:
    """Обработка проверки подписки"""
    is_subscribed = await check_subscription(callback.bot, callback.from_user.id)
    
    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            "👋 Отправь мне ссылку на видео из YouTube, Instagram, TikTok или VK, "
            "и я помогу тебе его скачать."
        )
    else:
        await callback.answer(
            "❌ Вы все еще не подписались на канал",
            show_alert=True
        )
        
        
class AntiSpam:
    """Система защиты от спама"""
    def __init__(self):
        # История запросов пользователей: user_id -> [timestamp1, timestamp2, ...]
        self.user_requests = defaultdict(list)
        self.max_requests = 30  # максимум запросов в окне
        self.time_window = 60  # окно в секундах
        self.block_duration = 300  # длительность блокировки в секундах
        self.blocked_users = {}  # user_id -> время окончания блокировки

    def is_blocked(self, user_id: int) -> Tuple[bool, Optional[int]]:
        """Проверка блокировки пользователя"""
        if user_id in self.blocked_users:
            block_end_time = self.blocked_users[user_id]
            if datetime.now() < block_end_time:
                remaining = int((block_end_time - datetime.now()).total_seconds())
                return True, remaining
            else:
                del self.blocked_users[user_id]
        return False, None

    def add_request(self, user_id: int) -> bool:
        """Добавление нового запроса и проверка лимитов"""
        now = datetime.now()
        user_times = self.user_requests[user_id]
        
        # Очищаем старые запросы
        user_times = [time for time in user_times 
                     if now - time < timedelta(seconds=self.time_window)]
        self.user_requests[user_id] = user_times

        # Проверяем количество запросов
        if len(user_times) >= self.max_requests:
            self.blocked_users[user_id] = now + timedelta(seconds=self.block_duration)
            return False

        user_times.append(now)
        return True


# Создаем экземпляр анти-спам системы
anti_spam = AntiSpam()


async def safe_delete_message(message: Message) -> None:
    """Безопасное удаление сообщения с обработкой ошибок"""
    try:
        await message.delete()
    except TelegramAPIError:
        return


async def get_error_message(error: Exception) -> str:
    """Получение понятного пользователю сообщения об ошибке"""
    error_text = str(error).lower()
    
    if "404" in error_text:
        return "❌ Видео не найдено. Возможно, оно было удалено или ссылка неверна."
    elif "deleted" in error_text:
        return "❌ Это видео было удалено и больше недоступно."
    elif "private" in error_text:
        return "❌ Это приватное видео. У бота нет доступа к нему."
    elif "copyright" in error_text:
        return "❌ Видео недоступно из-за нарушения авторских прав."
    elif "age" in error_text:
        return "❌ Видео имеет возрастные ограничения. Бот не может его загрузить."
    elif "unavailable" in error_text:
        return "❌ Видео недоступно для скачивания."
    elif "too large" in error_text:
        return "❌ Файл слишком большой для загрузки в Telegram (максимум 50MB)."
    else:
        return f"❌ Произошла ошибка при обработке видео"


async def handle_rate_limit(message: Message, remaining_time: int) -> None:
    """Обработка превышения лимита запросов"""
    minutes = remaining_time // 60
    seconds = remaining_time % 60
    await message.answer(
        f"⚠️ Слишком много запросов! Пожалуйста, подождите {minutes}:{seconds:02d} "
        "прежде чем отправлять новые ссылки."
    )



async def validate_and_prepare_url(message: Message) -> Optional[Tuple[str, str]]:
    """Проверка и подготовка URL"""
    if not message.text:
        return None

    # Очищаем URL от эмодзи и лишних пробелов
    url = ''.join(c for c in message.text if c.isprintable() and not c.isspace())
    
    # Проверяем есть ли в тексте URL
    import re
    url_pattern = r'https?://[^\s<>"\']+'
    match = re.search(url_pattern, url)
    if not match:
        return None
        
    url = match.group(0)
    platform = get_platform(url)
    
    if not platform:
        platforms = ", ".join(SUPPORTED_PLATFORMS.keys())
        await message.answer(f"❌ Неподдерживаемая платформа. Поддерживаются: {platforms}")
        return None

    return url, platform


def get_platform(url: str) -> Optional[str]:
    """Определение платформы из URL"""
    for domain, platform in SUPPORTED_PLATFORMS.items():
        if domain in url.lower():
            return platform
    return None


async def download_audio(url: str, output_path: str) -> bool:
    """Загрузка аудио из видео"""
    try:
        # Если это Instagram, используем специальный обработчик
        if 'instagram.com' in url.lower():
            from download_service import downloader
            instagram_downloader = downloader._downloaders['instagram']
            return await instagram_downloader.download_audio(url, output_path)
            
        is_tiktok = 'tiktok.com' in url.lower()
        
        proxy_settings = {
            'proxy': tik_tok_proxy if is_tiktok else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }

        # Общие настройки для отключения прогресса
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'progress_hooks': [],
            'logger': None,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'no_check_certificate': True,
            'nocheckcertificate': True
        }

        if is_tiktok:
            ydl_opts.update(proxy_settings)
            ydl_opts.update({
                'socket_timeout': 30,
                'retries': 5
            })
        
        # Чистим URL от эмодзи и лишних символов
        clean_url = ''.join(c for c in url if c.isprintable() and not c.isspace())
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([clean_url])
            
            # Проверяем наличие файла с суффиксом .mp3
            mp3_path = f"{output_path}.mp3"
            if os.path.exists(mp3_path):
                os.rename(mp3_path, output_path)
                return True
            
            # Проверяем оригинальный путь
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
                
            return False
            
    except Exception as e:
        print(f"Audio download error: {str(e)}")  # Для отладки
        return False
     
       
def format_duration(duration: int) -> str:
    """Форматирование длительности в читаемый вид"""
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def get_initial_caption(info: Dict[str, Any]) -> str:
    """Генерация начального описания с информацией о видео"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    
    # Безопасное преобразование duration
    try:
        duration_str = info.get('duration', '0')
        if isinstance(duration_str, str):
            # Удаляем все нечисловые символы кроме точки и преобразуем в секунды
            duration_str = ''.join(c for c in duration_str if c.isdigit() or c == '.')
            duration = round(float(duration_str))  # Округляем до ближайшего целого
        elif isinstance(duration_str, (int, float)):
            duration = round(float(duration_str))
        else:
            duration = 0
    except (ValueError, TypeError):
        duration = 0
    
    return (
        f"<code>🍿 {title}</code>\n"
        f"🔗 {source_url}\n"
        f"👤 Автор: #{author.replace(' ', '_')}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
        f"⏱ Продолжительность: {format_duration(duration)}"
    )
    

def get_download_caption(info: Dict[str, Any], file_type: str, quality: Optional[str] = None) -> str:
    """Генерация описания для загруженного видео/аудио"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    
    try:
        duration_str = info.get('duration', '0')
        if isinstance(duration_str, str):
            duration_str = ''.join(c for c in duration_str if c.isdigit() or c == '.')
            duration = round(float(duration_str))
        elif isinstance(duration_str, (int, float)):
            duration = round(float(duration_str))
        else:
            duration = 0
    except (ValueError, TypeError):
        duration = 0

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
        f"⏱ Продолжительность: {format_duration(duration)}"
        f"{quality_str}"
    )
    
async def send_large_video(message: Message, video_path: str, caption: str) -> Optional[Message]:
    """Отправка большого видео файла с повторными попытками"""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            with open(video_path, 'rb') as video:
                return await message.bot.send_video(
                    chat_id=message.chat.id,
                    video=FSInputFile(video_path),
                    caption=caption,
                    parse_mode="HTML"
                )
        except Exception as e:
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                try:
                    with open(video_path, 'rb') as video:
                        buf = BufferedInputFile(
                            video.read(),
                            filename="video.mp4"
                        )
                        return await message.bot.send_video(
                            chat_id=message.chat.id,
                            video=buf,
                            caption=caption,
                            parse_mode="HTML"
                        )
                except Exception as e:
                    raise VideoDownloadError(f"Не удалось отправить видео после всех попыток: {str(e)}")
            else:
                await asyncio.sleep(1)
    return None


async def download_video(url: str, output_path: str, format_id: str, is_tiktok: bool = False,
                        is_youtube: bool = False, is_instagram: bool = False) -> None:
    """Загрузка видео с учетом особенностей платформы"""
    try:
        if is_instagram:
            from download_service import downloader
            instagram_downloader = downloader._downloaders['instagram']
            await instagram_downloader.download_video(url, output_path, format_id)
            return

        # Базовые настройки прокси и заголовков
        proxy_settings = {
            'proxy': instagram_proxy if is_instagram else tik_tok_proxy,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive'
            }
        }

        # Общие настройки для отключения прогресса
        common_opts = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'progress_hooks': [],
            'logger': None,
            'no_check_certificate': True,
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5
        }

        # Чистим URL от эмодзи и лишних символов
        clean_url = ''.join(c for c in url if c.isprintable() and not c.isspace())

        if is_tiktok:
            ydl_opts = {
                **common_opts,
                'format': 'best',
                'outtmpl': output_path,
                'merge_output_format': 'mp4',
                **proxy_settings,
                'http_headers': {
                    **proxy_settings['http_headers'],
                    'Origin': 'https://www.tiktok.com',
                    'Referer': 'https://www.tiktok.com/'
                }
            }
        elif is_youtube:
            ydl_opts = {
                **common_opts,
                'format': f'bestvideo[height<={format_id}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<={format_id}][ext=mp4]',
                'outtmpl': output_path,
                'merge_output_format': 'mp4',
                'postprocessor_args': [
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-strict', 'experimental',
                    '-movflags', '+faststart'
                ],
                'fragment_retries': 50,
                'retries': 50,
                'socket_timeout': 120,
                'cookiefile': 'cookies.txt',
                'http_chunk_size': 10485760
            }
        else:
            ydl_opts = {
                **common_opts,
                'format': f'best[height<={format_id}]',
                'outtmpl': output_path
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: ydl.download([clean_url])
            )

    except Exception as e:
        raise VideoDownloadError(f"Ошибка при загрузке видео: {str(e)}")
    
    
@user_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Обработка команды /start"""
    try:
        if not await check_user_exists(message.from_user.id):
            await add_user(message.from_user.id, message.from_user.username)
        await message.answer(
            "👋 Привет! Отправь мне ссылку на видео из YouTube, Instagram, TikTok или VK, "
            "и я помогу тебе его скачать."
        )
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при запуске бота: {str(e)}")


@user_router.message(
    lambda message: message.text and any(
        platform in message.text.lower() 
        for platform in SUPPORTED_PLATFORMS.keys()
    )
)
async def process_video_url(message: Message) -> None:
    """Обработка сообщения с URL видео"""
    is_subscribed = await check_subscription(message.bot, message.from_user.id)
    if not is_subscribed:
        await message.answer(
            "⚠️ Для использования бота необходимо подписаться на наш канал.",
            reply_markup=get_subscribe_keyboard()
        )
        return
    
    user_id = message.from_user.id
    is_blocked, remaining_time = anti_spam.is_blocked(user_id)
    if is_blocked:
        await handle_rate_limit(message, remaining_time)
        return

    if not anti_spam.add_request(user_id):
        await handle_rate_limit(message, anti_spam.block_duration)
        return

    processing_msg = None
    try:
        # Валидация URL
        url_data = await validate_and_prepare_url(message)
        if not url_data:
            return
        
        url, platform = url_data
        
        processing_msg = await message.answer("⏳ Получаю информацию о видео...")
        
        # Получение информации о видео
        video_info = await get_video(url)
        
        info = await downloader.get_video_info(url)
        
        if not info:
            if processing_msg:
                await processing_msg.edit_text("❌ Не удалось получить информацию о видео. Проверьте ссылку.")
            return

        # Подготовка данных
        try:
            video_data = {
                'source_url': url,  
                'title': info.get('title', 'Без названия'),
                'author': info.get('author') or 'Unknown',  # Используем 'Unknown' если author is None
                'duration': info.get('duration', '0'),
                'thumbnail': str(info.get('thumbnail', '')),
                'platform': platform
            }

            if not video_info:
                video_id = await add_video(
                    url=url,
                    title=video_data['title'],
                    author=video_data['author'],
                    duration=video_data['duration'],
                    thumbnail=video_data['thumbnail']
                )
            else:
                video_id = video_info['video_id']

            if processing_msg:
                await safe_delete_message(processing_msg)

            await send_video_preview(message, video_data, video_id, info)
                
        except Exception as e:
            raise
            
    except VideoDownloadError as e:
        error_message = str(e)
        if processing_msg:
            try:
                await processing_msg.edit_text(error_message)
            except TelegramAPIError:
                await message.answer(error_message)
    except Exception as e:
        error_message = "❌ Произошла ошибка при обработке видео"
        if processing_msg:
            try:
                await processing_msg.edit_text(error_message)
            except TelegramAPIError:
                await message.answer(error_message)
                
                
async def send_video_preview(message: Message, video_data: Dict, video_id: int, info: Dict) -> None:
    """Отправка превью видео"""
    try:
        caption = get_initial_caption(video_data)
        
        keyboard = await get_download_keyboard(video_id, info)

        try:
            # Проверяем, является ли thumbnail URL строкой
            thumbnail = str(video_data['thumbnail']) if video_data.get('thumbnail') else None
            
            if thumbnail:
                await message.answer_photo(
                    photo=thumbnail,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            else:
                raise ValueError("No thumbnail URL available")
        except Exception as photo_error:
            await message.answer(
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    except Exception as e:
        raise
    
    
@user_router.callback_query(F.data.startswith("dl_"))
async def process_download(callback: CallbackQuery) -> None:
    """Обработка нажатий на кнопки загрузки"""
    await callback.answer()
    
    # Проверка на спам
    user_id = callback.from_user.id
    is_blocked, remaining_time = anti_spam.is_blocked(user_id)
    if is_blocked:
        await handle_rate_limit(callback.message, remaining_time)
        return

    if not anti_spam.add_request(user_id):
        await handle_rate_limit(callback.message, anti_spam.block_duration)
        return
    
    try:
        # Валидация данных
        download_data = await validate_download_data(callback.data)
        if not download_data:
            await callback.message.answer("❌ Неверный формат данных кнопки")
            return
            
        video_id, format_id, file_type = download_data
        
        # Получение информации о видео
        file_info = await get_file(video_id, format_id, file_type)
        db_video = await get_video_by_id(video_id)
        
        if not db_video:
            await callback.message.answer("❌ Видео не найдено в базе данных")
            return

        video_data = {
            'title': db_video['title'],
            'author': db_video['author'],
            'duration': db_video['duration'],
            'source_url': db_video['source_url'],
            'thumbnail': db_video['thumbnail_url']
        }

        # Проверяем кэш
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
                await safe_delete_message(callback.message)
                return
            except TelegramAPIError:
                pass

        # Загрузка нового файла
        await process_new_download(callback, video_data, video_id, format_id, file_type)

    except VideoDownloadError as e:
        await handle_download_error(callback, str(e), video_id)
    except Exception as e:
        await handle_download_error(callback, "Произошла ошибка при скачивании", video_id)


async def validate_download_data(callback_data: str) -> Optional[Tuple[int, str, str]]:
    """Валидация данных callback"""
    try:
        _, video_id, format_id, file_type = callback_data.split("_")
        return int(video_id), format_id, file_type
    except ValueError:
        return None


async def process_new_download(callback: CallbackQuery, video_data: Dict, 
                             video_id: int, format_id: str, file_type: str) -> None:
    """Обработка новой загрузки"""
    with tempfile.TemporaryDirectory(prefix=TEMP_FILE_PREFIX) as temp_dir:
        try:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n📥⌛️ Скачиваю файл... ⌛️📥",
                parse_mode="HTML",
                reply_markup=None
            )

            file_name = f"video_{int(datetime.now().timestamp())}"
            temp_path = Path(temp_dir) / file_name

            is_tiktok = 'tiktok.com' in video_data['source_url']
            is_youtube = 'youtube.com' in video_data['source_url'] or 'youtu.be' in video_data['source_url']
            is_instagram = 'instagram.com' in video_data['source_url']

            if file_type == 'video':
                temp_path = temp_path.with_suffix('.mp4')
                await download_video(
                    video_data['source_url'],
                    str(temp_path),
                    format_id,
                    is_tiktok,
                    is_youtube,
                    is_instagram
                )
            else:
                temp_path = temp_path.with_suffix('.mp3')
                success = await download_audio(video_data['source_url'], str(temp_path))
                if not success:
                    raise VideoDownloadError("Не удалось загрузить аудио файл")

            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise VideoDownloadError("Файл не был загружен корректно")

            # Отправка файла
            caption = get_download_caption(video_data, file_type, format_id)
            msg = await send_file(callback.message, temp_path, caption, file_type)
            
            # Сохранение в базу
            await save_file_info(msg, video_id, file_type, format_id, temp_path, callback.from_user.id)
            await safe_delete_message(callback.message)

        except Exception as e:
            raise VideoDownloadError(f"Ошибка при загрузке: {str(e)}")


async def send_file(message: Message, file_path: Path, caption: str, 
                   file_type: str) -> Message:
    """Отправка файла в Telegram"""
    if file_type == 'video':
        return await send_large_video(message, str(file_path), caption)
    else:
        return await message.answer_audio(
            audio=FSInputFile(str(file_path)),
            caption=caption,
            parse_mode="HTML"
        )


async def save_file_info(message: Message, video_id: int, file_type: str, 
                        format_id: str, file_path: Path, user_id: int) -> None:
    """Сохранение информации о файле в базу"""
    file_id = message.video.file_id if file_type == 'video' else message.audio.file_id
    file_size = file_path.stat().st_size
    
    new_file_id = await add_file(
        video_id=video_id,
        telegram_file_id=file_id,
        file_type=file_type,
        size=file_size,
        quality=format_id
    )

    await add_download(
        user_id=user_id,
        video_id=video_id,
        file_id=new_file_id
    )


async def handle_download_error(callback: CallbackQuery, error_message: str, video_id: int) -> None:
    """Обработка ошибок при загрузке"""
    try:
        info = await downloader.get_video_info(callback.message.caption.split('\n')[1].strip())
        keyboard = await get_download_keyboard(video_id, info)
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n❌ {error_message}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n❌ {error_message}",
            parse_mode="HTML"
        )


@user_router.callback_query(F.data == "size_limit")
async def process_size_limit(callback: CallbackQuery) -> None:
    """Обработка превышения лимита размера файла"""
    await callback.answer(
        "❌ Файл слишком большой (>50MB). Выберите меньшее качество или аудио версию.",
        show_alert=True
    )


@user_router.message()
async def process_unknown_message(message: Message) -> None:
    """Обработка неизвестных сообщений"""
    await message.answer(
        "Отправьте мне ссылку на видео из YouTube, Instagram, TikTok или VK, "
        "и я помогу вам его скачать."
    )