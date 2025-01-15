from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_file

def estimate_video_size(duration: float, quality: str) -> int:
    """
    Оценивает размер видео на основе длительности и качества.
    Используется только как запасной вариант, когда нет информации о реальном размере.
    """
    BITRATES = {
        '144': 0.3,    # ~0.3 Mbps
        '240': 0.5,    # ~0.5 Mbps
        '360': 1.0,    # ~1.0 Mbps
        '480': 2.5,    # ~2.5 Mbps
        '720': 5.0,    # ~5.0 Mbps
        '1080': 8.0,   # ~8.0 Mbps
        'audio': 0.128  # ~128 kbps для аудио
    }
    
    # Получаем битрейт в Mbps
    bitrate = BITRATES.get(quality, 5.0)
    
    # Конвертируем Mbps в байты и умножаем на длительность
    size_bytes = (bitrate * 1024 * 1024 * duration) / 8
    
    # Добавляем 10% для учета контейнера и метаданных
    size_bytes *= 1.1
    
    return int(size_bytes)

def format_size(size_bytes: int) -> str:
    """Форматируем размер в читаемый вид"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

async def get_download_keyboard(video_id: int, info: dict) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопками для скачивания видео в разных форматах.
    Показывает примерный размер файла и отмечает кэшированные файлы.
    """
    keyboard = []
    duration = float(info.get('duration', 0))
    formats = info.get('formats', [])
    
    # Проверяем наличие аудио в кэше
    cached_audio = await get_file(video_id, 'audio', 'audio')
    
    # Получаем размер аудио из форматов
    audio_format = next((f for f in formats if f.get('format_id') == 'worstaudio'), None)
    audio_size = audio_format.get('filesize', 0) if audio_format else estimate_video_size(duration, 'audio')
    
    # Аудио кнопка
    keyboard.append([
        InlineKeyboardButton(
            text=f"🎵 audio / {format_size(audio_size)} {'⚡️' if cached_audio else ''}",
            callback_data=f"dl_{video_id}_audio_audio"
        )
    ])
    
    # Видео кнопки с разными разрешениями
    video_resolutions = [
        ("256x144", "144"),
        ("426x240", "240"),
        ("640x360", "360"),
        ("852x480", "480"),
        ("1280x720", "720"),
        ("1920x1080", "1080")
    ]
    
    for resolution, quality in video_resolutions:
        # Ищем соответствующий формат в списке доступных
        matching_format = next(
            (f for f in formats if f.get('format_id') == f'url{quality}'), 
            None
        )
        
        if matching_format:
            # Используем реальный размер файла если доступен
            size = matching_format.get('filesize', 0)
            if not size:
                size = estimate_video_size(duration, quality)
            
            # Проверяем наличие в кэше
            cached_video = await get_file(video_id, quality, 'video')
            
            # Если размер меньше 2GB, добавляем кнопку
            if size < 2000 * 1024 * 1024:  # 2000 MB в байтах
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"📹 {resolution} / {format_size(size)} {'⚡️' if cached_video else ''}",
                        callback_data=f"dl_{video_id}_{quality}_video"
                    )
                ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)