import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, CRYPTOBOT_TOKEN, FREE_DAILY_LIMIT
import aiohttp
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
pending_payments = {}  # invoice_id -> { user_id, duration, plan }


async def check_payments(bot: Bot, cryptopay: CryptoPay):
    """Проверяет статус платежей и обновляет премиум"""
    # pending_payments now keyed by invoice_id -> payload
    for invoice_id, payload in list(pending_payments.items()):
        try:
            invoice = await cryptopay.get_invoice(invoice_id)
            if invoice.status == 'paid':
                user_id = payload.get('user_id')
                duration = payload.get('duration', 30)
                plan = payload.get('plan', 'unknown')
                await set_premium(user_id, True, duration)
                await metrics.record_premium_purchase(user_id)
                await bot.send_message(user_id, f"✅ Payment received! You now have premium ({plan})")
                # remove by invoice_id
                del pending_payments[invoice_id]
        except Exception as e:
            logging.error(f"Error checking payment for invoice {invoice_id}: {e}")


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
    # Limit checking is now handled in individual handlers (process.py)
    return await handler(event, data)


async def pay_command(cryptopay: CryptoPay, message: types.Message):
    """Команда /pay для создания инвойса"""
    user_id = message.from_user.id

    # Создаем инвойс на 0.05 USDT (temporary unlimited for 30 seconds)
    invoice = await cryptopay.create_invoice(
        amount=0.05,
        asset='USDT',
        description='Temporary unlimited access (30 seconds)'
    )

    # Store payload keyed by invoice_id so check_payments can grant correct duration
    pending_payments[invoice.invoice_id] = {'user_id': user_id, 'duration': 30, 'plan': 'temporary'}

    # Send payment link
    text = f"💳 Pay 0.05 USDT for temporary unlimited access (30 seconds).\n\n{invoice.pay_url}\n\nYour status will be updated automatically after payment."
    await message.answer(text)


async def callback_handler(cryptopay: CryptoPay, callback: types.CallbackQuery):
    """Обработчик callback для продления подписки"""
    user_id = callback.from_user.id
    if callback.data == "renew_yes":
        try:
            # Создаем инвойс прямо при клике на "Да" (temporary unlimited)
            invoice = await cryptopay.create_invoice(
                amount=0.05,
                asset='USDT',
                description='Temporary unlimited access (30 seconds)'
            )
            pending_payments[invoice.invoice_id] = {'user_id': user_id, 'duration': 30, 'plan': 'temporary'}

            # Отправляем платежную ссылку
            text = f"💳 Pay 0.05 USDT for temporary unlimited access (30 seconds).\n\n{invoice.pay_url}\n\nYour status will be updated automatically after payment."
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


async def subscribe_callback(cryptopay: CryptoPay, callback: types.CallbackQuery):
    """Callback handler for subscription buttons (monthly/yearly).

    Creates an invoice and sends the payment link to the user.
    """
    try:
        data = callback.data or ''
        parts = data.split('|')
        if len(parts) < 2:
            await callback.answer("Invalid subscription request", show_alert=True)
            return
        plan = parts[1]
        if plan == 'monthly':
            amount = 0.05
            # monthly = 30 days
            duration = 30 * 24 * 3600
            description = 'Monthly subscription (30 days) for SludgeAI'
            plan_label = 'monthly'
        elif plan == 'yearly':
            amount = 0.5
            # For testing: make yearly actually 1 minute
            duration = 60
            description = 'Yearly subscription (12 months, 4 months free) for SludgeAI'
            plan_label = 'yearly'
        else:
            await callback.answer("Unknown plan", show_alert=True)
            return

        invoice = await cryptopay.create_invoice(
            amount=amount,
            asset='USDT',
            description=description
        )
        pending_payments[invoice.invoice_id] = {'user_id': callback.from_user.id, 'duration': duration, 'plan': plan_label}

        text = f"💳 Подписка: {description}\nСумма: {amount} USDT\n\nОплатите по ссылке: {invoice.pay_url}\n\nВаш статус обновится автоматически после оплаты."
        await callback.message.answer(text)
    except Exception as e:
        logging.error(f"Error creating subscription invoice for {callback.from_user.id}: {e}")
        await callback.answer("Ошибка создания инвойса. Попробуйте позже.", show_alert=True)


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
    # Subscription buttons (monthly/yearly)
    dp.callback_query.register(functools.partial(subscribe_callback, cryptopay),
                               lambda c: c.data and str(c.data).startswith("subscribe|"))

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
        await dp.start_polling(bot, handle_signals=False, timeout=60, request_timeout=300)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
