from pocketbase import PocketBase
from config import PB_URL, PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD, RESET_MODE
from datetime import date, datetime, timezone
import time
import json
import os

pb = PocketBase(PB_URL)

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


async def init_db():
    # Аутентификация как superuser
    if PB_ADMIN_EMAIL and PB_ADMIN_PASSWORD:
        try:
            pb.admins.auth_with_password(PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD)
            print("Authenticated as superuser in PocketBase")
        except Exception as e:
            print(f"Failed to authenticate with PocketBase: {e}")
            raise
    else:
        print("Warning: PB_ADMIN_EMAIL or PB_ADMIN_PASSWORD not set. Running without authentication.")

    # Предполагаем, что коллекция 'users' уже создана в PocketBase с полями:
    # user_id: number
    # is_premium: bool
    # files_today: number
    # last_reset: date
    # name: plain text
    pass


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
                          username: str = None):
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
                print(f"[increment_files] attempt={attempt} user_id={user_id} current_files={current_files} current_total={current_total} last_reset_str={last_reset_str} marker={marker}")
                if last_reset_str:
                    try:
                        if str(RESET_MODE).lower() == 'daily':
                            last_reset_time = date.fromisoformat(last_reset_str)
                            if last_reset_time != marker:
                                print(f"[increment_files] СБРОС: last_reset_time={last_reset_time} != marker={marker}")
                                current_files = 0
                                should_reset = True
                            else:
                                print(f"[increment_files] НЕТ сброса: last_reset_time={last_reset_time} == marker={marker}")
                        else:
                            last_reset_time = datetime.fromisoformat(last_reset_str)
                            if last_reset_time < marker:
                                print(f"[increment_files] СБРОС: last_reset_time={last_reset_time} < marker={marker}")
                                current_files = 0
                                should_reset = True
                            else:
                                print(f"[increment_files] НЕТ сброса: last_reset_time={last_reset_time} >= marker={marker}")
                    except Exception as e:
                        print(f"[increment_files] Ошибка парсинга last_reset: {e}, СБРОС!")
                        current_files = 0
                        should_reset = True
                else:
                    print(f"[increment_files] Первый запрос, СБРОС!")
                    current_files = 0
                    should_reset = True

                new_files = current_files + amount
                new_total = current_total + amount
                update_payload = {
                    'files_today': new_files,
                    'total': new_total
                }
                # Обновляем last_reset только при сбросе
                if should_reset:
                    update_payload['last_reset'] = (marker.isoformat() if isinstance(marker, datetime) else str(marker))
                if username:
                    update_payload['username'] = username
                if name:
                    update_payload['name'] = name
                print(f"[increment_files] attempt={attempt} update_payload={update_payload}")
                try:
                    pb.collection('users').update(record.id, update_payload)
                    # If we're writing last_reset but PB schema doesn't persist it,
                    # also persist in the local fallback store so subsequent increments
                    # can consult it.
                    try:
                        if 'last_reset' in update_payload and update_payload['last_reset']:
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
                    if verified_files == new_files:
                        print(f"[increment_files] Success on attempt={attempt}: files_today={verified_files}")
                        return
                    else:
                        print(f"[increment_files] Mismatch after update on attempt={attempt}: verified_files={verified_files} expected={new_files}, retrying")
                        # попробуем ещё раз: прочитаем свежую запись
                        continue
                except Exception as e:
                    print(f"[increment_files] Failed to verify update on attempt={attempt}: {e}")
                    continue
            # Если все попытки не удались — логируем и выходим
            print(f"[increment_files] All attempts failed for user {user_id}. Last known current_files={getattr(record, 'files_today', None)}")
            return
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
            return
    except Exception as e:
        print(f"Failed to increment files for user {user_id}: {e}")
        # As a fallback, try using get_user behavior
        try:
            user_data = await get_user(user_id, name, telegram_id, username)
            record_id = user_data['record_id']
            # user_data уже учитывает возможный сброс, поэтому просто прибавляем
            new_files = user_data['files_today'] + amount
            new_total = int(user_data.get('total', 0)) + amount
            update_payload = {
                'files_today': new_files,
                'total': new_total
            }
            # НЕ обновляем last_reset в fallback, так как get_user уже мог его обновить
            if username:
                update_payload['username'] = username
            if name:
                update_payload['name'] = name
            pb.collection('users').update(record_id, update_payload)
            print(f"(fallback) Updated user {user_id} files_today to {new_files} and total to {new_total}")
        except Exception as e2:
            print(f"Fallback increment also failed for {user_id}: {e2}")


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