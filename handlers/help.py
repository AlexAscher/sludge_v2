from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "❓ FYP REPURPOSE FAQ ❓\n\n"

        "Every photo and video you process gets its metadata randomized and invisible, algorithm-proof tweaks applied. "
        "The result? Social media platforms see each copy as unique, original content — never flagged as duplicate.\n\n"

        "📖 How to Use:\n"
        "1️⃣ Send a photo or video from your gallery (up to 20MB)\n"
        "2️⃣ Choose how many copies you want (5, 10, 20, 30, 40, 50, 75, 100, or 120)\n"
        "3️⃣ Wait while our servers process your files\n"
        "4️⃣ Get a download link with all your unique copies in one place!\n\n"

        "🔧 What Gets Changed:\n"
        "📸 Photos:\n"
        "  • EXIF metadata (Artist, Copyright, DateTime, etc.)\n"
        "  • Micro-adjustments to brightness, contrast, color\n"
        "  • One random pixel replaced with random color\n"
        "  • Result: Visually identical, but unique hash\n\n"

        "🎥 Videos:\n"
        "  • Metadata (Title, Artist, Comment)\n"
        "  • Ultra-subtle brightness/contrast/saturation changes\n"
        "  • Noise filter and one random pixel replacement\n"
        "  • Result: Looks the same, recognized as unique\n\n"

        "💧 Watermark (Optional):\n"
        "  • Text watermark: Add your channel name or text\n"
        "  • Image watermark: Add your logo or signature\n"
        "  • Choose position: top-left, center, bottom-right, etc.\n\n"

        "💎 Free vs Premium:\n"
        "  • Free: 100 copies per day\n"
        "  • Premium: Unlimited copies\n"
        "  • Type /pay to upgrade\n\n"

        "⚠️ Errors & Issues:\n"
        "If the bot doesn't respond or freezes:\n"
        "  • Wait a few seconds — you might be in queue\n"
        "  • Video too large? Use our uploader: https://uploader.fypaccs.shop/\n"
        "  • Still having issues? Contact support\n\n"

        "📋 Available Commands:\n"
        "/start - Start the bot and see your usage stats\n"
        "/help - Display this help message\n"
        "/pay - Upgrade to premium for unlimited copies\n"
        "/stats - View your usage statistics\n\n"

        "✅ See real results: @fypvouches\n"
        "Your content. Your voice. Finally seen. 🚀"
    )
