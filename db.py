from pocketbase import PocketBase
from config import PB_URL, PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD, RESET_MODE, FREE_DAILY_LIMIT
from datetime import date, datetime, timezone
import time
import json
import os
import asyncio
import logging

pb = PocketBase(PB_URL)
logger = logging.getLogger(__name__)

# Local fallback store for last_reset if PocketBase schema doesn't include the field.
LAST_RESET_STORE = os.path.join(os.path.dirname(__file__), 'data', 'metrics', 'last_reset_store.json')


def _load_last_reset_store():
    try:
        if os.path.exists(LAST_RESET_STORE):
            with open(LAST_RESET_STORE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load last_reset_store: {e}")
    return {}


def _save_last_reset_store(store: dict):
    try:
        os.makedirs(os.path.dirname(LAST_RESET_STORE), exist_ok=True)
        with open(LAST_RESET_STORE, 'w', encoding='utf-8') as f:
            json.dump(store, f)
    except Exception as e:
        print(f"Failed to save last_reset_store: {e}")


def _get_last_reset_fallback(user_id: int):
    store = _load_last_reset_store()
    return store.get(str(user_id))


def _set_last_reset_fallback(user_id: int, marker_str: str):
    store = _load_last_reset_store()
    store[str(user_id)] = marker_str
    _save_last_reset_store(store)


def get_current_3min_block():
    """Получить текущий 3-минутный блок времени для сброса счётчика"""
    now = datetime.now()
    return now.replace(second=0, microsecond=0, minute=(now.minute // 3) * 3)


def get_current_reset_marker():
    """Возвращает текущий маркер сброса в зависимости от RESET_MODE.

    - Для 'daily' возвращает date.today() (тип date)
    - Для '3min' возвращает datetime с округлением до 3-минутного блока
    """
    if str(RESET_MODE).lower() == 'daily':
        return date.today()
    return get_current_3min_block()


async def init_db(max_retries=5, delay=3, initial_wait=2):
    """Initialize PocketBase connection with retry logic for network issues

    Args:
        max_retries: Number of retry attempts
        delay: Seconds to wait between retries
        initial_wait: Initial wait time before first attempt (PocketBase startup)
    """
    # Wait for PocketBase to fully initialize
    logger.info(f"Waiting {initial_wait}s for PocketBase to initialize...")
    await asyncio.sleep(initial_wait)

    for attempt in range(max_retries):
        try:
            logger.info(f"Initializing PocketBase (attempt {attempt + 1}/{max_retries})...")

            # First check: Health endpoint (basic connectivity)
            try:
                pb.health.check()
                logger.info("   ✓ Health check passed")
            except Exception as e:
                logger.warning(f"   ✗ Health check failed: {e}")
                raise

            # Small delay to let PocketBase fully initialize after health check
            if attempt > 0:
                await asyncio.sleep(1)

            # Second check: Authentication (full readiness)
            if PB_ADMIN_EMAIL and PB_ADMIN_PASSWORD:
                pb.admins.auth_with_password(PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD)
                logger.info("   ✓ Admin authentication successful")
                logger.info("✅ PocketBase fully initialized")
                return True
            else:
                logger.warning("⚠️  PB_ADMIN_EMAIL or PB_ADMIN_PASSWORD not set. Running without authentication.")
                logger.info("✅ PocketBase health check passed (no auth configured)")
                return True

        except Exception as e:
            logger.warning(f"⚠️  PocketBase init failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")
            if attempt < max_retries - 1:
                wait_time = delay * (2 ** attempt)  # Exponential backoff
                logger.info(f"   Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("\n❌ CRITICAL: Failed to connect to PocketBase after all retries\n")
                logger.error(f"   PB_URL: {PB_URL}")
                logger.error("\n   Possible causes:")
                logger.error("   1. PocketBase service is not running")
                logger.error("   2. URL/port is incorrect or has changed")
                logger.error("   3. Credentials (PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD) are wrong")
                logger.error("   4. PocketBase is starting up or having startup issues")
                logger.error("   5. VPN is interfering with local connection (127.0.0.1)\n")
                logger.error("   Solutions:")
                logger.error("   • Restart PocketBase: killall pocketbase (or close pocketbase.exe)")
                logger.error("   • Wait 10+ seconds for PocketBase to fully start")
                logger.error("   • Check PocketBase admin panel at http://127.0.0.1:8090/_/")
                logger.error("   • Enable split tunneling in VPN for localhost\n")

                # Don't crash - allow bot to run without database
                logger.error("   Continuing without database (some features may be limited)...\n")
                return False


async def get_user(user_id: int, name: str = None, telegram_id: str = None, username: str = None):
    print(f"Searching for user_id = {user_id}")
    try:
        records = pb.collection('users').get_list(1, 50, {
            'filter': f'user_id={user_id}'
        })
        if records.items:
            record = records.items[0]
            print(f"Found existing user: {record.id}, user_id: {record.user_id}, name: {record.name}")
            is_premium = getattr(record, 'is_premium', False)
            files_today = getattr(record, 'files_today', 0)
            total = getattr(record, 'total', 0)
            username_field = getattr(record, 'username', None)
            last_reset_str = getattr(record, 'last_reset', None)

            # Текущий маркер сброса (дата или 3-минутный блок) и парсинг last_reset
            marker = get_current_reset_marker()

            if last_reset_str:
                try:
                    if str(RESET_MODE).lower() == 'daily':
                        last_reset_time = date.fromisoformat(last_reset_str)
                    else:
                        last_reset_time = datetime.fromisoformat(last_reset_str)
                except Exception:
                    # Если поле last_reset присутствует, но парсинг упал — считаем как None
                    last_reset_time = None
            else:
                # Попробуем взять значение из локального fallback-а, если поле отсутствует в PB
                fallback = _get_last_reset_fallback(user_id)
                if fallback:
                    try:
                        if str(RESET_MODE).lower() == 'daily':
                            last_reset_time = date.fromisoformat(fallback)
                        else:
                            last_reset_time = datetime.fromisoformat(fallback)
                    except Exception:
                        last_reset_time = None
                else:
                    last_reset_time = None

            # Решаем, нужно ли сбрасывать счётчик
            if str(RESET_MODE).lower() == 'daily':
                should_reset = not last_reset_time or last_reset_time != marker
            else:
                should_reset = not last_reset_time or last_reset_time < marker
            if should_reset:
                files_today = 0
            # Check if premium has expired
            premium_end = getattr(record, 'premium_end', None)
            parsed_end = None
            if premium_end:
                try:
                    # Handle both formats: with Z (2025-10-19 18:51:54.081Z) and without
                    if 'Z' in str(premium_end):
                        parsed_end = datetime.fromisoformat(str(premium_end).replace('Z', '+00:00'))
                    else:
                        parsed_end = datetime.fromisoformat(str(premium_end))
                except Exception as e:
                    print(f"Failed to parse premium_end for user {user_id}: {premium_end} -> {e}")

            # Always use UTC for comparison
            now_utc = datetime.now(timezone.utc)
            expired = parsed_end and parsed_end < now_utc
            print(
                f"User {user_id}: premium_end={premium_end}, parsed_end={parsed_end}, now={now_utc}, expired={expired}")
            if expired:
                is_premium = False
            # Обновляем name/username, если передан и отличается (НИКОГДА не обновляем last_reset здесь!)
            update_data = {}
            if name and record.name != name:
                update_data['name'] = name
            if username and username_field != username:
                update_data['username'] = username
            elif username_field in (None, '') and username:
                print(f"Failed to parse premium_end for user {user_id}: {premium_end} -> {e}")
            # Никогда не обновляем last_reset, files_today, total здесь!
            if update_data:
                print(f"[get_user] Only updating name/username: {update_data}")
                pb.collection('users').update(record.id, update_data)
            return {
                'is_premium': bool(is_premium),
                'files_today': files_today,
                'total': int(total),
                'username': username_field or (username or ''),
                'record_id': record.id
            }
        else:
            raise Exception("User not found")
    except Exception as e:
        print(f"User not found or error: {e}, creating new user for user_id: {user_id}")
        # Новый пользователь
        marker = get_current_reset_marker()
        create_payload = {
            'user_id': user_id,
            'name': name or 'Unknown',
            'is_premium': False,
            'files_today': 0,
            'total': 0,
            'last_reset': (marker.isoformat() if isinstance(marker, datetime) else str(marker)),
            'premium_end': None,
            'expiry_notified': False
        }
        # Always set username (empty string if missing) to keep schema consistent
        create_payload['username'] = username or ''

        record = pb.collection('users').create(create_payload)
        # Синхронизируем локальный fallback на случай, если PB не хранит поле last_reset
        try:
            _set_last_reset_fallback(user_id, (marker.isoformat() if isinstance(marker, datetime) else str(marker)))
        except Exception as e:
            print(f"Failed to write last_reset fallback for new user {user_id}: {e}")
        print(f"Created new user: {record.id}")
    return {'is_premium': False, 'files_today': 0, 'total': 0, 'username': username or '', 'record_id': record.id}


async def increment_files(user_id: int, amount: int = 1, name: str = None, telegram_id: str = None,
                          username: str = None, enforce_limit: bool = False):
    """
    Robustly increment files_today and total for a user.
    This directly queries the users collection by user_id and updates the record,
    creating the user if it does not exist. This avoids subtle issues with get_user
    (which may reset files_today) and ensures files_today reflects actual increments.
    """
    try:
        # Try to find existing record by user_id
        records = pb.collection('users').get_list(1, 50, {
            'filter': f'user_id={user_id}'
        })
        if records.items:
            record = records.items[0]
            # Попробуем выполнить update с простой оптимистичной попыткой несколько раз,
            # чтобы избежать состояния, когда обновление перезаписывает неправильное значение.
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                # ВАЖНО: каждый раз читаем актуальное значение из record (может быть обновлена в конце предыдущей итерации)
                current_files = int(getattr(record, 'files_today', 0) or 0)
                current_total = int(getattr(record, 'total', 0) or 0)
                last_reset_str = getattr(record, 'last_reset', None)
                # If PocketBase record lacks last_reset (schema missing), try local fallback
                if not last_reset_str:
                    try:
                        fallback = _get_last_reset_fallback(user_id)
                        if fallback:
                            last_reset_str = fallback
                            print(f"[increment_files] used fallback last_reset for user {user_id}: {fallback}")
                    except Exception as e:
                        print(f"[increment_files] failed to read fallback last_reset for {user_id}: {e}")
                marker = get_current_reset_marker()
                should_reset = False
                # Лог для отладки
                print(
                    f"[increment_files] attempt={attempt} user_id={user_id} current_files={current_files} current_total={current_total} last_reset_str={last_reset_str} marker={marker}")
                if last_reset_str:
                    try:
                        if str(RESET_MODE).lower() == 'daily':
                            last_reset_time = date.fromisoformat(last_reset_str)
                            if last_reset_time != marker:
                                print(f"[increment_files] СБРОС: last_reset_time={last_reset_time} != marker={marker}")
                                current_files = 0
                                should_reset = True
                            else:
                                print(
                                    f"[increment_files] НЕТ сброса: last_reset_time={last_reset_time} == marker={marker}")
                        else:
                            last_reset_time = datetime.fromisoformat(last_reset_str)
                            if last_reset_time < marker:
                                print(f"[increment_files] СБРОС: last_reset_time={last_reset_time} < marker={marker}")
                                current_files = 0
                                should_reset = True
                            else:
                                print(
                                    f"[increment_files] НЕТ сброса: last_reset_time={last_reset_time} >= marker={marker}")
                    except Exception as e:
                        print(f"[increment_files] Ошибка парсинга last_reset: {e}, СБРОС!")
                        current_files = 0
                        should_reset = True
                else:
                    print(f"[increment_files] Первый запрос, СБРОС!")
                    current_files = 0
                    should_reset = True

                new_files = current_files + amount
                # Enforce free-user limit if requested and user is not premium
                is_premium = bool(getattr(record, 'is_premium', False))
                if enforce_limit and not is_premium:
                    try:
                        limit = int(FREE_DAILY_LIMIT)
                    except Exception:
                        limit = 20
                    if new_files > limit:
                        print(
                            f"[increment_files] would exceed limit for user {user_id}: current={current_files} amount={amount} limit={limit}")
                        # Extra debug info: show parsed last_reset and is_premium
                        try:
                            print(
                                f"[increment_files] DEBUG user={user_id} is_premium={is_premium} last_reset_str={last_reset_str} marker={marker}")
                        except Exception:
                            pass
                        # Do not perform update; signal caller that limit was exceeded
                        return False
                new_total = current_total + amount
                update_payload = {
                    'files_today': new_files,
                    'total': new_total,
                    # ВАЖНО: ВСЕГДА обновляем last_reset, чтобы следующий increment не считал что нужен сброс
                    'last_reset': (marker.isoformat() if isinstance(marker, datetime) else str(marker))
                }
                if username:
                    update_payload['username'] = username
                if name:
                    update_payload['name'] = name
                print(f"[increment_files] attempt={attempt} update_payload={update_payload}")
                try:
                    pb.collection('users').update(record.id, update_payload)
                    # ВСЕГДА сохраняем last_reset в fallback для последовательности инкрементов
                    try:
                        _set_last_reset_fallback(user_id, update_payload['last_reset'])
                    except Exception as e:
                        print(f"[increment_files] failed to write fallback last_reset after update for {user_id}: {e}")
                except Exception as e:
                    print(f"[increment_files] attempt={attempt} update failed: {e}")
                    # Попробуем заново прочитать запись и повторить
                    try:
                        time.sleep(0.05)
                        record = pb.collection('users').get_one(record.id)
                        continue
                    except Exception:
                        break

                # Проверяем результат — читаем запись и убеждаемся, что files_today соответствует ожиданию
                try:
                    time.sleep(0.05)
                    record = pb.collection('users').get_one(record.id)
                    verified_files = int(getattr(record, 'files_today', 0) or 0)
                    # Проверяем СТРОГОЕ равенство - если значение отличается, значит произошла race condition
                    # и нужно повторить операцию с актуальным значением из базы
                    if verified_files == new_files:
                        print(
                            f"[increment_files] Success on attempt={attempt}: files_today={verified_files} (expected {new_files})")
                        return True
                    else:
                        print(
                            f"[increment_files] Mismatch after update on attempt={attempt}: verified_files={verified_files} expected={new_files}, retrying with fresh data")
                        # record уже обновлена свежими данными выше, следующая итерация будет использовать актуальное значение
                        continue
                except Exception as e:
                    print(f"[increment_files] Failed to verify update on attempt={attempt}: {e}")
                    # При ошибке проверки тоже попробуем прочитать свежую запись
                    try:
                        record = pb.collection('users').get_one(record.id)
                    except Exception:
                        pass
                    continue
            # Если все попытки не удались — логируем и выходим
            print(
                f"[increment_files] All attempts failed for user {user_id}. Last known current_files={getattr(record, 'files_today', None)}")
            return False
        else:
            # Create new user with initial counts
            marker = get_current_reset_marker()
            create_payload = {
                'user_id': user_id,
                'name': name or 'Unknown',
                'is_premium': False,
                'files_today': amount,
                'total': amount,
                'last_reset': (marker.isoformat() if isinstance(marker, datetime) else str(marker)),
                'premium_end': None,
                'expiry_notified': False,
                'username': username or ''
            }
            record = pb.collection('users').create(create_payload)
            print(f"Created user {user_id} with files_today={amount} total={amount}")
            # Persist last_reset to local fallback store as well, in case PB schema lacks the field
            try:
                marker_iso = (marker.isoformat() if isinstance(marker, datetime) else str(marker))
                _set_last_reset_fallback(user_id, marker_iso)
            except Exception as e:
                print(f"Failed to write last_reset fallback for created user {user_id}: {e}")
            # New user created and counts set
            return True
    except Exception as e:
        print(f"Failed to increment files for user {user_id}: {e}")
        # FALLBACK НЕ ДОЛЖЕН использовать get_user, так как это создаёт race condition
        # Вместо этого создаём пользователя, если его нет
        try:
            # Попробуем создать нового пользователя (если его вообще нет)
            marker = get_current_reset_marker()
            create_payload = {
                'user_id': user_id,
                'name': name or 'Unknown',
                'is_premium': False,
                'files_today': amount,
                'total': amount,
                'last_reset': (marker.isoformat() if isinstance(marker, datetime) else str(marker)),
                'premium_end': None,
                'expiry_notified': False,
                'username': username or ''
            }
            record = pb.collection('users').create(create_payload)
            print(f"(fallback) Created user {user_id} with files_today={amount} total={amount}")
            # Persist last_reset to local fallback store
            try:
                marker_iso = (marker.isoformat() if isinstance(marker, datetime) else str(marker))
                _set_last_reset_fallback(user_id, marker_iso)
            except Exception as e3:
                print(f"(fallback) Failed to write last_reset fallback: {e3}")
            return True
        except Exception as e2:
            print(f"Fallback increment also failed for {user_id}: {e2}")
            return False


async def reset_user_files(user_id: int):
    """
    Reset files_today and update last_reset for the given user_id.

    Important: do NOT call `get_user` here because `get_user` may call
    `reset_user_files` when it detects a stale last_reset — that creates
    an infinite recursive loop. Instead, find the user's record directly
    via PocketBase and update it.

    Returns True if updated, False otherwise.
    """
    try:
        records = pb.collection('users').get_list(1, 50, {
            'filter': f'user_id={user_id}'
        })
        if records.items:
            record = records.items[0]
            marker = get_current_reset_marker()
            pb.collection('users').update(record.id, {
                'files_today': 0,
                'last_reset': (marker.isoformat() if isinstance(marker, datetime) else str(marker))
            })
            return True
        return False
    except Exception as e:
        print(f"Failed to reset files for user {user_id}: {e}")
        return False


async def set_premium(user_id: int, premium: bool = True, duration: int = None):
    user_data = await get_user(user_id)
    record_id = user_data['record_id']
    update_data = {'is_premium': premium}
    if premium and duration:
        # Always use UTC: now + duration in seconds
        premium_end_utc = datetime.now(timezone.utc).timestamp() + duration
        premium_end_value = datetime.fromtimestamp(premium_end_utc, tz=timezone.utc).isoformat()
        update_data['premium_end'] = premium_end_value
        update_data['expiry_notified'] = False
        print(f"Setting premium for {user_id}: premium_end={premium_end_value} (UTC)")
    elif not premium:
        update_data['premium_end'] = None
    pb.collection('users').update(record_id, update_data)
    print(f"Premium updated for {user_id}: is_premium={premium}")


async def get_expired_users():
    try:
        records = pb.collection('users').get_list(1, 1000)
        expired = []
        current_time_utc = datetime.now(timezone.utc)
        for record in records.items:
            premium_end = getattr(record, 'premium_end', None)
            expiry_notified = getattr(record, 'expiry_notified', False)
            parsed = None
            if premium_end:
                try:
                    # Handle both formats: with Z and without
                    if 'Z' in str(premium_end):
                        parsed = datetime.fromisoformat(str(premium_end).replace('Z', '+00:00'))
                    else:
                        parsed = datetime.fromisoformat(str(premium_end))
                except Exception as e:
                    print(
                        f"Failed to parse premium_end for user {getattr(record, 'user_id', record.id)}: {premium_end} -> {e}")

            is_expired = parsed and parsed < current_time_utc
            if is_expired and not expiry_notified:
                print(
                    f"Found expired user: {getattr(record, 'user_id', record.id)}, premium_end={premium_end}, now={current_time_utc}")
                expired.append(record)

        return expired
    except Exception as e:
        print(f"Error getting expired users: {e}")
        return []

# Инициализация
# asyncio.run(init_db())  # Не нужно, поскольку PocketBase управляет