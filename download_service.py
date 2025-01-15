import yt_dlp
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

class Downloader:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 5,
            'no_check_certificate': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        }
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._cache = {}
        self._cache_ttl = timedelta(minutes=5)

    async def get_video_info(self, url: str) -> dict:
        try:
            now = datetime.now()
            if url in self._cache:
                cache_data, cache_time = self._cache[url]
                if now - cache_time < self._cache_ttl:
                    return cache_data.copy()
                else:
                    del self._cache[url]

            # Определяем платформу
            is_youtube = 'youtube.com' in url or 'youtu.be' in url
            is_tiktok = 'tiktok.com' in url

            if is_youtube:
                self.ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                })
            elif is_tiktok:
                self.ydl_opts.update({
                    'format': 'best',
                })

            loop = asyncio.get_event_loop()
            
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = await loop.run_in_executor(
                    self._executor,
                    lambda: ydl.extract_info(url, download=False)
                )
                
                if not info:
                    print(f"No info extracted for URL: {url}")
                    return None
                
                if 'entries' in info:
                    info = info['entries'][0]

                formats = []
                if is_youtube:
                    # Начинаем с поиска аудио и его размера
                    audio_formats = [f for f in info.get('formats', []) 
                                   if f.get('acodec', 'none') != 'none' and 
                                   (f.get('vcodec', 'none') == 'none' or not f.get('vcodec'))]
                    best_audio = max(audio_formats, key=lambda f: f.get('filesize', 0) or 0) if audio_formats else None
                    audio_size = best_audio.get('filesize', 0) or 0

                    # Собираем видео форматы
                    video_formats = {}
                    for f in info.get('formats', []):
                        if f.get('vcodec', 'none') != 'none':
                            height = f.get('height', 0)
                            if not height:
                                continue

                            # Определяем качество
                            if height <= 144:
                                quality = 'url144'
                            elif height <= 360:
                                quality = 'url360'
                            elif height <= 720:
                                quality = 'url720'
                            elif height <= 1080:
                                quality = 'url1080'
                            else:
                                continue

                            # Сохраняем только лучший формат для каждого качества
                            if quality not in video_formats or (f.get('filesize', 0) or 0) > (video_formats[quality].get('filesize', 0) or 0):
                                video_formats[quality] = f

                    # Формируем итоговый список форматов
                    formats = []
                    for quality, video_fmt in video_formats.items():
                        video_size = video_fmt.get('filesize', 0) or 0
                        total_size = video_size + audio_size  # Добавляем размер аудио
                        formats.append({
                            'url': video_fmt['url'],
                            'format_id': quality,
                            'ext': 'mp4',
                            'filesize': total_size,
                            'format': f"{video_fmt.get('height', '')}p",
                            'duration': info.get('duration', 0)
                        })

                elif is_tiktok:
                    formats.append({
                        'url': info.get('url', ''),
                        'format_id': 'url720',
                        'ext': 'mp4',
                        'filesize': info.get('filesize', 0),
                        'format': 'HD',
                        'duration': info.get('duration', 0)
                    })
                else:
                    # Стандартная обработка для других платформ (VK и др.)
                    for f in info.get('formats', []):
                        if not f:
                            continue
                            
                        f_url = f.get('url')
                        format_id = f.get('format_id')
                        
                        if not f_url or not format_id:
                            continue
                            
                        formats.append({
                            'url': f_url,
                            'format_id': format_id,
                            'ext': f.get('ext', ''),
                            'filesize': f.get('filesize', 0),
                            'format': f.get('format', ''),
                            'duration': info.get('duration', 0)
                        })

                if not formats and info.get('url'):
                    formats.append({
                        'url': info['url'],
                        'format_id': 'url720',
                        'ext': 'mp4',
                        'filesize': 0,
                        'format': 'Default',
                        'duration': info.get('duration', 0)
                    })
                
                result = {
                    'title': info.get('title', 'Без названия'),
                    'duration': str(info.get('duration', 0)),
                    'thumbnail': info.get('thumbnail', ''),
                    'author': info.get('uploader', 'Unknown'),
                    'formats': sorted(formats, key=lambda x: float(x.get('format', '0').replace('p', '') or 0), reverse=True)
                }
                
                print(f"Available formats for {url}:")
                for fmt in result['formats']:
                    print(f"Format: {fmt.get('format')}, ID: {fmt.get('format_id')}, Size: {fmt.get('filesize')}")
                
                if formats:
                    self._cache[url] = (result.copy(), now)
                return result.copy()
                
        except Exception as e:
            print(f"Error extracting info for {url}: {e}")
            return None

    def clear_cache(self):
        """Очищает весь кэш"""
        self._cache.clear()

    def remove_from_cache(self, url: str):
        """Удаляет конкретный URL из кэша"""
        if url in self._cache:
            del self._cache[url]

downloader = Downloader()