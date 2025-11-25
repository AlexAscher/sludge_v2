# ...existing code...


from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery
## download_video больше не используется
from services.video_edit import randomize_metadata
from services.photo_edit import randomize_exif
from services.watermark import add_watermark_image, add_watermark_video, add_image_watermark_image, \
    add_image_watermark_video, WATERMARK_POSITIONS
import mimetypes
import aiohttp
import os
import uuid
import boto3
import time
from config import TEMP_DIR, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION, S3_ENDPOINT, \
    FREE_DAILY_LIMIT
from collections import defaultdict
import zipfile
import shutil
from db import increment_files, get_user
from services import metrics

router = Router()

file_cache = {}
file_cache_times = {}

user_files = defaultdict(list)  # {user_id: [file_paths]}

# Состояние для Watermark: {user_id: {'file_path': path, 'file_type': 'photo/video', 'step': 'choosing_type', 'watermark_type': 'text/image'}}
watermark_state = defaultdict(dict)


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

    # Проверяем, ожидаем ли мы изображение для водяного знака
    if user_id in watermark_state and watermark_state[user_id]['step'] == 'waiting_image':
        await handle_watermark_image(message)
        return

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
        [
            types.InlineKeyboardButton(text="💧 Add Watermark", callback_data=f"watermark|{file_uuid}|photo"),
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
    file = await message.bot.get_file(video.file_id)
    file_path = file.file_path
    ext = os.path.splitext(file_path)[1] or ".mp4"
    dest_path = os.path.join(TEMP_DIR, f"{video.file_id}{ext}")
    await message.bot.download_file(file_path, dest_path)
    # Ensure user record exists and username is stored
    user_id = message.from_user.id
    name = message.from_user.first_name or "Unknown"
    username = message.from_user.username
    await get_user(user_id, name, str(user_id), username)

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
        ],
        [
            types.InlineKeyboardButton(text="💧 Add Watermark", callback_data=f"watermark|{file_uuid}|video"),
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


# Watermark handlers
@router.callback_query(F.data.startswith("watermark|"))
async def start_watermark(callback: CallbackQuery):
    """Начало процесса добавления водяного знака"""
    try:
        parts = callback.data.split("|")
        if len(parts) != 3:
            await callback.answer("Invalid data", show_alert=True)
            return

        _, file_uuid, file_type = parts
        filepath = file_cache.get(file_uuid)
        if not filepath:
            await callback.answer("File not found", show_alert=True)
            return

        user_id = callback.from_user.id
        watermark_state[user_id] = {
            'file_path': filepath,
            'file_type': file_type,
            'file_uuid': file_uuid,
            'step': 'choosing_type'
        }

        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="📝 Text Watermark", callback_data="watermark_type|text"),
                types.InlineKeyboardButton(text="🖼️ Image Watermark", callback_data="watermark_type|image")
            ],
            [types.InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_watermark")]
        ])

        await callback.message.edit_text(
            "💧 Watermark Mode\n\n"
            "Choose the type of watermark you want to add:",
            reply_markup=keyboard
        )

    except Exception as e:
        logging.error(f"Watermark start error: {e}")
        await callback.answer("Error starting watermark process", show_alert=True)


@router.callback_query(F.data.startswith("watermark_type|"))
async def choose_watermark_type(callback: CallbackQuery):
    """Выбор типа водяного знака"""
    try:
        parts = callback.data.split("|")
        if len(parts) != 2:
            await callback.answer("Invalid data", show_alert=True)
            return

        _, watermark_type = parts
        user_id = callback.from_user.id

        if user_id not in watermark_state:
            await callback.answer("Session expired", show_alert=True)
            return

        watermark_state[user_id]['watermark_type'] = watermark_type

        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_watermark")]
        ])

        if watermark_type == 'text':
            watermark_state[user_id]['step'] = 'waiting_text'
            await callback.message.edit_text(
                "📝 Text Watermark\n\n"
                "Send me the text you want to use as a watermark.\n"
                "Example: @YourChannel, Your Name, etc.\n\n"
                "📏 Maximum 50 characters",
                reply_markup=keyboard
            )
        elif watermark_type == 'image':
            watermark_state[user_id]['step'] = 'waiting_image'
            await callback.message.edit_text(
                "🖼️ Image Watermark\n\n"
                "Send me an image to use as a watermark.\n"
                "Best formats: PNG with transparent background\n\n"
                "💡 Tip: Use your logo or signature image",
                reply_markup=keyboard
            )

    except Exception as e:
        logging.error(f"Watermark type selection error: {e}")
        await callback.answer("Error selecting watermark type", show_alert=True)


@router.callback_query(F.data == "cancel_watermark")
async def cancel_watermark(callback: CallbackQuery):
    """Отмена добавления водяного знака"""
    user_id = callback.from_user.id

    # Очищаем состояние и временные файлы
    if user_id in watermark_state:
        state = watermark_state[user_id]
        # Удаляем временный файл водяного знака если есть
        if 'watermark_image_path' in state and os.path.exists(state['watermark_image_path']):
            os.remove(state['watermark_image_path'])

        del watermark_state[user_id]

    await callback.message.edit_text(
        "❌ Watermark cancelled.\n\n"
        "Send me a photo or video to get started."
    )


@router.callback_query(F.data.startswith("watermark_pos|"))
async def choose_watermark_position(callback: CallbackQuery):
    """Выбор позиции водяного знака"""
    try:
        parts = callback.data.split("|")
        if len(parts) != 2:
            await callback.answer("Invalid data", show_alert=True)
            return

        _, position = parts
        user_id = callback.from_user.id

        if user_id not in watermark_state:
            await callback.answer("Session expired", show_alert=True)
            return

        state = watermark_state[user_id]
        watermark_type = state.get('watermark_type', 'text')
        file_path = state['file_path']
        file_type = state['file_type']

        await callback.message.edit_text("🔄 Adding watermark... Please wait.")

        try:
            # Добавляем водяной знак в зависимости от типа
            if watermark_type == 'text':
                text = state['watermark_text']
                if file_type == 'photo':
                    result_path = add_watermark_image(file_path, text, position)
                else:  # video
                    result_path = add_watermark_video(file_path, text, position)
            else:  # image watermark
                watermark_image_path = state['watermark_image_path']
                if file_type == 'photo':
                    result_path = add_image_watermark_image(file_path, watermark_image_path, position)
                else:  # video
                    result_path = add_image_watermark_video(file_path, watermark_image_path, position)

            # Загружаем результат в S3 — сохраняем реальное расширение и ContentType
            import mimetypes as _mimetypes
            session_id = str(uuid.uuid4())
            # используем расширение из result_path, если оно есть
            ext = os.path.splitext(result_path)[1].lstrip('.') or ('mp4' if file_type == 'video' else 'jpg')
            random_name = f"watermarked_{watermark_type}_{uuid.uuid4().hex}.{ext}"
            key = f"{session_id}/{random_name}"

            guessed_type = _mimetypes.guess_type(result_path)[0]
            # безопасный fallback
            if guessed_type is None:
                if file_type == 'photo':
                    guessed_type = 'image/png' if ext == 'png' else 'image/jpeg'
                else:
                    guessed_type = 'video/mp4'

            s3_client.upload_file(result_path, S3_BUCKET_NAME, key,
                                  ExtraArgs={'ContentType': guessed_type})

            # Record metrics: count file and bytes uploaded
            try:
                size = os.path.getsize(result_path) if os.path.exists(result_path) else 0
                await metrics.record_file_processed(callback.from_user.id, size)
            except Exception as e:
                logging.error(f"Failed to record metrics for user {callback.from_user.id}: {e}")

            # Получаем presigned URL
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET_NAME, 'Key': key},
                ExpiresIn=3600
            )

            # Отправляем результат
            watermark_emoji = "📝" if watermark_type == 'text' else "🖼️"

            if file_type == 'photo':
                await callback.message.bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=url,
                    caption=f"✅ {watermark_emoji} Watermark added!\nDownload: {url}"
                )
            else:
                await callback.message.answer(
                    f"✅ {watermark_emoji} Video watermark completed!\n\n"
                    f"Download: {url}\n\n"
                    f"Link valid for 1 hour."
                )

            # Increment user counters: watermarking counts as one processed file
            try:
                name = callback.from_user.first_name or "Unknown"
                telegram_id = str(callback.from_user.id)
                username = getattr(callback.from_user, 'username', '') or ''
                await increment_files(callback.from_user.id, 1, name, telegram_id, username)
            except Exception as e:
                logging.error(f"Failed to increment files for user {callback.from_user.id}: {e}")

            # Очищаем временные файлы
            try:
                if os.path.exists(result_path):
                    os.remove(result_path)
            except Exception:
                pass
            if watermark_type == 'image' and 'watermark_image_path' in state:
                if os.path.exists(state['watermark_image_path']):
                    os.remove(state['watermark_image_path'])
            # Удаляем оригинальный файл и кэш (если был сохранён)
            try:
                file_uuid = state.get('file_uuid')
                orig_path = state.get('file_path')
                if orig_path and os.path.exists(orig_path):
                    try:
                        os.remove(orig_path)
                    except Exception:
                        pass
                if file_uuid and file_uuid in file_cache:
                    try:
                        del file_cache[file_uuid]
                    except Exception:
                        pass
                if file_uuid and file_uuid in file_cache_times:
                    try:
                        del file_cache_times[file_uuid]
                    except Exception:
                        pass
            except Exception:
                pass

            # Очищаем состояние
            del watermark_state[user_id]

        except Exception as e:
            logging.error(f"Watermark processing error: {e}")
            await callback.message.edit_text(f"❌ Watermark failed: {str(e)}")
            # Очищаем временные файлы при ошибке
            if watermark_type == 'image' and 'watermark_image_path' in state:
                if os.path.exists(state['watermark_image_path']):
                    try:
                        os.remove(state['watermark_image_path'])
                    except Exception:
                        pass
            # Удаляем оригинальный файл и кэш (если есть)
            try:
                file_uuid = state.get('file_uuid')
                orig_path = state.get('file_path')
                if orig_path and os.path.exists(orig_path):
                    try:
                        os.remove(orig_path)
                    except Exception:
                        pass
                if file_uuid and file_uuid in file_cache:
                    try:
                        del file_cache[file_uuid]
                    except Exception:
                        pass
                if file_uuid and file_uuid in file_cache_times:
                    try:
                        del file_cache_times[file_uuid]
                    except Exception:
                        pass
            except Exception:
                pass
            del watermark_state[user_id]

    except Exception as e:
        logging.error(f"Watermark position error: {e}")
        await callback.answer("Error processing watermark", show_alert=True)


# Обработчик текстовых сообщений для watermark
@router.message(F.text)
async def handle_watermark_text(message: Message):
    """Обработка текста для водяного знака"""
    user_id = message.from_user.id

    # Проверяем, ожидаем ли мы текст для водяного знака
    if user_id in watermark_state and watermark_state[user_id]['step'] == 'waiting_text':
        text = message.text.strip()

        if len(text) > 50:
            await message.answer("❌ Text too long. Please use up to 50 characters.")
            return

        if len(text) < 1:
            await message.answer("❌ Please enter some text.")
            return

        # Сохраняем текст и переходим к выбору позиции
        watermark_state[user_id]['watermark_text'] = text
        watermark_state[user_id]['step'] = 'choosing_position'

        # Создаем клавиатуру с позициями
        keyboard_rows = []
        positions = list(WATERMARK_POSITIONS.items())

        # Группируем по 3 кнопки в ряд
        for i in range(0, len(positions), 3):
            row = []
            for j in range(3):
                if i + j < len(positions):
                    pos_key, pos_name = positions[i + j]
                    row.append(types.InlineKeyboardButton(
                        text=pos_name,
                        callback_data=f"watermark_pos|{pos_key}"
                    ))
            keyboard_rows.append(row)

        # Добавляем кнопку отмены
        keyboard_rows.append([
            types.InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_watermark")
        ])

        keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        await message.answer(
            f"✅ Text watermark: \"{text}\"\n\n"
            f"Now choose the position for your watermark:",
            reply_markup=keyboard
        )

        return

    # Если не в режиме watermark, показываем приветственное сообщение
    # и статус использования для не-премиум пользователей
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


# Обработчик изображений для watermark
async def handle_watermark_image(message: Message):
    """Обработка изображения для водяного знака"""
    user_id = message.from_user.id

    # Проверяем, ожидаем ли мы изображение для водяного знака
    if user_id in watermark_state and watermark_state[user_id]['step'] == 'waiting_image':
        try:
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            file_path = file.file_path

            # Сохраняем водяной знак
            watermark_path = os.path.join(TEMP_DIR, f"watermark_{photo.file_id}.jpg")
            await message.bot.download_file(file_path, watermark_path)

            # Сохраняем путь к водяному знаку
            watermark_state[user_id]['watermark_image_path'] = watermark_path
            watermark_state[user_id]['step'] = 'choosing_position'

            # Создаем клавиатуру с позициями
            keyboard_rows = []
            positions = list(WATERMARK_POSITIONS.items())

            # Группируем по 3 кнопки в ряд
            for i in range(0, len(positions), 3):
                row = []
                for j in range(3):
                    if i + j < len(positions):
                        pos_key, pos_name = positions[i + j]
                        row.append(types.InlineKeyboardButton(
                            text=pos_name,
                            callback_data=f"watermark_pos|{pos_key}"
                        ))
                keyboard_rows.append(row)

            # Добавляем кнопку отмены
            keyboard_rows.append([
                types.InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_watermark")
            ])

            keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            await message.answer(
                f"✅ Image watermark saved!\n\n"
                f"Now choose the position for your watermark:",
                reply_markup=keyboard
            )

        except Exception as e:
            logging.error(f"Error handling watermark image: {e}")
            await message.answer("❌ Error processing watermark image. Please try again.")

        return


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
