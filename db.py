from pocketbase import PocketBase
from config import PB_URL, PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD
from datetime import date, datetime, timezone
import time

pb = PocketBase(PB_URL)


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
            last_reset_str = getattr(record, 'last_reset', str(date.today()))
            last_reset_date = date.fromisoformat(last_reset_str) if isinstance(last_reset_str, str) else last_reset_str
            if last_reset_date != date.today():
                await reset_user_files(user_id)
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
            # Обновляем name, если передан и отличается
            update_data = {}
            if name and record.name != name:
                update_data['name'] = name
            # Обновляем username, если передан и отличается, или если поле отсутствует
            if username and username_field != username:
                update_data['username'] = username
            elif username_field in (None, '') and username:
                # старые записи могли не иметь username — заполним его
                update_data['username'] = username
            if update_data:
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
        create_payload = {
            'user_id': user_id,
            'name': name or 'Unknown',
            'is_premium': False,
            'files_today': 0,
            'total': 0,
            'last_reset': str(date.today()),
            'premium_end': None,
            'expiry_notified': False
        }
        # Always set username (empty string if missing) to keep schema consistent
        create_payload['username'] = username or ''

        record = pb.collection('users').create(create_payload)
        print(f"Created new user: {record.id}")
    return {'is_premium': False, 'files_today': 0, 'total': 0, 'username': username or '', 'record_id': record.id}


async def increment_files(user_id: int, amount: int = 1, name: str = None, telegram_id: str = None,
                          username: str = None):
    user_data = await get_user(user_id, name, telegram_id, username)
    record_id = user_data['record_id']
    new_files = user_data['files_today'] + amount
    new_total = int(user_data.get('total', 0)) + amount
    print(
        f"Incrementing files for user {user_id}: current {user_data['files_today']}, adding {amount}, new {new_files}; total -> {new_total}")
    update_payload = {
        'files_today': new_files,
        'total': new_total,
        'last_reset': str(date.today())
    }
    # If caller provided a username or name, update them as well
    if username:
        update_payload['username'] = username
    if name:
        update_payload['name'] = name

    pb.collection('users').update(record_id, update_payload)
    print(f"Updated user {user_id} files_today to {new_files} and total to {new_total}")


async def reset_user_files(user_id: int):
    user_data = await get_user(user_id)
    record_id = user_data['record_id']
    pb.collection('users').update(record_id, {
        'files_today': 0,
        'last_reset': str(date.today())
    })


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