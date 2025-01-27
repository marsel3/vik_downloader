import yt_dlp
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

class VideoFormat:
    def __init__(self, url: str, format_id: str, ext: str, filesize: int,
                 format_name: str, duration: int, width: int, height: int,
                 vcodec: str = None, acodec: str = None):
        self.url = url
        self.format_id = format_id
        self.ext = ext
        self.filesize = filesize
        self.format_name = format_name
        self.duration = duration
        self.width = width
        self.height = height
        self.vcodec = vcodec
        self.acodec = acodec

class VideoInfo:
    def __init__(self, title: str, duration: str, thumbnail: str,
                 author: str, formats: List[VideoFormat], source_url: str):
        self.title = title
        self.duration = duration
        self.thumbnail = thumbnail
        self.author = author
        self.formats = formats
        self.source_url = source_url

class BaseDownloader(ABC):
    def __init__(self):
        self.ydl_opts = {}
        self.base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 5,
            'no_check_certificate': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive'
            }
        }

    @abstractmethod
    async def get_video_info(self, url: str, ydl: yt_dlp.YoutubeDL) -> Optional[Dict]:
        pass

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            if isinstance(value, str):
                return int(float(value))
            if isinstance(value, (int, float)):
                return int(value)
            return default
        except (ValueError, TypeError):
            return default

    def _safe_get_filesize(self, format_dict: Dict) -> int:
        try:
            filesize = format_dict.get('filesize')
            if filesize is None:
                filesize = format_dict.get('filesize_approx')
            return self._safe_int(filesize, 0)
        except (ValueError, TypeError):
            return 0

    def _normalize_duration(self, duration: Any) -> int:
        return self._safe_int(duration, 0)

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = {
            **self.base_opts,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        }

    async def get_video_info(self, url: str, ydl: yt_dlp.YoutubeDL) -> Optional[Dict]:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )
            
            if not info:
                return None

            formats = []
            duration = self._normalize_duration(info.get('duration', 0))

            # Собираем аудио форматы
            audio_formats = [f for f in info.get('formats', [])
                           if f.get('acodec', 'none') != 'none'
                           and (f.get('vcodec', 'none') == 'none' or not f.get('vcodec'))]
            best_audio = max(audio_formats, key=lambda f: self._safe_get_filesize(f)) if audio_formats else None

            # Собираем видео форматы
            video_formats = {}
            for f in info.get('formats', []):
                if f.get('vcodec', 'none') == 'none':
                    continue

                height = self._safe_int(f.get('height', 0))
                if height <= 0:
                    continue

                current_size = self._safe_get_filesize(f)
                if height not in video_formats or current_size > self._safe_get_filesize(video_formats[height]):
                    video_formats[height] = f

            # Стандартизируем качество
            quality_mapping = {
                1080: 'url1080',
                720: 'url720',
                480: 'url480',
                360: 'url360',
                240: 'url240',
                144: 'url144'
            }

            for height, video_fmt in video_formats.items():
                closest_quality = min(quality_mapping.keys(), key=lambda x: abs(x - height))
                format_id = quality_mapping[closest_quality]

                video_size = self._safe_get_filesize(video_fmt)
                audio_size = self._safe_get_filesize(best_audio) if best_audio else 0
                total_size = video_size + audio_size

                video_url = video_fmt.get('url')
                if not video_url and video_fmt.get('fragment_base_url'):
                    video_url = video_fmt['fragment_base_url']

                formats.append({
                    'url': video_url,
                    'format_id': format_id,
                    'ext': video_fmt.get('ext', 'mp4'),
                    'filesize': total_size,
                    'format': f'{height}p',
                    'duration': duration,
                    'width': self._safe_int(video_fmt.get('width'), 0),
                    'height': height,
                    'vcodec': video_fmt.get('vcodec', ''),
                    'acodec': video_fmt.get('acodec', '')
                })

            return {
                'title': info.get('title', 'Без названия'),
                'duration': str(duration),
                'thumbnail': info.get('thumbnail', ''),
                'author': info.get('uploader', 'Unknown'),
                'formats': sorted(formats, key=lambda x: self._safe_int(x['height'], 0), reverse=True),
                'source_url': url
            }

        except Exception as e:
            print(f"Error in YouTube downloader: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

class InstagramDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = {
            **self.base_opts,
            'format': 'best',
            'cookiefile': 'instagram.txt',
            'extract_flat': True,
            'ignoreerrors': True,
            'no_color': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Origin': 'https://www.instagram.com',
                'Referer': 'https://www.instagram.com/'
            }
        }

    async def get_video_info(self, url: str, ydl: yt_dlp.YoutubeDL) -> Optional[Dict]:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

            if not info:
                return None

            duration = self._normalize_duration(info.get('duration', 0))
            formats = []

            # Пытаемся получить основной URL видео
            main_url = info.get('url')
            if main_url:
                formats.append({
                    'url': main_url,
                    'format_id': 'url720',
                    'ext': info.get('ext', 'mp4'),
                    'filesize': self._safe_get_filesize(info),
                    'format': '720p',
                    'duration': duration,
                    'width': self._safe_int(info.get('width'), 0),
                    'height': self._safe_int(info.get('height'), 720)
                })

            # Обрабатываем дополнительные форматы
            for f in info.get('formats', []):
                if not f or not f.get('url'):
                    continue

                height = self._safe_int(f.get('height'), 720)
                formats.append({
                    'url': f['url'],
                    'format_id': f'url{height}',
                    'ext': f.get('ext', 'mp4'),
                    'filesize': self._safe_get_filesize(f),
                    'format': f'{height}p',
                    'duration': duration,
                    'width': self._safe_int(f.get('width'), 0),
                    'height': height
                })

            return {
                'title': info.get('title', 'Без названия'),
                'duration': str(duration),
                'thumbnail': info.get('thumbnail', ''),
                'author': info.get('uploader', 'Unknown'),
                'formats': formats,
                'source_url': url
            }

        except Exception as e:
            print(f"Error in Instagram downloader: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

class TikTokDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = {
            **self.base_opts,
            'format': 'best'
        }

    async def get_video_info(self, url: str, ydl: yt_dlp.YoutubeDL) -> Optional[Dict]:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

            if not info:
                return None

            duration = self._normalize_duration(info.get('duration', 0))
            formats = []

            video_formats = [f for f in info.get('formats', []) if f.get('vcodec') != 'none']
            if video_formats:
                best_video = max(video_formats, key=lambda f: self._safe_get_filesize(f))
                formats.append({
                    'url': best_video.get('url', ''),
                    'format_id': 'url720',
                    'ext': best_video.get('ext', 'mp4'),
                    'filesize': self._safe_get_filesize(best_video),
                    'format': 'HD',
                    'duration': duration,
                    'width': self._safe_int(best_video.get('width'), 0),
                    'height': self._safe_int(best_video.get('height'), 720)
                })
            else:
                formats.append({
                    'url': info.get('url', ''),
                    'format_id': 'url720',
                    'ext': info.get('ext', 'mp4'),
                    'filesize': self._safe_get_filesize(info),
                    'format': 'HD',
                    'duration': duration,
                    'width': self._safe_int(info.get('width'), 0),
                    'height': self._safe_int(info.get('height'), 720)
                })

            return {
                'title': info.get('title', 'Без названия'),
                'duration': str(duration),
                'thumbnail': info.get('thumbnail', ''),
                'author': info.get('uploader', 'Unknown'),
                'formats': formats,
                'source_url': url
            }

        except Exception as e:
            print(f"Error in TikTok downloader: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

class VKDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = {
            **self.base_opts,
            'format': 'best'
        }

    async def get_video_info(self, url: str, ydl: yt_dlp.YoutubeDL) -> Optional[Dict]:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

            if not info:
                return None

            duration = self._normalize_duration(info.get('duration', 0))
            formats = []

            for f in info.get('formats', []):
                if not f or not f.get('url'):
                    continue

                height = self._safe_int(f.get('height'), 0)
                if height > 0:
                    formats.append({
                        'url': f['url'],
                        'format_id': f'url{height}',
                        'ext': f.get('ext', 'mp4'),
                        'filesize': self._safe_get_filesize(f),
                        'format': f'{height}p',
                        'duration': duration,
                        'width': self._safe_int(f.get('width'), 0),
                        'height': height
                    })

            return {
                'title': info.get('title', 'Без названия'),
                'duration': str(duration),
                'thumbnail': info.get('thumbnail', ''),
                'author': info.get('uploader', 'Unknown'),
                'formats': sorted(formats, key=lambda x: self._safe_int(x['height'], 0), reverse=True),
                'source_url': url
            }

        except Exception as e:
            print(f"Error in VK downloader: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            return None

class Downloader:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._cache = {}
        self._cache_ttl = timedelta(minutes=5)
        self.base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 5,
            'no_check_certificate': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive'
            }
        }
        
        # Инициализация загрузчиков для разных платформ
        self._downloaders = {
            'youtube': YouTubeDownloader(),
            'instagram': InstagramDownloader(),
            'tiktok': TikTokDownloader(),
            'vk': VKDownloader()
        }

    def _get_platform(self, url: str) -> Optional[str]:
        """Определяет платформу по URL"""
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'instagram.com' in url:
            return 'instagram'
        elif 'tiktok.com' in url:
            return 'tiktok'
        elif 'vk.com' in url:
            return 'vk'
        return None

    async def get_video_info(self, url: str) -> Optional[Dict]:
        """
        Получает информацию о видео с учетом платформы
        Args:
            url: URL видео
        Returns:
            Dict с информацией о видео или None в случае ошибки
        """
        try:
            now = datetime.now()
            
            # Проверяем кэш
            if url in self._cache:
                cache_data, cache_time = self._cache[url]
                if now - cache_time < self._cache_ttl:
                    return cache_data.copy()
                else:
                    del self._cache[url]

            # Определяем платформу
            platform = self._get_platform(url)
            if not platform:
                print(f"Unsupported platform for URL: {url}")
                return None

            # Получаем соответствующий загрузчик
            downloader = self._downloaders[platform]
            
            # Устанавливаем специфичные для платформы опции
            ydl_opts = {**self.base_opts, **downloader.ydl_opts}
            
            # Получаем информацию о видео
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = await downloader.get_video_info(url, ydl)
                
                if result:
                    # Сохраняем в кэш
                    self._cache[url] = (result.copy(), now)
                    return result.copy()
                    
                return None

        except Exception as e:
            print(f"Error in get_video_info: {str(e)}")
            print(f"Full traceback: {traceback.format_exc()}")
            return None

    def clear_cache(self):
        """Очищает весь кэш"""
        self._cache.clear()

    def remove_from_cache(self, url: str):
        """Удаляет конкретный URL из кэша"""
        if url in self._cache:
            del self._cache[url]

# Создаем единственный экземпляр загрузчика
downloader = Downloader()