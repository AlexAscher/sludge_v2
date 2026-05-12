from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from db import get_user
from config import FREE_DAILY_LIMIT

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Unknown"
    telegram_id = str(message.from_user.id)
    username = message.from_user.username

    try:
        user_data = await get_user(user_id, name, telegram_id, username)
        is_premium = user_data.get('is_premium', False)
        files_used = user_data.get('files_today', 0)

        welcome_text = (
            "Добро пожаловать в FYP Repurpose 🥷\n\n"
            "Создавайте незаметные копии фото и видео, которые алгоритмы не помечают как дубликаты.\n\n"
            "Мы автоматически меняем метаданные и вносим незаметные уникальные правки в каждый файл. Результат: больший охват, больше просмотров и выше шанс попасть в FYP!\n\n"
            "✅ Реальные примеры и подтверждения: @fypvouches\n"
            "✅ Просто отправьте фото или видео, чтобы начать!\n\n"
        )

        if is_premium:
            welcome_text += "⭐ Премиум: безлимитные копии\n\n"
        else:
            welcome_text += f"📊 Сегодня бесплатно: использовано {files_used}/{FREE_DAILY_LIMIT}\n"
            welcome_text += "✨ Нужен безлимит? Введите /pay\n\n"

        welcome_text += "Ваш контент. Ваш голос. Наконец-то замечен. 🚀"

        await message.answer(welcome_text)
    except Exception as e:
        # Fallback если не удалось получить данные пользователя
        await message.answer(
            "Добро пожаловать в FYP Repurpose 🥷\n\n"
            "Создавайте незаметные копии фото и видео, которые алгоритмы не помечают как дубликаты.\n\n"
            "Мы автоматически меняем метаданные и вносим незаметные уникальные правки в каждый файл. Результат: больший охват, больше просмотров и выше шанс попасть в FYP!\n\n"
            "✅ Реальные примеры и подтверждения: @fypvouches\n"
            "✅ Просто отправьте фото или видео, чтобы начать!\n\n"
            "📊 Сегодня бесплатно: использовано 0/100\n"
            "✨ Нужен безлимит? Введите /pay\n\n"
            "Ваш контент. Ваш голос. Наконец-то замечен. 🚀"
        )
