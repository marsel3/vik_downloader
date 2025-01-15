from datetime import datetime
from loader import dp


async def check_user_exists(user_id: int):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            result = await conn.fetchrow('SELECT user_id FROM users WHERE user_id=$1', user_id)
            return result is not None


async def add_user(user_id: int, username: str = None):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                'INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = $2',
                user_id, username
            )


async def get_video(url: str):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            return await conn.fetchrow('SELECT * FROM videos WHERE source_url = $1', url)


async def add_video(url: str, title: str, author: str, duration: str, thumbnail: str):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            return await conn.fetchval(
                '''INSERT INTO videos (source_url, title, author, upload_date, duration, thumbnail_url, platform) 
                VALUES ($1, $2, $3, $4, $5, $6, $7) 
                ON CONFLICT (source_url) DO UPDATE 
                SET title=$2, author=$3, duration=$5, thumbnail_url=$6 
                RETURNING video_id''',
                url, title, author, datetime.now(), duration, thumbnail, 'vk'
            )


async def get_file(video_id: int, quality: str, file_type: str):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            return await conn.fetchrow(
                'SELECT * FROM files WHERE video_id = $1 AND quality = $2 AND type = $3',
                video_id, quality, file_type
            )


async def add_file(video_id: int, telegram_file_id: str, file_type: str, size: int, quality: str):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            return await conn.fetchval(
                '''INSERT INTO files (video_id, telegram_file_id, type, size, quality) 
                VALUES ($1, $2, $3, $4, $5) RETURNING file_id''',
                video_id, telegram_file_id, file_type, size, quality
            )


async def add_download(user_id: int, video_id: int, file_id: int):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                '''INSERT INTO downloads (user_id, video_id, file_id) 
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING''',
                user_id, video_id, file_id
            )


async def get_video_by_id(video_id: int):
    async with dp["db"].acquire() as conn:
        async with conn.transaction():
            return await conn.fetchrow('SELECT * FROM videos WHERE video_id = $1', video_id)