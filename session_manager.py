import aiohttp
from instagrapi import Client
import traceback
from instagrapi.exceptions import LoginRequired, ClientError
import json
import os
from datetime import datetime
import asyncio
from typing import Optional, Dict
from pathlib import Path

import yt_dlp

class InstagramService:
    def __init__(self, username: str, password: str, proxy: str = None):
        self.username = username
        self.password = password
        self.proxy = proxy
        self.client = None
        self.session_file = "instagram_session.json"
        
    async def ensure_client(self) -> Client:
        """Обеспечивает наличие авторизованного клиента"""
        if self.client is not None:
            return self.client
            
        self.client = Client()
        if self.proxy:
            self.client.set_proxy(self.proxy)
            
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, 'r') as f:
                    session_data = json.load(f)
                    self.client.set_settings(session_data)
                    try:
                        self.client.get_timeline_feed()
                        return self.client
                    except LoginRequired:
                        pass
            except Exception as e:
                pass
        
        try:
            self.client.login(self.username, self.password)
            with open(self.session_file, 'w') as f:
                json.dump(self.client.get_settings(), f)
            return self.client
        except Exception as e:
            raise

    def extract_media_info(self, media_info) -> Dict:
        """Извлекает информацию о медиа в стандартизированном формате"""
        # Получаем размеры из разных возможных источников
        width = getattr(media_info, 'width', None) or getattr(media_info, 'pixel_width', None) or 1280
        height = getattr(media_info, 'height', None) or getattr(media_info, 'pixel_height', None) or 720
        
        # Получаем URL видео или изображения
        if hasattr(media_info, 'video_url') and media_info.video_url:
            media_url = media_info.video_url
            is_video = True
        else:
            media_url = getattr(media_info, 'thumbnail_url', None) or media_info.thumbnail_url
            is_video = False
        
        # Получаем длительность видео
        duration = getattr(media_info, 'video_duration', 0) if is_video else 0
        
        # Получаем имя пользователя
        username = getattr(media_info.user, 'username', 'Unknown')
        
        # Получаем описание
        caption = ''
        if hasattr(media_info, 'caption_text'):
            caption = media_info.caption_text[:100] if media_info.caption_text else ''
        
        return {
            'title': caption or f'Instagram {"Video" if is_video else "Image"} by {username}',
            'duration': str(duration),
            'thumbnail': media_info.thumbnail_url,
            'author': username,
            'formats': [{
                'url': media_url,
                'format_id': 'url720',
                'ext': 'mp4' if is_video else 'jpg',
                'filesize': 0,  # Размер неизвестен заранее
                'format': 'HD',
                'duration': duration,
                'width': width,
                'height': height
            }],
            'source_url': getattr(media_info, 'code', str(media_info.pk))
        }

    async def get_media_info(self, url: str) -> Optional[Dict]:
        """Получает информацию о медиа (пост, история или reels)"""
        try:
            client = await self.ensure_client()
            
            # Определяем тип URL
            if 'stories' in url:
                try:
                    # Извлекаем username и story_id из URL
                    parts = [p for p in url.split('/') if p]
                    username = parts[parts.index('stories') + 1]
                    story_id = parts[-1] if parts[-1].isdigit() else None
                    
                    # Получаем user_id
                    user_id = client.user_id_from_username(username)
                    # Получаем все истории пользователя
                    stories = client.user_stories(user_id)
                    
                    if not stories:
                        raise Exception("No active stories found")
                        
                    if story_id:
                        # Если указан конкретный ID истории, ищем его
                        story_info = next((story for story in stories if str(story.pk) == story_id), None)
                        if not story_info:
                            raise Exception(f"Story with id {story_id} not found")
                    else:
                        # Если ID не указан, берем последнюю историю
                        story_info = stories[0]
                    
                    return self.extract_media_info(story_info)
                except Exception as e:
                    raise
            else:
                # Обрабатываем reels и обычные посты
                try:
                    media_pk = client.media_pk_from_url(url)
                    media_info = client.media_info(media_pk)
                    if media_info.media_type == 2:  # Видео
                        result = self.extract_media_info(media_info)
                        return result
                except Exception as e:
                    raise
                    
        except Exception as e:
            raise

    async def download_media(self, url: str, output_path: str) -> bool:
        try:
            client = await self.ensure_client()
            output_path = Path(output_path)
            
            if 'stories' in url:
                try:
                    parts = [p for p in url.split('/') if p]
                    username = parts[parts.index('stories') + 1]
                    
                    user_id = client.user_id_from_username(username)
                    stories = client.user_stories(user_id)
                    
                    if not stories:
                        raise Exception("No active stories found")
                    
                    story = stories[0]
                    video_url = story.video_url if hasattr(story, 'video_url') and story.video_url else None
                    
                    if not video_url:
                        raise Exception("Story doesn't contain video")
                    
                    timeout = aiohttp.ClientTimeout(total=300, connect=60)
                    conn = aiohttp.TCPConnector(force_close=True, ssl=False)
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Origin': 'https://www.instagram.com',
                        'Referer': 'https://www.instagram.com/'
                    }
                    
                    async with aiohttp.ClientSession(
                        connector=conn,
                        timeout=timeout,
                        headers=headers,
                        cookies=client.get_settings()['cookies']
                    ) as session:
                        async with session.get(str(video_url), proxy=self.proxy) as response:
                            if response.status == 200:
                                with open(output_path, 'wb') as f:
                                    async for chunk in response.content.iter_chunked(8192):
                                        f.write(chunk)
                                return True
                    return False
                    
                except Exception as e:
                    raise
                    
            else:
                try:
                    media_pk = client.media_pk_from_url(url)
                    media_info = client.media_info(media_pk)
                    
                    if not hasattr(media_info, 'video_url') or not media_info.video_url:
                        raise Exception("Медиа не содержит видео")
                    
                    timeout = aiohttp.ClientTimeout(total=300, connect=60)
                    conn = aiohttp.TCPConnector(force_close=True, ssl=False)
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Origin': 'https://www.instagram.com',
                        'Referer': 'https://www.instagram.com/'
                    }
                    
                    async with aiohttp.ClientSession(
                        connector=conn,
                        timeout=timeout,
                        headers=headers,
                        cookies=client.get_settings()['cookies']
                    ) as session:
                        async with session.get(str(media_info.video_url), proxy=self.proxy) as response:
                            if response.status == 200:
                                with open(output_path, 'wb') as f:
                                    async for chunk in response.content.iter_chunked(8192):
                                        f.write(chunk)
                                return True
                    return False
                    
                except Exception as e:
                    raise
                        
        except Exception as e:
            raise
        
