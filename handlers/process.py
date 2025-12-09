# ...existing code...


from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery
## download_video больше не используется
from services.video_edit import randomize_metadata
from services.photo_edit import randomize_exif
import mimetypes
import aiohttp
import os
import uuid
import boto3
import time
from config import TEMP_DIR, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION, S3_ENDPOINT, \
    FREE_DAILY_LIMIT, UPLOADER_URL
from collections import defaultdict
import zipfile
import shutil
from db import increment_files, get_user
from services import metrics

router = Router()

file_cache = {}
file_cache_times = {}

user_files = defaultdict(list)  # {user_id: [file_paths]}

# Отслеживание последнего файла каждого пользователя: {user_id: {'file_uuid': uuid, 'file_path': path}}
user_last_file = {}


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
    # If the message has media — use edit_caption, otherwise edit_text
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
    caption = callback.message.caption or callback.message.text or ""
    is_photo = callback.message.photo is not None
    is_video = callback.message.video is not None
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Templates", callback_data="templates"),
         types.InlineKeyboardButton(text="Tools", callback_data="tools")],
        [types.InlineKeyboardButton(text="Bulk Templates", callback_data="bulk_templates"),
         types.InlineKeyboardButton(text="Bulk Randomize", callback_data="bulk_randomize")],
        [types.InlineKeyboardButton(text="Get Paid to Post 💰", callback_data="get_paid")],
        [types.InlineKeyboardButton(text="Monthly Subscription", callback_data="monthly_sub")],
        [types.InlineKeyboardButton(text="Annual Subscription (3 months free)", callback_data="annual_sub")],
    ])
    try:
        if is_photo:
            await callback.message.edit_caption(caption="✅ Done! Here is your photo with new metadata.",
                                                reply_markup=keyboard)
        elif is_video:
            await callback.message.edit_caption(caption="✅ Done! Here is your video with new metadata.",
                                                reply_markup=keyboard)
        else:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        await callback.answer("Failed to go back.", show_alert=True)


@router.message(F.photo)
async def handle_photo(message: Message):
    logging.info(f"Received photo from {message.from_user.id}")
    cleanup_old_files()  # Очищаем старые файлы

    user_id = message.from_user.id

    # Удаляем предыдущий файл пользователя, если он есть
    if user_id in user_last_file:
        old_file_uuid = user_last_file[user_id].get('file_uuid')
        old_file_path = user_last_file[user_id].get('file_path')

        # Удаляем файл с диска
        if old_file_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                logging.info(f"Removed old file for user {user_id}: {old_file_path}")
            except Exception as e:
                logging.error(f"Error removing old file: {e}")

        # Удаляем из кэша
        if old_file_uuid and old_file_uuid in file_cache:
            del file_cache[old_file_uuid]
        if old_file_uuid and old_file_uuid in file_cache_times:
            del file_cache_times[old_file_uuid]

    photo = message.photo[-1]
    logging.info(f"Downloading photo {photo.file_id}")
    file = await message.bot.get_file(photo.file_id)
    file_path = file.file_path
    dest_path = os.path.join(TEMP_DIR, f"{photo.file_id}.jpg")
    await message.bot.download_file(file_path, dest_path)
    logging.info(f"Photo downloaded to {dest_path}")
    # Ensure user record exists and username is stored
    name = message.from_user.first_name or "Unknown"
    username = message.from_user.username
    await get_user(user_id, name, str(user_id), username)

    # Сохраняем в кэш
    file_uuid = str(uuid.uuid4())
    file_cache[file_uuid] = dest_path
    current_time = time.time()
    file_cache_times[file_uuid] = current_time

    # Сохраняем как последний файл пользователя
    user_last_file[user_id] = {
        'file_uuid': file_uuid,
        'file_path': dest_path
    }

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
        ],
        # Subscription buttons stacked full-width
        [
            types.InlineKeyboardButton(text="Ежемесячная подписка", callback_data=f"subscribe|monthly"),
        ],
        [
            types.InlineKeyboardButton(text="Годовая подписка (4 месяца бесплатно)", callback_data=f"subscribe|yearly"),
        ]
    ])
    await message.answer("File detected. How many copies do you want?", reply_markup=keyboard)


@router.message(F.video)
async def handle_video(message: Message):
    cleanup_old_files()  # Очищаем старые файлы

    video = message.video
    file_size_mb = video.file_size / (1024 * 1024) if video.file_size else 0

    # Проверяем размер файла (Telegram Bot API лимит 20 МБ)
    if video.file_size and video.file_size > 20 * 1024 * 1024:
        await message.answer(
            f"❌ Video file is too large ({file_size_mb:.1f} MB).\n\n"
            f"Telegram Bot API limit: 20 MB\n\n"
            f"Please send a smaller video or compress it first."
        )
        return

    user_id = message.from_user.id

    # Удаляем предыдущий файл пользователя, если он есть
    if user_id in user_last_file:
        old_file_uuid = user_last_file[user_id].get('file_uuid')
        old_file_path = user_last_file[user_id].get('file_path')

        # Удаляем файл с диска
        if old_file_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                logging.info(f"Removed old file for user {user_id}: {old_file_path}")
            except Exception as e:
                logging.error(f"Error removing old file: {e}")

        # Удаляем из кэша
        if old_file_uuid and old_file_uuid in file_cache:
            del file_cache[old_file_uuid]
        if old_file_uuid and old_file_uuid in file_cache_times:
            del file_cache_times[old_file_uuid]

    file = await message.bot.get_file(video.file_id)
    file_path = file.file_path
    ext = os.path.splitext(file_path)[1] or ".mp4"
    dest_path = os.path.join(TEMP_DIR, f"{video.file_id}{ext}")

    # Показываем прогресс
    progress_msg = await message.answer(f"⏳ Downloading video ({file_size_mb:.1f} MB)...")

    # Скачиваем с обработкой таймаута
    try:
        await message.bot.download_file(file_path, dest_path)
        await progress_msg.delete()
    except TimeoutError:
        await progress_msg.edit_text(
            f"❌ Timeout while downloading video ({file_size_mb:.1f} MB).\n\n"
            f"Please try a smaller file or check your connection."
        )
        return
    except Exception as e:
        logging.error(f"Error downloading video: {e}")
        await progress_msg.edit_text(f"❌ Error downloading video: {e}")
        return

    # Ensure user record exists and username is stored
    name = message.from_user.first_name or "Unknown"
    username = message.from_user.username
    await get_user(user_id, name, str(user_id), username)

    # Сохраняем в кэш
    file_uuid = str(uuid.uuid4())
    file_cache[file_uuid] = dest_path
    current_time = time.time()
    file_cache_times[file_uuid] = current_time

    # Сохраняем как последний файл пользователя
    user_last_file[user_id] = {
        'file_uuid': file_uuid,
        'file_path': dest_path
    }

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
        ],
        # Subscription buttons stacked full-width
        [
            types.InlineKeyboardButton(text="Monthly Subscription", callback_data=f"subscribe|monthly"),
        ],
        [
            types.InlineKeyboardButton(text="Annual Subscription (4 months free)", callback_data=f"subscribe|yearly"),
        ]
    ])
    await message.answer("File detected. How many copies do you want?", reply_markup=keyboard)


# URL handler for uploader links
@router.message(F.text)
async def handle_url(message: Message):
    """Обработчик для ссылок с uploader (DigitalOcean Spaces)"""
    text = message.text.strip()

    # Проверяем, что это ссылка на наш bucket
    if not (text.startswith("http://") or text.startswith("https://")):
        return  # Не URL, игнорируем

    # Проверяем, что это ссылка на наш Spaces bucket
    if S3_BUCKET_NAME not in text or "digitaloceanspaces.com" not in text:
        return  # Не наша ссылка, игнорируем

    user_id = message.from_user.id

    # Удаляем предыдущий файл пользователя, если он есть
    if user_id in user_last_file:
        old_file_uuid = user_last_file[user_id].get('file_uuid')
        old_file_path = user_last_file[user_id].get('file_path')

        if old_file_path and os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                logging.info(f"Removed old file for user {user_id}: {old_file_path}")
            except Exception as e:
                logging.error(f"Error removing old file: {e}")

        if old_file_uuid and old_file_uuid in file_cache:
            del file_cache[old_file_uuid]
        if old_file_uuid and old_file_uuid in file_cache_times:
            del file_cache_times[old_file_uuid]

    progress_msg = await message.answer("⏳ Downloading file from uploader...")

    try:
        # Скачиваем файл по URL
        async with aiohttp.ClientSession() as session:
            async with session.get(text) as resp:
                if resp.status != 200:
                    await progress_msg.edit_text(f"❌ Failed to download file: HTTP {resp.status}")
                    return

                # Определяем расширение по content-type или URL
                content_type = resp.headers.get('Content-Type', '')
                if 'image' in content_type:
                    ext = mimetypes.guess_extension(content_type) or '.jpg'
                    file_type = 'photo'
                elif 'video' in content_type:
                    ext = mimetypes.guess_extension(content_type) or '.mp4'
                    file_type = 'video'
                else:
                    # Пробуем определить по URL
                    url_ext = os.path.splitext(text.split('?')[0])[1].lower()
                    if url_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                        ext = url_ext
                        file_type = 'photo'
                    elif url_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                        ext = url_ext
                        file_type = 'video'
                    else:
                        await progress_msg.edit_text("❌ Unsupported file type. Please upload image or video.")
                        return

                # Сохраняем файл
                file_uuid = str(uuid.uuid4())
                dest_path = os.path.join(TEMP_DIR, f"{file_uuid}{ext}")

                with open(dest_path, 'wb') as f:
                    f.write(await resp.read())

                logging.info(f"Downloaded file from URL to {dest_path}")

        await progress_msg.delete()

        # Ensure user record exists
        name = message.from_user.first_name or "Unknown"
        username = message.from_user.username
        await get_user(user_id, name, str(user_id), username)

        # Сохраняем в кэш
        file_cache[file_uuid] = dest_path
        file_cache_times[file_uuid] = time.time()

        # Сохраняем как последний файл пользователя
        user_last_file[user_id] = {
            'file_uuid': file_uuid,
            'file_path': dest_path
        }

        # Предлагаем выбрать количество копий
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="5", callback_data=f"copies|5|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="10", callback_data=f"copies|10|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="20", callback_data=f"copies|20|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="30", callback_data=f"copies|30|{file_uuid}|{file_type}"),
            ],
            [
                types.InlineKeyboardButton(text="40", callback_data=f"copies|40|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="50", callback_data=f"copies|50|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="75", callback_data=f"copies|75|{file_uuid}|{file_type}"),
                types.InlineKeyboardButton(text="100", callback_data=f"copies|100|{file_uuid}|{file_type}"),
            ],
            [
                types.InlineKeyboardButton(text="120", callback_data=f"copies|120|{file_uuid}|{file_type}"),
            ],
            [
                types.InlineKeyboardButton(text="Monthly Subscription", callback_data=f"subscribe|monthly"),
            ],
            [
                types.InlineKeyboardButton(text="Annual Subscription (4 months free)",
                                           callback_data=f"subscribe|yearly"),
            ]
        ])
        await message.answer(
            f"✅ File downloaded successfully!\n\nFile type: {file_type}\n\nHow many copies do you want?",
            reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Error downloading file from URL: {e}")
        await progress_msg.edit_text(f"❌ Error downloading file: {e}")


# Обработчик текстовых сообщений
@router.message(F.text)
async def handle_text(message: Message):
    """Обработка текстовых сообщений - показываем приветственное сообщение"""
    user_id = message.from_user.id
    name = message.from_user.first_name or "Unknown"
    telegram_id = str(message.from_user.id)
    username = message.from_user.username

    try:
        user_data = await get_user(user_id, name, telegram_id, username)
        is_premium = user_data.get('is_premium', False)

        welcome_text = (
            "Welcome to @SludgeAI 🚀\n\n"
            "Create truly unique videos and images that algorithms won't flag as duplicates! Sludge AI automatically modifies your media files—altering metadata, applying subtle randomized visual changes, and ensuring every clip or image stands out as one-of-a-kind.\n\n"
            "The result? Greater reach and a better chance of landing on the FYP and in recommendations!\n\n"
            "Get started now: upload a video or photo from your gallery ⬇️\n\n"
            "👀 See real reviews and examples in @sludgevouches!\n\n"
            "Your content—your voice. Make it seen 🚀"
        )

        if not is_premium:
            files_used = user_data.get('files_today', 0)
            remaining = max(0, FREE_DAILY_LIMIT - files_used)
            welcome_text += f"\n\n📊 Files used today: {files_used}/{FREE_DAILY_LIMIT}\n📦 Remaining: {remaining}\n\n✨ Upgrade to premium for unlimited access: /pay 💎"

        await message.answer(welcome_text)
    except Exception as e:
        logging.error(f"Error getting user data in text handler: {e}")
        await message.answer(
            "Welcome to @SludgeAI 🚀\n\n"
            "Create truly unique videos and images that algorithms won't flag as duplicates! Sludge AI automatically modifies your media files—altering metadata, applying subtle randomized visual changes, and ensuring every clip or image stands out as one-of-a-kind.\n\n"
            "The result? Greater reach and a better chance of landing on the FYP and in recommendations!\n\n"
            "Get started now: upload a video or photo from your gallery ⬇️\n\n"
            "👀 See real reviews and examples in @sludgevouches!\n\n"
            "Your content—your voice. Make it seen 🚀"
        )


# Обработчик для неподдерживаемых сообщений
@router.message()
async def handle_unsupported(message: Message):
    logging.info(
        f"Received unsupported message from {message.from_user.id}: {message.text or message.caption or 'non-text'}")
    # For any unsupported message type, just inform user
    await message.answer("❌ Please send only photos or videos. Other types are not supported.")


# 2️⃣ Обработка кнопки (с путём к файлу)
# Note: download callback handler intentionally removed — download button is no longer used.

# Обработка выбора количества копий
@router.callback_query(F.data.startswith("copies|"))
async def process_copies(callback: CallbackQuery):
    cleanup_old_files()  # Очищаем старые файлы

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

    # Prepare containers for cleanup
    output_files = []
    file_names = []
    download_links = []
    session_id = str(uuid.uuid4())

    try:
        await callback.message.answer(f"⏳ Creating {count} copies...")

        name = callback.from_user.first_name or "Unknown"
        telegram_id = str(callback.from_user.id)
        username = getattr(callback.from_user, 'username', '') or ''

        # Try to reserve quota before heavy processing
        reserved = await increment_files(callback.from_user.id, count, name, telegram_id, username, enforce_limit=True)
        if not reserved:
            # Limit exceeded - get current usage to show user
            try:
                user_data = await get_user(callback.from_user.id, name, telegram_id, username)
                remaining = max(0, FREE_DAILY_LIMIT - user_data.get('files_today', 0))
            except Exception:
                remaining = 0
            await callback.message.answer(
                f"❌ You reached the limit of {FREE_DAILY_LIMIT} copies per day. You have {remaining} remaining. Upgrade to premium for unlimited access: /pay"
            )
            return

        import random, string
        def long_random_name(length=36):
            return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

        for i in range(count):
            try:
                logging.info(f"Creating copy {i + 1}")
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
                # record metrics per generated copy
                try:
                    size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
                    await metrics.record_file_processed(callback.from_user.id, size)
                except Exception as e:
                    logging.error(f"Failed to record metrics for user {callback.from_user.id} on copy {i + 1}: {e}")

                # Получаем presigned URL
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': S3_BUCKET_NAME, 'Key': key},
                    ExpiresIn=3600  # 1 час
                )
                logging.info(f"Presigned URL: {url[:50]}...")  # Log first 50 chars
                download_links.append(url)

            except Exception as e:
                logging.error(f"Error in copy {i + 1}: {e}")
                await callback.message.answer(f"❌ Error creating copy {i + 1}: {e}")

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

        # Получаем актуальную информацию о пользователе для отображения остатка
        try:
            user_data = await get_user(callback.from_user.id, name, telegram_id, username)
            files_used = user_data.get('files_today', 0)
            is_premium = user_data.get('is_premium', False)

            if is_premium:
                status_msg = "✅ Your copies are ready!\n\n🔗 View and download: {url}\n\n⭐ Premium: Unlimited copies"
            else:
                remaining = max(0, FREE_DAILY_LIMIT - files_used)
                status_msg = f"✅ Your copies are ready!\n\n🔗 View and download: {{url}}\n\n📊 Files used today: {files_used}/{FREE_DAILY_LIMIT}\n📦 Remaining: {remaining}"

            await callback.message.answer(status_msg.format(url=page_url))
        except Exception as e:
            logging.error(f"Failed to get user stats: {e}")
            await callback.message.answer(f"✅ Your copies are ready! View and download them here: {page_url}")

    except Exception as e:
        logging.error(f"Error in process_copies: {e}")
        await callback.answer(f"❌ Error: {e}", show_alert=True)
    finally:
        # Удаляем временные файлы и очищаем кэш в любом случае
        try:
            for f in output_files:
                if os.path.exists(f):
                    os.remove(f)
            # original uploaded file
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            # cleanup cache entries if present
            try:
                if file_uuid in file_cache:
                    del file_cache[file_uuid]
                if file_uuid in file_cache_times:
                    del file_cache_times[file_uuid]
            except Exception:
                pass
        except Exception as e:
            logging.error(f"Error cleaning up files in finally: {e}")
