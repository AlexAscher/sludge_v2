import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from config import BOT_TOKEN, CRYPTOBOT_TOKEN
from handlers import start, help, process
from db import get_user, increment_files, set_premium, init_db
from aiosend import CryptoPay, TESTNET
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logging.basicConfig(level=logging.INFO)

# Глобальные переменные для платежей
pending_payments = {}  # user_id: invoice_id


async def check_payments(bot: Bot, cryptopay: CryptoPay):
    """Проверяет статус платежей и обновляет премиум"""
    for user_id, invoice_id in list(pending_payments.items()):
        try:
            invoice = await cryptopay.get_invoice(invoice_id)
            if invoice.status == 'paid':
                await set_premium(user_id, True)
                await bot.send_message(user_id, "✅ Payment received! You now have unlimited access.")
                del pending_payments[user_id]
        except Exception as e:
            logging.error(f"Error checking payment for {user_id}: {e}")


async def limit_middleware(handler, event, data):
    """Middleware для проверки лимита файлов"""
    if isinstance(event, types.Message) and event.text and not event.text.startswith('/'):
        user_id = event.from_user.id
        name = event.from_user.first_name or "Unknown"
        telegram_id = event.from_user.id
        username = getattr(event.from_user, 'username', '') or ''
        user_data = await get_user(user_id, name, telegram_id, username)

        if not user_data['is_premium']:
            if user_data['files_today'] >= 20:
                await event.answer(
                    "❌ You reached the limit of 20 copies per day. Pay 0.05 USDT for unlimited access: /pay")
                return
            else:
                remaining = 20 - user_data['files_today']
                if remaining in [20, 15, 10, 5, 3, 2, 1]:
                    await event.answer(
                        f"ℹ️ You have {remaining} copies left today. For unlimited access, pay 0.05 USDT: /pay")

    return await handler(event, data)


async def pay_command(message: types.Message, cryptopay: CryptoPay):
    """Команда /pay для создания инвойса"""
    user_id = message.from_user.id

    # Создаем инвойс на 0.05 USDT
    invoice = await cryptopay.create_invoice(
        amount=0.05,
        currency='USDT',
        description='Subscription for unlimited access to the bot'
    )

    pending_payments[user_id] = invoice.invoice_id

    # Send payment link
    text = f"💳 Pay 0.05 USDT for unlimited access.\n\n{invoice.pay_url}\n\nYour status will be updated automatically after payment."
    await message.answer(text)


async def main():
    # Инициализация базы данных и аутентификация
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()

    # Инициализация CryptoPay
    cryptopay = CryptoPay(CRYPTOBOT_TOKEN, TESTNET)

    # Регистрируем middleware
    dp.message.middleware(limit_middleware)

    # Регистрируем хендлеры
    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(process.router)

    # Команда оплаты
    dp.message.register(lambda msg: pay_command(msg, cryptopay), Command("pay"))

    # Планировщик для проверки платежей каждые 30 секунд
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_payments, IntervalTrigger(seconds=30), args=[bot, cryptopay])
    scheduler.start()

    print("🤖 Bot started with payment system...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
