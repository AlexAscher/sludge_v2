import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, CRYPTOBOT_TOKEN
from handlers import start, help, process, stats
from db import get_user, increment_files, set_premium, init_db, get_expired_users, pb
from aiosend import CryptoPay, TESTNET
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import functools
from services import metrics

logging.basicConfig(level=logging.INFO)

# Глобальные переменные для платежей
pending_payments = {}  # user_id: invoice_id


async def check_payments(bot: Bot, cryptopay: CryptoPay):
    """Проверяет статус платежей и обновляет премиум"""
    for user_id, invoice_id in list(pending_payments.items()):
        try:
            invoice = await cryptopay.get_invoice(invoice_id)
            if invoice.status == 'paid':
                await set_premium(user_id, True, 30)  # 30 seconds premium
                await metrics.record_premium_purchase(user_id)
                await bot.send_message(user_id, "✅ Payment received! You now have unlimited access for 30 seconds.")
                del pending_payments[user_id]
        except Exception as e:
            logging.error(f"Error checking payment for {user_id}: {e}")


async def check_expired_premiums(bot: Bot):
    """Проверяет истекшие премиумы и отправляет уведомления"""
    expired_users = await get_expired_users()
    print(f"check_expired_premiums: found {len(expired_users)} expired users")
    for user in expired_users:
        user_id = user.user_id
        try:
            print(f"Will clear premium for user {user_id} (record id {user.id})")
            # Сбросить премиум
            res = pb.collection('users').update(user.id,
                                                {'is_premium': False, 'premium_end': None, 'expiry_notified': True})
            print(f"Update response for {user_id}: {getattr(res, 'id', res)}")
            # Отправить сообщение с кнопками
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Yes", callback_data="renew_yes")],
                [InlineKeyboardButton(text="No", callback_data="renew_no")]
            ])
            await bot.send_message(user_id, "Your subscription has expired. Do you want to renew?",
                                   reply_markup=keyboard)
        except Exception as e:
            logging.error(f"Error processing expired premium for {user_id}: {e}")


async def limit_middleware(handler, event, data):
    """Middleware для проверки лимита файлов"""
    logging.info(f"Middleware: received message from {event.from_user.id}: '{event.text}'")
    if isinstance(event, types.Message) and event.text and not event.text.startswith('/'):
        user_id = event.from_user.id
        name = event.from_user.first_name or "Unknown"
        telegram_id = event.from_user.id
        username = getattr(event.from_user, 'username', '') or ''
        user_data = await get_user(user_id, name, telegram_id, username)

        if not user_data['is_premium']:
            if user_data['files_today'] >= 20:
                await event.answer(
                    "❌ You reached the limit of 20 copies per day. Pay 0.05 USDT for unlimited access for 30 seconds: /pay")
                return
            else:
                remaining = 20 - user_data['files_today']
                if remaining in [20, 15, 10, 5, 3, 2, 1]:
                    await event.answer(
                        f"ℹ️ You have {remaining} copies left today. For unlimited access for 30 seconds, pay 0.05 USDT: /pay")

    return await handler(event, data)


async def pay_command(cryptopay: CryptoPay, message: types.Message):
    """Команда /pay для создания инвойса"""
    user_id = message.from_user.id

    # Создаем инвойс на 0.05 USDT
    invoice = await cryptopay.create_invoice(
        amount=0.05,
        asset='USDT',
        description='Subscription for unlimited access to the bot'
    )

    pending_payments[user_id] = invoice.invoice_id

    # Send payment link
    text = f"💳 Pay 0.05 USDT for unlimited access for 30 seconds.\n\n{invoice.pay_url}\n\nYour status will be updated automatically after payment."
    await message.answer(text)


async def callback_handler(cryptopay: CryptoPay, callback: types.CallbackQuery):
    """Обработчик callback для продления подписки"""
    user_id = callback.from_user.id
    if callback.data == "renew_yes":
        try:
            # Создаем инвойс прямо при клике на "Да"
            invoice = await cryptopay.create_invoice(
                amount=0.05,
                asset='USDT',
                description='Subscription for unlimited access to the bot'
            )
            pending_payments[user_id] = invoice.invoice_id

            # Отправляем платежную ссылку
            text = f"💳 Pay 0.05 USDT for unlimited access for 30 seconds.\n\n{invoice.pay_url}\n\nYour status will be updated automatically after payment."
            await callback.message.edit_text(text)
        except Exception as e:
            logging.error(f"Error creating invoice for {user_id}: {e}")
            await callback.answer("Error creating payment link. Try /pay command.")
    elif callback.data == "renew_no":
        # Remove the question message and send the main informational/start message
        try:
            await callback.message.delete()
        except Exception:
            pass
        main_text = (
            "Welcome to @SludgeAI 🚀\n\n"
            "Create truly unique videos and images that algorithms won’t flag as duplicates! Sludge AI automatically modifies your media files—altering metadata, applying subtle randomized visual changes, and ensuring every clip or image stands out as one-of-a-kind.\n\n"
            "The result? Greater reach and a better chance of landing on the FYP and in recommendations!\n\n"
            "Get started now: upload a video or photo from your gallery ⬇️\n\n"
            "👀 See real reviews and examples in @sludgevouches!\n\n"
            "Your content—your voice. Make it seen 🚀"
        )
        await callback.message.bot.send_message(user_id, main_text)
    else:
        await callback.message.edit_reply_markup(reply_markup=None)


async def main():
    logging.info("Starting bot main function")
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
    dp.include_router(stats.router)
    dp.include_router(process.router)
    logging.info("All routers included: start, help, stats, process")

    # Команда оплаты
    dp.message.register(functools.partial(pay_command, cryptopay), Command("pay"))

    # Обработчик callback
    dp.callback_query.register(functools.partial(callback_handler, cryptopay),
                               lambda c: c.data in ["renew_yes", "renew_no"])

    # Планировщик для проверки платежей каждые 30 секунд
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_payments, IntervalTrigger(seconds=30), args=[bot, cryptopay])
    scheduler.add_job(check_expired_premiums, IntervalTrigger(seconds=60), args=[bot])
    scheduler.start()

    print("🤖 Bot started with payment system...")
    # Set bot commands
    try:
        await bot.set_my_commands([
            types.BotCommand(command="start", description="Start the bot"),
            types.BotCommand(command="help", description="Get help"),
            types.BotCommand(command="pay", description="Pay for premium access"),
            types.BotCommand(command="stats", description="Get usage statistics"),
        ])
        logging.info("Bot commands set successfully")
    except Exception as e:
        logging.error(f"Failed to set bot commands: {e}")
    logging.info("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
