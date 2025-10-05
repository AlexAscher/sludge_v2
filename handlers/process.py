

# ...existing code...


from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery
from services.downloader import download_video
from services.video_edit import randomize_metadata
from services.photo_edit import randomize_exif
import mimetypes
import aiohttp
import os
import uuid
import boto3
import time
from config import TEMP_DIR, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION, S3_ENDPOINT
from collections import defaultdict
import zipfile
import shutil

router = Router()

file_cache = {}
file_cache_times = {}

user_files = defaultdict(list)  # {user_id: [file_paths]}

def cleanup_old_files():
    """Удаляет файлы старше 24 часов из кэша и с диска."""
    current_time = time.time()
    to_delete = [uid for uid, t in file_cache_times.items() if current_time - t > 86400]
    for uid in to_delete:
        filepath = file_cache.get(uid)
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        del file_cache[uid]
        del file_cache_times[uid]
    # Cleanup user_files
    for user_id, files in list(user_files.items()):
        user_files[user_id] = [f for f in files if os.path.exists(f) and current_time - os.path.getmtime(f) < 86400]
        if not user_files[user_id]:
            del user_files[user_id]

# S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=S3_REGION,
    endpoint_url=S3_ENDPOINT
)

# Импорт autocaption_video и регистрация caption_handler строго после router

# Autocrop callback

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger_caption = logging.getLogger("caption_handler")




## Удалено дублирование импортов и router = Router()


# Tools menu callback (edit message)

@router.callback_query(F.data == "tools")
async def show_tools_menu(callback: CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Go Back", callback_data="back")],
    ])
    # Если сообщение с медиа — используем edit_caption, иначе edit_text
    try:
        if callback.message.photo or callback.message.video:
            await callback.message.edit_caption(caption="Select a template option:", reply_markup=keyboard)
        else:
            await callback.message.edit_text("Select a template option:", reply_markup=keyboard)
    except Exception as e:
        await callback.answer("Failed to open tools menu.", show_alert=True)


# Go Back button handler (restore previous menu)
@router.callback_query(F.data == "back")
async def go_back_menu(callback: CallbackQuery):
    # Определяем, к какому типу файла возвращаться (фото или видео)
    # Пробуем получить caption и media type
    caption = callback.message.caption or callback.message.text or ""
    # Определяем, что было отправлено: фото или видео
    is_photo = callback.message.photo is not None
    is_video = callback.message.video is not None
    # Клавиатура как после обработки фото/видео
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Download", callback_data="download_photo" if is_photo else "download_video")],
        [types.InlineKeyboardButton(text="Templates", callback_data="templates"), types.InlineKeyboardButton(text="Tools", callback_data="tools")],
        [types.InlineKeyboardButton(text="Bulk Templates", callback_data="bulk_templates"), types.InlineKeyboardButton(text="Bulk Randomize", callback_data="bulk_randomize")],
        [types.InlineKeyboardButton(text="Get Paid to Post 💰", callback_data="get_paid")],
        [types.InlineKeyboardButton(text="Monthly Subscription", callback_data="monthly_sub")],
        [types.InlineKeyboardButton(text="Annual Subscription (3 months free)", callback_data="annual_sub")],
    ])
    # Обновляем только reply_markup и caption, не отправляем новое сообщение
    try:
        if is_photo:
            await callback.message.edit_caption(caption="✅ Done! Here is your photo with new metadata.", reply_markup=keyboard)
        elif is_video:
            await callback.message.edit_caption(caption="✅ Done! Here is your video with new metadata.", reply_markup=keyboard)
        else:
            # Если не фото и не видео, просто обновим reply_markup
            await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        await callback.answer("Failed to go back.", show_alert=True)


# Обработка фото от пользователя
@router.message(F.photo)
async def handle_photo(message: Message):
    cleanup_old_files()  # Очищаем старые файлы

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_path = file.file_path
    dest_path = os.path.join(TEMP_DIR, f"{photo.file_id}.jpg")
    await message.bot.download_file(file_path, dest_path)
    # Сохраняем в кэш
    file_uuid = str(uuid.uuid4())
    file_cache[file_uuid] = dest_path
    current_time = time.time()
    file_cache_times[file_uuid] = current_time
    # Вместо обработки, отправляем сообщение с выбором количества копий
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="5", callback_data=f"copies|5|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="10", callback_data=f"copies|10|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="20", callback_data=f"copies|20|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="30", callback_data=f"copies|30|{file_uuid}|photo"),
        ],
        [
            types.InlineKeyboardButton(text="40", callback_data=f"copies|40|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="50", callback_data=f"copies|50|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="75", callback_data=f"copies|75|{file_uuid}|photo"),
            types.InlineKeyboardButton(text="100", callback_data=f"copies|100|{file_uuid}|photo"),
        ],
        [
            types.InlineKeyboardButton(text="120", callback_data=f"copies|120|{file_uuid}|photo"),
        ]
    ])
    await message.answer("File detected. How many copies do you want?", reply_markup=keyboard)

# Обработка видео от пользователя
@router.message(F.video)
async def handle_video(message: Message):
    cleanup_old_files()  # Очищаем старые файлы

    video = message.video
    file = await message.bot.get_file(video.file_id)
    file_path = file.file_path
    ext = os.path.splitext(file_path)[1] or ".mp4"
    dest_path = os.path.join(TEMP_DIR, f"{video.file_id}{ext}")
    await message.bot.download_file(file_path, dest_path)
    # Сохраняем в кэш
    file_uuid = str(uuid.uuid4())
    file_cache[file_uuid] = dest_path
    current_time = time.time()
    file_cache_times[file_uuid] = current_time
    # Вместо обработки, отправляем сообщение с выбором количества копий
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="5", callback_data=f"copies|5|{file_uuid}|video"),
            types.InlineKeyboardButton(text="10", callback_data=f"copies|10|{file_uuid}|video"),
            types.InlineKeyboardButton(text="20", callback_data=f"copies|20|{file_uuid}|video"),
            types.InlineKeyboardButton(text="30", callback_data=f"copies|30|{file_uuid}|video"),
        ],
        [
            types.InlineKeyboardButton(text="40", callback_data=f"copies|40|{file_uuid}|video"),
            types.InlineKeyboardButton(text="50", callback_data=f"copies|50|{file_uuid}|video"),
            types.InlineKeyboardButton(text="75", callback_data=f"copies|75|{file_uuid}|video"),
            types.InlineKeyboardButton(text="100", callback_data=f"copies|100|{file_uuid}|video"),
        ],
        [
            types.InlineKeyboardButton(text="120", callback_data=f"copies|120|{file_uuid}|video"),
        ]
    ])
    await message.answer("File detected. How many copies do you want?", reply_markup=keyboard)




# Универсальное определение типа файла по ссылке
def guess_file_type(url: str) -> str:
    ext = os.path.splitext(url)[1].lower()
    if ext in {'.mp4', '.mov', '.avi', '.webm'}:
        return 'video'
    if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}:
        return 'photo'
    # Проверка по домену для популярных видеохостингов
    video_domains = [
        'youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com', 'vk.com', 'twitter.com', 'x.com', 'facebook.com', 'vimeo.com', 'dailymotion.com'
    ]
    for domain in video_domains:
        if domain in url:
            return 'video-hosting'
    return 'unknown'

# Универсальное скачивание файла (фото/видео)
async def download_file(url: str) -> str:
    filename = os.path.basename(url.split('?')[0])
    if not filename:
        filename = 'file'
    filepath = os.path.join(TEMP_DIR, filename)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(filepath, 'wb') as f:
                    f.write(await resp.read())
                return filepath
            else:
                raise Exception(f"HTTP {resp.status}")

@router.message(F.text.startswith("http"))
async def handle_link(message: Message):
    cleanup_old_files()  # Очищаем старые файлы

    url = message.text.strip()
    await message.answer(f"🔗 Link received: {url}\n⏳ Downloading...")


    # ...удалён функционал TikTok и Instagram...

    # Старое поведение для остальных ссылок
    filetype = guess_file_type(url)
    if filetype not in ('photo', 'video', 'video-hosting'):
        await message.answer("❌ Only photo and video links are supported. Please send a direct photo or video file, or a link to one.")
        return
    try:
        if filetype in ('video', 'video-hosting'):
            filepath = await download_video(url)
            if not filepath:
                raise Exception("Failed to download video. It may be unavailable or deleted.")
        elif filetype == 'photo':
            filepath = await download_file(url)
        else:
            filepath = await download_file(url)
            with open(filepath, 'rb') as f:
                head = f.read(512)
                if b'<html' in head.lower():
                    raise Exception("The link does not point to a file, but to a web page.")
        if not filepath:
            raise Exception("File was not downloaded")
        file_uuid = str(uuid.uuid4())
        file_cache[file_uuid] = filepath
        current_time = time.time()
        file_cache_times[file_uuid] = current_time
        ext = os.path.splitext(filepath)[1].lower()
        media_type = "photo" if ext in {'.jpg', '.jpeg', '.png', '.webp'} else "video" if ext in {'.mp4', '.mov', '.avi', '.webm'} else "document"
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="5", callback_data=f"copies|5|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="10", callback_data=f"copies|10|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="20", callback_data=f"copies|20|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="30", callback_data=f"copies|30|{file_uuid}|{media_type}"),
            ],
            [
                types.InlineKeyboardButton(text="40", callback_data=f"copies|40|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="50", callback_data=f"copies|50|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="75", callback_data=f"copies|75|{file_uuid}|{media_type}"),
                types.InlineKeyboardButton(text="100", callback_data=f"copies|100|{file_uuid}|{media_type}"),
            ],
            [
                types.InlineKeyboardButton(text="120", callback_data=f"copies|120|{file_uuid}|{media_type}"),
            ]
        ])
        await message.answer("File detected. How many copies do you want?", reply_markup=keyboard)
    except Exception as e:
        await message.answer(f"❌ Failed to download file: {e}")

# Обработчик для неподдерживаемых сообщений
@router.message()
async def handle_unsupported(message: Message):
    await message.answer("❌ Please send only photos or videos (or links to them). Other types are not supported.")

# 2️⃣ Обработка кнопки (с путём к файлу)
@router.callback_query(F.data.startswith("download|"))
async def process_download(callback: CallbackQuery):
    cleanup_old_files()  # Очищаем старые файлы

    await callback.message.answer("⏳ Processing file...")

    try:
        _, input_file = callback.data.split("|", 1)
        ext = os.path.splitext(input_file)[1].lower()
        if ext in {'.jpg', '.jpeg', '.png', '.webp'}:
            output_file = randomize_exif(input_file)
            await callback.message.answer_photo(types.FSInputFile(output_file), caption="✅ Done! Here is your file with new metadata.")
        elif ext in {'.mp4', '.mov', '.avi', '.webm'}:
            output_file = randomize_metadata(input_file)
            await callback.message.answer_video(types.FSInputFile(output_file), caption="✅ Done! Here is your file with new metadata.")
        else:
            output_file = randomize_metadata(input_file)
            await callback.message.answer_document(types.FSInputFile(output_file), caption="✅ Done! Here is your file with new metadata.")
    except Exception as e:
        await callback.message.answer(f"❌ Error: {e}")

# Обработка выбора количества копий
@router.callback_query(F.data.startswith("copies|"))
async def process_copies(callback: CallbackQuery):
    cleanup_old_files()  # Очищаем старые файлы

    try:
        parts = callback.data.split("|")
        if len(parts) != 4:
            await callback.answer("Invalid data", show_alert=True)
            return
        _, count_str, file_uuid, media_type = parts
        count = int(count_str)
        if count < 1 or count > 120:
            await callback.answer("Invalid count", show_alert=True)
            return
        filepath = file_cache.get(file_uuid)
        if not filepath:
            await callback.answer("File not found", show_alert=True)
            return
        await callback.message.answer(f"⏳ Creating {count} copies...")

        import random, string
        def long_random_name(length=36):
            return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

        session_id = str(uuid.uuid4())
        download_links = []
        output_files = []  # Список для хранения путей к копиям
        file_names = []  # Список для хранения имён файлов

        for i in range(count):
            try:
                logging.info(f"Creating copy {i+1}")
                if media_type == "photo":
                    output_file = randomize_exif(filepath)
                elif media_type == "video":
                    output_file = randomize_metadata(filepath)
                else:
                    output_file = randomize_metadata(filepath)

                output_files.append(output_file)  # Добавляем в список для удаления
                user_files[callback.from_user.id].append(output_file)  # Добавляем в user_files
                logging.info(f"output_file: {output_file}, exists: {os.path.exists(output_file)}")

                # Генерируем случайное имя файла
                ext = os.path.splitext(output_file)[1]
                random_name = long_random_name(36) + ext
                file_names.append(random_name)

                # Загружаем на S3
                key = f"{session_id}/{random_name}"
                logging.info(f"key: {key}, bucket: {S3_BUCKET_NAME}")
                # Определяем ContentType на основе расширения
                ext_lower = ext.lower()
                if ext_lower in ['.jpg', '.jpeg']:
                    content_type = 'image/jpeg'
                elif ext_lower == '.png':
                    content_type = 'image/png'
                elif ext_lower == '.webp':
                    content_type = 'image/webp'
                elif ext_lower == '.mp4':
                    content_type = 'video/mp4'
                elif ext_lower == '.mov':
                    content_type = 'video/quicktime'
                elif ext_lower == '.avi':
                    content_type = 'video/x-msvideo'
                elif ext_lower == '.webm':
                    content_type = 'video/webm'
                else:
                    content_type = 'application/octet-stream'
                s3_client.upload_file(output_file, S3_BUCKET_NAME, key, ExtraArgs={'ContentType': content_type})
                logging.info(f"Uploaded to S3: {key}")

                # Получаем presigned URL
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': S3_BUCKET_NAME, 'Key': key},
                    ExpiresIn=3600  # 1 час
                )
                logging.info(f"Presigned URL: {url[:50]}...")  # Log first 50 chars
                download_links.append(url)

            except Exception as e:
                logging.error(f"Error in copy {i+1}: {e}")
                await callback.message.answer(f"❌ Error creating copy {i+1}: {e}")

        logging.info(f"Created {len(download_links)} links")

        # Создаём ZIP-архив всех копий
        zip_path = os.path.join(TEMP_DIR, f"{session_id}_all_files.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_path, filename in zip(output_files, file_names):
                if os.path.exists(file_path):
                    zipf.write(file_path, filename)

        # Загружаем ZIP на S3
        zip_key = f"{session_id}/all_files.zip"
        s3_client.upload_file(zip_path, S3_BUCKET_NAME, zip_key, ExtraArgs={'ContentType': 'application/zip'})

        # Получаем presigned URL для ZIP
        zip_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': zip_key},
            ExpiresIn=3600
        )

        # Удаляем локальный ZIP
        os.remove(zip_path)

        # Генерируем HTML-страницу с карточками файлов
        html_content = f"""<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>Your File Copies</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #f5f6fa; margin: 0; padding: 0; }}
        .container {{ max-width: 900px; margin: 30px auto; }}
        h1 {{ text-align: center; margin-bottom: 24px; }}
        .download-all {{ text-align: center; margin-bottom: 30px; }}
        .download-btn {{ background: #28a745; color: #fff; border: none; border-radius: 8px; padding: 12px 24px; font-size: 1.1em; cursor: pointer; text-decoration: none; display: inline-block; }}
        .download-btn:hover {{ background: #218838; }}
        .grid {{ display: flex; flex-wrap: wrap; gap: 24px; justify-content: center; }}
        .card {{ background: #fff; border-radius: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); width: 260px; overflow: hidden; transition: box-shadow .2s; position: relative; }}
        .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.16); }}
        .card-thumb {{ width: 100%; height: 180px; object-fit: cover; background: #eee; display: flex; align-items: center; justify-content: center; }}
        .card-content {{ padding: 14px 16px 10px 16px; }}
        .card-title {{ font-size: 1.05em; font-weight: 600; margin: 0 0 6px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .card-meta {{ font-size: 0.93em; color: #888; margin-bottom: 8px; }}
        .card-actions {{ display: flex; gap: 10px; }}
        .card-btn {{ flex: 1; background: #007bff; color: #fff; border: none; border-radius: 6px; padding: 7px 0; font-size: 1em; cursor: pointer; transition: background .2s; text-align: center; text-decoration: none; }}
        .card-btn:hover {{ background: #0056b3; }}
        .card-index {{ position: absolute; left: 10px; top: 10px; background: rgba(0,0,0,0.7); color: #fff; border-radius: 6px; font-size: 0.95em; padding: 2px 8px; }}
        .video-player {{ width: 100%; height: 180px; background: #000; }}
    </style>
</head>
<body>
    <div class='container'>
        <h1>Your File Copies</h1>
        <div class='download-all'>
            <a href='{zip_url}' class='download-btn'>Download All as ZIP</a>
        </div>
        <div class='grid'>
"""

        import random, string
        def long_random_name(length=32):
            return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

        for i, (url, filename) in enumerate(zip(download_links, file_names), 1):
            ext = os.path.splitext(filename)[1].lower()
            is_video = ext in ['.mp4', '.mov', '.avi', '.webm']
            is_photo = ext in ['.jpg', '.jpeg', '.png', '.webp']
            if is_photo:
                thumb = f"<img src='{url}' class='card-thumb' alt='Preview'>"
                # Клик по карточке открывает фото в новой вкладке на весь экран
                html_content += f"""
            <div class='card'>
                <div class='card-index'>{i}</div>
                <a href='{url}' target='_blank' style='text-decoration:none;'>
                    {thumb}
                </a>
                <div class='card-content'>
                    <div class='card-title'>{filename}</div>
                    <div class='card-meta'>PHOTO</div>
                </div>
            </div>
"""
            elif is_video:
                thumb = f"<video src='{url}' class='card-thumb' muted playsinline preload='metadata'></video>"
                # Клик по карточке открывает видео в новой вкладке (плеер)
                html_content += f"""
            <div class='card'>
                <div class='card-index'>{i}</div>
                <a href='{url}' target='_blank' style='text-decoration:none;'>
                    {thumb}
                </a>
                <div class='card-content'>
                    <div class='card-title'>{filename}</div>
                    <div class='card-meta'>VIDEO</div>
                </div>
            </div>
"""
            else:
                thumb = f"<div class='card-thumb'>No preview</div>"
                html_content += f"""
            <div class='card'>
                <div class='card-index'>{i}</div>
                <a href='{url}' target='_blank' style='text-decoration:none;'>
                    {thumb}
                </a>
                <div class='card-content'>
                    <div class='card-title'>{filename}</div>
                    <div class='card-meta'>FILE</div>
                </div>
            </div>
"""

        html_content += """
        </div>
        <p style='text-align:center;color:#888;font-size:0.98em;margin-top:30px;'>Links valid for 1 hour.</p>
    </div>
</body>
</html>"""

        # Загружаем HTML в S3
        html_key = f"{session_id}/index.html"
        logging.info(f"Uploading HTML: {html_key}")
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=html_key, Body=html_content, ContentType='text/html')
        logging.info("HTML uploaded")

        # Получаем presigned URL для HTML
        page_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': html_key},
            ExpiresIn=3600
        )
        logging.info(f"Page URL: {page_url[:50]}...")

        await callback.message.answer(f"✅ Your copies are ready! View and download them here: {page_url}")

        # Удаляем временные файлы
        try:
            for f in output_files:
                if os.path.exists(f):
                    os.remove(f)
            if os.path.exists(filepath):
                os.remove(filepath)
            # Очищаем кэш
            del file_cache[file_uuid]
            del file_cache_times[file_uuid]
        except Exception as e:
            logging.error(f"Error cleaning up files: {e}")

    except Exception as e:
        logging.error(f"Error in process_copies: {e}")
        await callback.answer(f"❌ Error: {e}", show_alert=True)
