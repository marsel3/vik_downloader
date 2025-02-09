from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_file
from config import CHANNEL_ID, CHANNEL_URL


MAX_FILE_SIZE = 2000 * 1024 * 1024


async def check_subscription(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False


def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться на канал",
                    url=CHANNEL_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Проверить подписку",
                    callback_data="check_subscription"
                )
            ]
        ]
    )
    return keyboard


def estimate_video_size(duration: float, quality: str) -> int:
    BITRATES = {
        '144': 0.2,    # ~0.2 Mbps для VK (было 0.3)
        '240': 0.35,   # ~0.35 Mbps для VK (было 0.5)
        '360': 0.65,   # ~0.65 Mbps для VK (было 1.0)
        '480': 1.7,    # ~1.7 Mbps для VK (было 2.5)
        '720': 3.3,    # ~3.3 Mbps для VK (было 5.0)
        '1080': 5.2,   # ~5.2 Mbps для VK (было 8.0)
        'audio': 0.128  # ~128 kbps для аудио (без изменений)
    }
    
    # Получаем битрейт в Mbps
    bitrate = BITRATES.get(quality, 5.0)
    
    # Конвертируем Mbps в байты и умножаем на длительность
    size_bytes = (bitrate * 1024 * 1024 * duration) / 8
    
    # Добавляем 10% для учета контейнера и метаданных
    size_bytes *= 1.1
    
    return int(size_bytes)


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


async def get_download_keyboard(video_id: int, info: dict) -> InlineKeyboardMarkup:
    keyboard = []
    duration = float(info.get('duration', 0))
    formats = info.get('formats', [])
    source_url = str(info.get('source_url', ''))
    
    # Проверяем наличие аудио в кэше
    cached_audio = await get_file(video_id, 'audio', 'audio')
    
    # Получаем размер аудио из форматов
    audio_format = next((f for f in formats if f.get('format_id') == 'worstaudio'), None)
    audio_size = audio_format.get('filesize', 0) if audio_format else estimate_video_size(duration, 'audio')
    
    # Аудио кнопка
    if audio_size < MAX_FILE_SIZE:  # Меньше 50MB
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎵 audio / {format_size(audio_size)} {'⚡️' if cached_audio else ''}",
                callback_data=f"dl_{video_id}_audio_audio"
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎵 audio / {format_size(audio_size)} ⚠️",
                callback_data=f"size_limit"
            )
        ])

    # Проверяем, является ли это Instagram видео
    is_instagram = any(
        platform in str(source_url).lower() 
        for platform in ['instagram.com', '/p/', '/reel/', '/stories/']
    )
    
    if is_instagram:
        # Для Instagram показываем только одну кнопку с лучшим качеством
        best_format = max(formats, key=lambda x: x.get('filesize', 0) if x.get('filesize', 0) > 0 else 0)
        if best_format:
            size = best_format.get('filesize', 0)
            cached_video = await get_file(video_id, '720', 'video')
            
            if size < MAX_FILE_SIZE:  # Меньше 50MB
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📹 HD / {format_size(size)} {'⚡️' if cached_video else ''}",
                        callback_data=f"dl_{video_id}_720_video"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📹 HD / {format_size(size)} ⚠️",
                        callback_data=f"size_limit"
                    )
                ])
    else:
        # Для остальных платформ оставляем текущую логику
        video_resolutions = [
            ("256x144", "144"),
            ("426x240", "240"),
            ("640x360", "360"),
            ("852x480", "480"),
            ("1280x720", "720"),
            ("1920x1080", "1080")
        ]
        
        for resolution, quality in video_resolutions:
            matching_format = next(
                (f for f in formats if f.get('format_id') == f'url{quality}'), 
                None
            )
            
            if matching_format:
                size = matching_format.get('filesize', 0)
                if not size:
                    size = estimate_video_size(duration, quality)
                
                cached_video = await get_file(video_id, quality, 'video')
                
                if size < MAX_FILE_SIZE:  # Меньше 50MB
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"📹 {resolution} / {format_size(size)} {'⚡️' if cached_video else ''}",
                            callback_data=f"dl_{video_id}_{quality}_video"
                        )
                    ])
                else:
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"📹 {resolution} / {format_size(size)} ⚠️",
                            callback_data=f"size_limit"
                        )
                    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить статистику",
                    callback_data="refresh_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Рассылка",
                    callback_data="broadcast"
                )
            ]
        ]
    )
    return keyboard

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data="cancel_broadcast"
                )
            ]
        ]
    )
    return keyboard