import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, CRYPTOBOT_TOKEN, FREE_DAILY_LIMIT, TELEGRAM_PROXY
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
                await bot.send_message(user_id, f"✅ Платёж получен! Теперь у вас премиум ({plan})")
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
                [InlineKeyboardButton(text="Да", callback_data="renew_yes")],
                [InlineKeyboardButton(text="Нет", callback_data="renew_no")]
            ])
            await bot.send_message(user_id, "Ваша подписка закончилась. Хотите продлить?",
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
        description='Временный безлимитный доступ (30 секунд)'
    )

    # Store payload keyed by invoice_id so check_payments can grant correct duration
    pending_payments[invoice.invoice_id] = {'user_id': user_id, 'duration': 30, 'plan': 'temporary'}

    # Send payment link
    text = f"💳 Оплатите 0.05 USDT за временный безлимитный доступ (30 секунд).\n\n{invoice.pay_url}\n\nСтатус обновится автоматически после оплаты."
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
                description='Временный безлимитный доступ (30 секунд)'
            )
            pending_payments[invoice.invoice_id] = {'user_id': user_id, 'duration': 30, 'plan': 'temporary'}

            # Отправляем платежную ссылку
            text = f"💳 Оплатите 0.05 USDT за временный безлимитный доступ (30 секунд).\n\n{invoice.pay_url}\n\nСтатус обновится автоматически после оплаты."
            await callback.message.edit_text(text)
        except Exception as e:
            logging.error(f"Error creating invoice for {user_id}: {e}")
            await callback.answer("Ошибка создания ссылки на оплату. Попробуйте команду /pay.")
    elif callback.data == "renew_no":
        # Remove the question message and send the main informational/start message
        try:
            await callback.message.delete()
        except Exception:
            pass
        main_text = (
            "Добро пожаловать в @SludgeAI 🚀\n\n"
            "Создавайте действительно уникальные видео и изображения, которые алгоритмы не помечают как дубликаты. Sludge AI автоматически меняет ваши медиафайлы: правит метаданные, вносит мягкие случайные визуальные изменения и помогает каждому клипу или изображению выглядеть как единственный экземпляр.\n\n"
            "Результат: больший охват и выше шанс попасть в FYP и рекомендации!\n\n"
            "Начните сейчас: загрузите видео или фото из галереи ⬇️\n\n"
            "👀 Реальные отзывы и примеры: @sludgevouches\n\n"
            "Ваш контент — ваш голос. Сделайте его заметным 🚀"
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
            await callback.answer("Некорректный запрос на подписку", show_alert=True)
            return
        plan = parts[1]
        if plan == 'monthly':
            amount = 0.05
            # monthly = 30 days
            duration = 30 * 24 * 3600
            description = 'Ежемесячная подписка (30 дней) для SludgeAI'
            plan_label = 'monthly'
        elif plan == 'yearly':
            amount = 0.5
            # For testing: make yearly actually 1 minute
            duration = 60
            description = 'Годовая подписка (12 месяцев, 4 месяца бесплатно) для SludgeAI'
            plan_label = 'yearly'
        else:
            await callback.answer("Неизвестный тариф", show_alert=True)
            return

        invoice = await cryptopay.create_invoice(
            amount=amount,
            asset='USDT',
            description=description
        )
        pending_payments[invoice.invoice_id] = {'user_id': callback.from_user.id, 'duration': duration,
                                                'plan': plan_label}

        text = f"💳 Подписка: {description}\nСумма: {amount} USDT\n\nОплатите по этой ссылке: {invoice.pay_url}\n\nСтатус обновится автоматически после оплаты."
        await callback.message.answer(text)
    except Exception as e:
        logging.error(f"Error creating subscription invoice for {callback.from_user.id}: {e}")
        await callback.answer("Ошибка создания счёта. Попробуйте позже.", show_alert=True)


async def init_cryptopay_with_retry(max_retries=3, delay=5):
    """Initialize CryptoPay with retry logic for network issues"""
    for attempt in range(max_retries):
        try:
            logging.info(f"Initializing CryptoPay (attempt {attempt + 1}/{max_retries})...")
            cryptopay = CryptoPay(CRYPTOBOT_TOKEN, TESTNET)
            logging.info("✅ CryptoPay initialized successfully")
            return cryptopay
        except Exception as e:
            logging.warning(f"⚠️ CryptoPay init failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
            else:
                logging.error(
                    "❌ CryptoPay initialization failed after all retries. Payment system will be unavailable.")
                return None


async def main():
    logging.info("Starting bot main function")

    # Инициализация базы данных и аутентификация (graceful degradation)
    try:
        db_available = await init_db()
    except Exception as e:
        logging.error(f"Database initialization error: {e}")
        db_available = False

    session = AiohttpSession(proxy=TELEGRAM_PROXY) if TELEGRAM_PROXY else AiohttpSession()
    if TELEGRAM_PROXY:
        logging.info("Telegram proxy is enabled for aiogram session")
    else:
        logging.warning("Telegram proxy не задан. Если Telegram заблокирован, укажите TELEGRAM_PROXY в .env")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=session,
    )
    dp = Dispatcher()

    # Инициализация CryptoPay с обработкой ошибок
    cryptopay = await init_cryptopay_with_retry()
    cryptopay_available = cryptopay is not None

    # Регистрируем middleware
    dp.message.middleware(limit_middleware)

    # Регистрируем хендлеры
    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(stats.router)
    dp.include_router(process.router)
    logging.info("All routers included: start, help, stats, process")

    # Команда оплаты (только если CryptoPay доступен)
    if cryptopay_available:
        dp.message.register(functools.partial(pay_command, cryptopay), Command("pay"))

        # Обработчик callback
        dp.callback_query.register(functools.partial(callback_handler, cryptopay),
                                   lambda c: c.data in ["renew_yes", "renew_no"])
        # Subscription buttons (monthly/yearly)
        dp.callback_query.register(functools.partial(subscribe_callback, cryptopay),
                                   lambda c: c.data and str(c.data).startswith("subscribe|"))
    else:
        logging.warning("⚠️ CryptoPay disabled - payment commands will be unavailable")

    # Планировщик для проверки платежей каждые 30 секунд
    scheduler = AsyncIOScheduler()

    # Только добавляем задачи если CryptoPay доступен
    if cryptopay_available:
        scheduler.add_job(check_payments, IntervalTrigger(seconds=30), args=[bot, cryptopay])

    scheduler.add_job(check_expired_premiums, IntervalTrigger(seconds=60), args=[bot])
    scheduler.start()

    # Construct startup message
    status_items = []
    if db_available:
        status_items.append("✅ database")
    else:
        status_items.append("⚠️  database disabled")

    if cryptopay_available:
        status_items.append("✅ payments")
    else:
        status_items.append("⚠️  payments disabled")

    status_str = " | ".join(status_items)
    print(f"🤖 Bot started [{status_str}]")
    logging.info(f"Bot status: {status_str}")

    # Set bot commands
    try:
        commands = [
            types.BotCommand(command="start", description="Запустить бота"),
            types.BotCommand(command="help", description="Помощь"),
            types.BotCommand(command="stats", description="Статистика использования"),
        ]
        if cryptopay_available:
            commands.insert(2, types.BotCommand(command="pay", description="Оплатить премиум"))

        await bot.set_my_commands(commands)
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
