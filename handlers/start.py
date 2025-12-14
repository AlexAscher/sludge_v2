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
            "Welcome to FYP Repurpose 🥷\n\n"
            "Create undetectable, algorithm-proof copies of your photos and videos — so your content never gets flagged as duplicate.\n\n"
            "We automatically modify metadata and apply invisible, unique tweaks to every file. The result? Higher reach, more views, and better chances to hit the FYP!\n\n"
            "✅ See real examples and proof: @fypvouches\n"
            "✅ Just send a photo or video to get started!\n\n"
        )

        if is_premium:
            welcome_text += "⭐ Premium: Unlimited copies\n\n"
        else:
            welcome_text += f"📊 Free today: {files_used}/{FREE_DAILY_LIMIT} used\n"
            welcome_text += "✨ Want unlimited? Type /pay\n\n"

        welcome_text += "Your content. Your voice. Finally seen. 🚀"

        await message.answer(welcome_text)
    except Exception as e:
        # Fallback если не удалось получить данные пользователя
        await message.answer(
            "Welcome to FYP Repurpose 🥷\n\n"
            "Create undetectable, algorithm-proof copies of your photos and videos — so your content never gets flagged as duplicate.\n\n"
            "We automatically modify metadata and apply invisible, unique tweaks to every file. The result? Higher reach, more views, and better chances to hit the FYP!\n\n"
            "✅ See real examples and proof: @fypvouches\n"
            "✅ Just send a photo or video to get started!\n\n"
            "📊 Free today: 0/100 used\n"
            "✨ Want unlimited? Type /pay\n\n"
            "Your content. Your voice. Finally seen. 🚀"
        )
