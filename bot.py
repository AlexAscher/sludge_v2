import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from config import BOT_TOKEN, CRYPTOBOT_TOKEN
from handlers import start, help, process
from db import get_user, increment_files, set_premium
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
                await bot.send_message(user_id, "✅ Оплата прошла! Теперь у вас безлимитный доступ.")
                del pending_payments[user_id]
        except Exception as e:
            logging.error(f"Error checking payment for {user_id}: {e}")


async def limit_middleware(handler, event, data):
    """Middleware для проверки лимита файлов"""
    if isinstance(event, types.Message) and event.text and not event.text.startswith('/'):
        user_id = event.from_user.id
        user_data = await get_user(user_id)

        if not user_data['is_premium']:
            if user_data['files_today'] >= 20:
                await event.answer(
                    "❌ Вы достигли лимита 20 копий в день. Оплатите подписку за 0.05 USDT для безлимитного доступа: /pay")
                return
            else:
                remaining = 20 - user_data['files_today']
                if remaining in [20, 15, 10, 5, 3, 2, 1]:
                    await event.answer(
                        f"ℹ️ У вас осталось {remaining} копий в день. Для безлимитного доступа оплатите 0.05 USDT: /pay")

    return await handler(event, data)


async def pay_command(message: types.Message, cryptopay: CryptoPay):
    """Команда /pay для создания инвойса"""
    user_id = message.from_user.id

    # Создаем инвойс на 0.05 USDT
    invoice = await cryptopay.create_invoice(
        amount=0.05,
        currency='USDT',
        description='Подписка на безлимитный доступ к боту'
    )

    pending_payments[user_id] = invoice.invoice_id

    # Отправляем ссылку на оплату
    text = f"💳 Оплатите 0.05 USDT для безлимитного доступа.\n\n{invoice.pay_url}\n\nПосле оплаты статус обновится автоматически."
    await message.answer(text)


async def main():
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
