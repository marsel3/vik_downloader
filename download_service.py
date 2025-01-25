import yt_dlp
import asyncio
import traceback
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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive'
            }
        }
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._cache = {}
        self._cache_ttl = timedelta(minutes=5)

    def _safe_int(self, value, default=0):
        """Безопасно конвертирует значение в int"""
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

    def _get_format_height(self, fmt):
        """Безопасно получаем высоту формата"""
        height = fmt.get('height', None)
        if height is None:
            for field in [fmt.get('format_note', ''), fmt.get('format', '')]:
                if field:
                    for quality in ['1080p', '720p', '480p', '360p', '240p', '144p']:
                        if quality in field:
                            return int(quality.replace('p', ''))
        return self._safe_int(height, 0)

    def _normalize_duration(self, duration):
        """Нормализует длительность видео в целое число секунд"""
        return self._safe_int(duration, 0)

    def _safe_get_filesize(self, format_dict):
        """Безопасно получает размер файла"""
        try:
            filesize = format_dict.get('filesize')
            if filesize is None:
                filesize = format_dict.get('filesize_approx')
            return self._safe_int(filesize, 0)
        except (ValueError, TypeError):
            return 0

    async def get_video_info(self, url: str) -> dict:
        try:
            now = datetime.now()
            if url in self._cache:
                cache_data, cache_time = self._cache[url]
                if now - cache_time < self._cache_ttl:
                    return cache_data.copy()
                else:
                    del self._cache[url]

            is_youtube = 'youtube.com' in url or 'youtu.be' in url
            is_tiktok = 'tiktok.com' in url
            is_instagram = 'instagram.com' in url

            if is_instagram:
                self.ydl_opts.update({
                    'format': '(best)[protocol^=http]',
                    'extract_flat': False,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                        'Accept': '*/*',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Origin': 'https://www.instagram.com',
                        'Referer': 'https://www.instagram.com/',
                        'Sec-Fetch-Dest': 'empty',
                        'Sec-Fetch-Mode': 'cors',
                        'Sec-Fetch-Site': 'same-site',
                        'X-IG-App-ID': '936619743392459',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    'extractor_args': {
                        'instagram': {
                            'direct': True,
                            'prefer_direct_download': True
                        }
                    }
                })
            elif is_youtube:
                self.ydl_opts.update({
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                })
            elif is_tiktok:
                self.ydl_opts.update({
                    'format': 'best',
                    'extract_flat': False,
                    'quiet': True,
                    'no_warnings': True
                })

            loop = asyncio.get_event_loop()
            info = None
            
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                try:
                    info = await loop.run_in_executor(
                        self._executor,
                        lambda: ydl.extract_info(url, download=False)
                    )
                except Exception as e:
                    print(f"Initial extraction error: {str(e)}")
                    if is_instagram:
                        print("Trying alternative Instagram extraction...")
                        alt_opts = self.ydl_opts.copy()
                        alt_opts.update({
                            'format': 'bestaudio/best',
                            'extract_flat': True
                        })
                        try:
                            with yt_dlp.YoutubeDL(alt_opts) as alt_ydl:
                                info = await loop.run_in_executor(
                                    self._executor,
                                    lambda: alt_ydl.extract_info(url, download=False)
                                )
                        except Exception as e2:
                            print(f"Alternative extraction failed: {str(e2)}")
                            return None
                    else:
                        return None
                
            if not info:
                print(f"No info extracted for URL: {url}")
                return None
            
            if 'entries' in info:
                info = info['entries'][0]

            duration = self._normalize_duration(info.get('duration', 0))
            formats = []

            try:
                if is_instagram:
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

                elif is_youtube:
                    available_formats = info.get('formats', [])
                    
                    # Собираем аудио форматы
                    audio_formats = [f for f in available_formats 
                                    if f.get('acodec', 'none') != 'none' 
                                    and (f.get('vcodec', 'none') == 'none' or not f.get('vcodec'))]
                    best_audio = max(audio_formats, key=lambda f: self._safe_get_filesize(f)) if audio_formats else None
                    
                    # Собираем видео форматы
                    video_formats = {}
                    for f in available_formats:
                        if f.get('vcodec', 'none') == 'none':
                            continue
                            
                        height = self._get_format_height(f)
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
                    
                    # Формируем итоговые форматы
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

                elif is_tiktok:
                    video_formats = [f for f in info.get('formats', []) if f.get('vcodec') != 'none']
                    if video_formats:
                        best_video = max(video_formats, key=lambda f: self._safe_get_filesize(f))
                        formats.append({
                            'url': best_video.get('url', ''),
                            'format_id': 'url720',  # Используем фиксированный format_id
                            'ext': best_video.get('ext', 'mp4'),
                            'filesize': self._safe_get_filesize(best_video),
                            'format': 'HD',
                            'duration': duration,
                            'width': self._safe_int(best_video.get('width'), 0),
                            'height': self._safe_int(best_video.get('height'), 720)
                        })
                    else:
                        # Если не нашли видео форматы, используем основной URL
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

                else:
                    for f in info.get('formats', []):
                        if not f or not f.get('url') or not f.get('format_id'):
                            continue

                        formats.append({
                            'url': f['url'],
                            'format_id': f['format_id'],
                            'ext': f.get('ext', ''),
                            'filesize': self._safe_get_filesize(f),
                            'format': f.get('format', ''),
                            'duration': duration,
                            'width': self._safe_int(f.get('width'), 0),
                            'height': self._safe_int(f.get('height'), 0)
                        })

                if not formats and info.get('url'):
                    formats.append({
                        'url': info['url'],
                        'format_id': 'url720',
                        'ext': 'mp4',
                        'filesize': self._safe_get_filesize(info),
                        'format': 'Default',
                        'duration': duration,
                        'width': self._safe_int(info.get('width'), 0),
                        'height': self._safe_int(info.get('height'), 720)
                    })

                # Безопасное удаление дубликатов
                unique_formats = {}
                for f in formats:
                    key = f['format_id']
                    current_size = self._safe_get_filesize(f)
                    if key not in unique_formats or current_size > self._safe_get_filesize(unique_formats[key]):
                        unique_formats[key] = f

                sorted_formats = sorted(
                    unique_formats.values(),
                    key=lambda x: self._safe_int(''.join(filter(str.isdigit, x.get('format', '0'))), 0),
                    reverse=True
                )

                result = {
                    'title': info.get('title', 'Без названия'),
                    'duration': str(duration),
                    'thumbnail': info.get('thumbnail', ''),
                    'author': info.get('uploader', 'Unknown'),
                    'formats': sorted_formats,
                    'source_url': url
                }

                print(f"Available formats for {url}:")
                for fmt in result['formats']:
                    print(f"Format: {fmt.get('format')}, ID: {fmt.get('format_id')}, "
                          f"Size: {fmt.get('filesize')}, Dimensions: {fmt.get('width')}x{fmt.get('height')}")

                self._cache[url] = (result.copy(), now)
                return result.copy()

            except Exception as inner_e:
                print(f"Error processing formats: {str(inner_e)}")
                print(f"Inner traceback: {traceback.format_exc()}")
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

downloader = Downloader()