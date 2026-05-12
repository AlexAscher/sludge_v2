from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from services import metrics
import asyncio
import logging

router = Router()
logging.info("Stats router created")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Generate metrics report (TXT) and send as a file to the requester."""
    logging.info(f"Stats command triggered by user {message.from_user.id}")
    await message.answer("Готовлю отчёт... Это может занять немного времени.")
    logging.info("Starting report generation")
    # Generate and save report
    path = await metrics.save_report_to_file()
    logging.info(f"Report saved to {path}")
    # Print report contents to logs for debugging
    try:
        with open(path, 'r', encoding='utf-8') as f:
            report_content = f.read()
        logging.info(f"Report content length: {len(report_content)} chars")
        logging.info(f"Report content preview:\n{report_content[:500]}...")
    except Exception as e:
        logging.error(f"Failed to read report: {e}")

    # Send the file
    try:
        logging.info("Attempting to send document")
        document = FSInputFile(path)
        await message.answer_document(document)
        logging.info("Report sent successfully")
    except Exception as e:
        logging.error(f"Failed to send report: {e}")
        await message.answer("Отчёт создан, но не удалось отправить файл. Проверьте логи.", parse_mode=None)
