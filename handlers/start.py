from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from config import UPLOADER_URL

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Welcome to @SludgeAI 🚀\n\n"
        "Create truly unique videos and images that algorithms won't flag as duplicates! Sludge AI automatically modifies your media files—altering metadata, applying subtle randomized visual changes, and ensuring every clip or image stands out as one-of-a-kind.\n\n"
        "The result? Greater reach and a better chance of landing on the FYP and in recommendations!\n\n"
        "Get started now: upload a video or photo from your gallery ⬇️\n\n"
        f"📁 For files larger than 20MB, use our uploader: {UPLOADER_URL}\n"
        "After uploading, send me the link you receive!\n\n"
        "👀 See real reviews and examples in @sludgevouches!\n\n"
        "Your content—your voice. Make it seen 🚀"
    )
