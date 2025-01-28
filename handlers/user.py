from typing import Optional, Dict, Any, Union
from pathlib import Path
import asyncio
import tempfile
from datetime import datetime
import yt_dlp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError
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
from keyboards import get_download_keyboard
from download_service import downloader


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
    """Custom exception for video download errors"""
    pass


async def safe_delete_message(message: Message) -> None:
    """Safely delete a message with error handling"""
    try:
        await message.delete()
    except TelegramAPIError:
        pass


async def download_audio(url: str, output_path: str) -> bool:
    """Download audio from video URL"""
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
    except Exception:
        return False


def format_duration(duration: int) -> str:
    """Format duration in seconds to human readable string"""
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def get_initial_caption(info: Dict[str, Any]) -> str:
    """Generate initial message caption with video information"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    duration = int(info.get('duration', '0'))
    
    return (
        f"<code>🍿 {title}</code>\n"
        f"🔗 {source_url}\n"
        f"👤 Автор: #{author.replace(' ', '_')}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
        f"⏱ Продолжительность: {format_duration(duration)}"
    )


def get_download_caption(info: Dict[str, Any], file_type: str, quality: Optional[str] = None) -> str:
    """Generate caption for downloaded video/audio"""
    title = info.get('title', 'Без названия').replace('&quot;', '"')
    author = info.get('author', 'Unknown').replace('&quot;', '"')
    source_url = info.get('source_url', '')
    duration = int(info.get('duration', '0'))

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


def get_platform(url: str) -> Optional[str]:
    """Determine platform from URL"""
    for domain, platform in SUPPORTED_PLATFORMS.items():
        if domain in url.lower():
            return platform
    return None


@user_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command"""
    try:
        if not await check_user_exists(message.from_user.id):
            await add_user(message.from_user.id, message.from_user.username)
        await message.answer("👋 Привет! Отправь мне ссылку на видео, и я помогу тебе его скачать.")
    except Exception:
        await message.answer("❌ Произошла ошибка при запуске бота")


@user_router.message(
    lambda message: message.text and any(
        platform in message.text.lower() 
        for platform in SUPPORTED_PLATFORMS.keys()
    )
)
async def process_video_url(message: Message) -> None:
    """Process video URL message"""
    processing_msg = None
    try:
        url = message.text.strip()
        platform = get_platform(url)
        
        if not platform:
            await message.answer("❌ Неподдерживаемая платформа")
            return

        processing_msg = await message.answer("⏳ Получаю информацию о видео...")
        
        video_info = await get_video(url)
        info = await downloader.get_video_info(url)
        
        if not info:
            if processing_msg:
                await processing_msg.edit_text("❌ Не удалось получить информацию о видео")
            return

        video_data = {
            'source_url': url,
            'title': info.get('title', 'Без названия'),
            'author': info.get('author', 'Unknown'),
            'duration': info.get('duration', '0'),
            'thumbnail': info.get('thumbnail', ''),
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

        caption = get_initial_caption(video_data)
        keyboard = await get_download_keyboard(video_id, info)

        if processing_msg:
            await safe_delete_message(processing_msg)

        try:
            await message.answer_photo(
                photo=video_data['thumbnail'],
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except TelegramAPIError:
            await message.answer(
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
    except Exception:
        error_message = "❌ Произошла ошибка при обработке видео"
        
        if processing_msg:
            try:
                await processing_msg.edit_text(error_message)
            except TelegramAPIError:
                await message.answer(error_message)


async def send_large_video(message: Message, video_path: str, caption: str) -> Optional[Message]:
    """Send large video file with retry logic"""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            with open(video_path, 'rb') as video:
                return await message.bot.send_video(
                    chat_id=message.chat.id,
                    video=FSInputFile(video_path),
                    caption=caption,
                    parse_mode="HTML"
                )
        except Exception:
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
                except Exception:
                    raise VideoDownloadError("Failed to send video after all attempts")
            else:
                await asyncio.sleep(1)
    return None


async def download_video(url: str, output_path: str, format_id: str, is_tiktok: bool = False,
                        is_youtube: bool = False, is_instagram: bool = False) -> None:
    """Download video with platform-specific options"""
    if is_tiktok:
        ydl_opts = {
            'format': 'best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4'
        }
    elif is_youtube:
        ydl_opts = {
            'format': f'bestvideo[height<={format_id}][ext=mp4]+bestaudio[ext=m4a]/best[height<={format_id}][ext=mp4]/best[ext=mp4]',
            'outtmpl': output_path,
            'merge_output_format': 'mp4',
            'fragment_retries': 50,
            'retries': 50,
            'socket_timeout': 120,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',
            'http_chunk_size': 10485760
        }
    elif is_instagram:
        ydl_opts = {
            'format': 'best[ext=mp4]',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }
    else:
        ydl_opts = {
            'format': f'best[height<={format_id}]',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: ydl.download([url])
        )


@user_router.callback_query(F.data.startswith("dl_"))
async def process_download(callback: CallbackQuery) -> None:
    """Handle download button callbacks"""
    await callback.answer()
    
    try:
        _, video_id, format_id, file_type = callback.data.split("_")
        video_id = int(video_id)
    except ValueError:
        return
    
    try:
        file_info = await get_file(video_id, format_id, file_type)
        db_video = await get_video_by_id(video_id)
        
        if not db_video:
            await callback.message.answer("❌ Видео не найдено")
            return

        video_data = {
            'title': db_video['title'],
            'author': db_video['author'],
            'duration': db_video['duration'],
            'source_url': db_video['source_url'],
            'thumbnail': db_video['thumbnail_url']
        }

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

        with tempfile.TemporaryDirectory(prefix=TEMP_FILE_PREFIX) as temp_dir:
            try:
                await callback.message.edit_caption(
                    caption=f"{callback.message.caption}\n\n📥⌛️ Скачиваю из источника ⌛️📥",
                    parse_mode="HTML",
                    reply_markup=None
                )

                file_name = f"video_{int(datetime.now().timestamp())}"
                temp_path = Path(temp_dir) / file_name

                is_tiktok = 'tiktok.com' in db_video['source_url']
                is_youtube = 'youtube.com' in db_video['source_url'] or 'youtu.be' in db_video['source_url']
                is_instagram = 'instagram.com' in db_video['source_url']

                if file_type == 'video':
                    temp_path = temp_path.with_suffix('.mp4')
                    await download_video(
                        db_video['source_url'],
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
                        raise VideoDownloadError("Failed to download audio")

                if not temp_path.exists() or temp_path.stat().st_size == 0:
                    raise VideoDownloadError("File not downloaded correctly")

                caption = get_download_caption(video_data, file_type, format_id)

                if file_type == 'video':
                    msg = await send_large_video(callback.message, str(temp_path), caption)
                    file_id = msg.video.file_id
                else:
                    msg = await callback.message.answer_audio(
                        audio=FSInputFile(str(temp_path)),
                        caption=caption,
                        parse_mode="HTML"
                    )
                    file_id = msg.audio.file_id

                await safe_delete_message(callback.message)

                file_size = temp_path.stat().st_size
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

            except Exception:
                info = await downloader.get_video_info(video_data['source_url'])
                keyboard = await get_download_keyboard(video_id, info)
                await callback.message.edit_caption(
                    caption=f"{callback.message.caption}\n\n❌ Ошибка при скачивании",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

    except Exception:
        pass


@user_router.callback_query(F.data == "size_limit")
async def process_size_limit(callback: CallbackQuery) -> None:
    """Handle size limit exceeded callback"""
    await callback.answer(
        "❌ Файл слишком большой (>50MB). Выберите меньшее качество.",
        show_alert=True
    )


@user_router.message()
async def process_unknown_message(message: Message) -> None:
    """Handle unknown messages"""
    await message.answer("Отправьте мне ссылку на видео, и я помогу вам его скачать.")