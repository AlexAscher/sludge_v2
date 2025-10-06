from pocketbase import PocketBase
from config import PB_URL
from datetime import date

pb = PocketBase(PB_URL)

async def init_db():
    # Предполагаем, что коллекция 'users' уже создана в PocketBase с полями:
    # user_id: number
    # is_premium: bool
    # files_today: number
    # last_reset: date
    pass

async def get_user(user_id: int):
    try:
        record = pb.collection('users').get_first_list_item(f'user_id={user_id}')
        is_premium = record.is_premium
        files_today = record.files_today
        last_reset_str = record.last_reset
        last_reset_date = date.fromisoformat(last_reset_str) if isinstance(last_reset_str, str) else last_reset_str
        if last_reset_date != date.today():
            await reset_user_files(user_id)
            files_today = 0
        return {'is_premium': bool(is_premium), 'files_today': files_today, 'record_id': record.id}
    except:
        # Новый пользователь
        record = pb.collection('users').create({
            'user_id': user_id,
            'is_premium': False,
            'files_today': 0,
            'last_reset': str(date.today())
        })
        return {'is_premium': False, 'files_today': 0, 'record_id': record.id}

async def increment_files(user_id: int, amount: int = 1):
    user_data = await get_user(user_id)
    record_id = user_data['record_id']
    new_files = user_data['files_today'] + amount
    pb.collection('users').update(record_id, {
        'files_today': new_files,
        'last_reset': str(date.today())
    })

async def reset_user_files(user_id: int):
    user_data = await get_user(user_id)
    record_id = user_data['record_id']
    pb.collection('users').update(record_id, {
        'files_today': 0,
        'last_reset': str(date.today())
    })

async def set_premium(user_id: int, premium: bool = True):
    user_data = await get_user(user_id)
    record_id = user_data['record_id']
    pb.collection('users').update(record_id, {'is_premium': premium})

# Инициализация
# asyncio.run(init_db())  # Не нужно, поскольку PocketBase управляет