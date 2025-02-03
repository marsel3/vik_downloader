from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, instagram_proxy

class InstagramService:
    def __init__(self):
        self.client = None
        self.session_file = "instagram_session.json"
        self.last_auth_time = None
        self.auth_ttl = timedelta(hours=12)  # Переавторизация каждые 12 часов
        
        # Настройка прокси
        self.proxy = instagram_proxy
        
    async def ensure_authenticated(self) -> None:
        """Проверяет аутентификацию и при необходимости выполняет повторную авторизацию"""
        now = datetime.now()
        
        # Проверяем необходимость переавторизации
        if (self.last_auth_time is None or 
            now - self.last_auth_time > self.auth_ttl or 
            self.client is None):
            
            self.client = Client()
            
            # Устанавливаем прокси
            if self.proxy:
                self.client.set_proxy(self.proxy)
            
            # Пытаемся загрузить сохраненную сессию
            if os.path.exists(self.session_file):
                try:
                    with open(self.session_file, 'r') as f:
                        session_data = json.load(f)
                        self.client.load_settings(session_data)
                        # Проверяем валидность сессии
                        self.client.get_timeline_feed()
                        self.last_auth_time = now
                        return
                except (json.JSONDecodeError, LoginRequired, ClientError):
                    # Если сессия невалидна, удаляем файл
                    os.remove(self.session_file)
            
            # Если нет валидной сессии, выполняем новую авторизацию
            try:
                self.client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                # Сохраняем новую сессию
                with open(self.session_file, 'w') as f:
                    json.dump(self.client.get_settings(), f)
                self.last_auth_time = now
            except Exception as e:
                raise Exception(f"Ошибка авторизации в Instagram: {str(e)}")

    async def get_story_info(self, story_url: str) -> Dict[str, Any]:
        """Получает информацию о истории Instagram"""
        await self.ensure_authenticated()
        
        try:
            # Извлекаем ID истории из URL
            story_id = self._extract_story_id(story_url)
            if not story_id:
                raise ValueError("Неверный URL истории Instagram")
            
            # Получаем информацию об истории
            story_info = self.client.story_info(story_id)
            
            # Формируем информацию для скачивания
            return {
                'title': f"Instagram Story {story_info.user.username}",
                'duration': "15",  # Стандартная длительность истории
                'thumbnail': story_info.thumbnail_url,
                'author': story_info.user.username,
                'formats': [{
                    'url': story_info.video_url if story_info.video_url else story_info.thumbnail_url,
                    'format_id': 'url720',
                    'ext': 'mp4' if story_info.video_url else 'jpg',
                    'filesize': 0,  # Размер неизвестен заранее
                    'format': 'HD',
                    'width': story_info.original_width,
                    'height': story_info.original_height
                }],
                'source_url': story_url
            }
        except Exception as e:
            raise Exception(f"Ошибка получения информации об истории: {str(e)}")

    def _extract_story_id(self, url: str) -> Optional[int]:
        """Извлекает ID истории из URL"""
        try:
            # Пример URL: instagram.com/stories/username/12345678901234567
            if '/stories/' not in url:
                return None
            
            # Извлекаем ID из URL
            story_id = url.split('/')[-1].split('?')[0]
            return int(story_id)
        except (ValueError, IndexError):
            return None

    async def download_story(self, story_url: str, output_path: str) -> None:
        """Скачивает историю Instagram"""
        await self.ensure_authenticated()
        
        try:
            story_id = self._extract_story_id(story_url)
            if not story_id:
                raise ValueError("Неверный URL истории Instagram")
            
            story_info = self.client.story_info(story_id)
            
            # Скачиваем видео или фото
            if story_info.video_url:
                self.client.story_download(story_id, output_path)
            else:
                self.client.photo_download(story_id, output_path)
                
        except Exception as e:
            raise Exception(f"Ошибка скачивания истории: {str(e)}")

# Создаем глобальный экземпляр сервиса
instagram_service = InstagramService()