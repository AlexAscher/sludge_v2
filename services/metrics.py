import os
import json
from datetime import datetime, date
from typing import Optional
from config import DATA_DIR, PB_URL, PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD
from pocketbase import PocketBase

METRICS_DIR = os.path.join(DATA_DIR, "metrics")
os.makedirs(METRICS_DIR, exist_ok=True)

# Storage totals file
STORAGE_TOTAL_FILE = os.path.join(METRICS_DIR, "storage_total.json")

# PocketBase client for user counts (optional auth if provided)
pb = PocketBase(PB_URL)
if PB_ADMIN_EMAIL and PB_ADMIN_PASSWORD:
    try:
        pb.admins.auth_with_password(PB_ADMIN_EMAIL, PB_ADMIN_PASSWORD)
    except Exception:
        # continue without admin auth (read-only queries may still work if PB is public)
        pass


def _read_json(path: str, default=None):
    if default is None:
        default = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def record_file_processed(user_id: int, size_bytes: int = 0):
    """Record that a user processed a file (e.g., watermark or copy)."""
    day = date.today().isoformat()
    path = os.path.join(METRICS_DIR, f"daily_{day}.json")
    data = _read_json(path, default={
        'date': day,
        'files': 0,
        'bytes': 0,
        'premium_purchased': 0,
        'unique_users': [],
        'user_details': {}
    })

    data['files'] = int(data.get('files', 0)) + 1
    data['bytes'] = int(data.get('bytes', 0)) + int(size_bytes or 0)
    # Track unique users list (store as strings)
    ulist = set(data.get('unique_users', []))
    ulist.add(str(user_id))
    data['unique_users'] = list(ulist)

    # Track detailed user statistics
    user_str = str(user_id)
    if 'user_details' not in data:
        data['user_details'] = {}

    if user_str not in data['user_details']:
        data['user_details'][user_str] = {
            'files': 0,
            'bytes': 0
        }

    data['user_details'][user_str]['files'] += 1
    data['user_details'][user_str]['bytes'] += int(size_bytes or 0)

    _write_json(path, data)

    # Update storage total (cumulative uploaded bytes)
    total = _read_json(STORAGE_TOTAL_FILE, default={'bytes_stored': 0})
    total['bytes_stored'] = int(total.get('bytes_stored', 0)) + int(size_bytes or 0)
    _write_json(STORAGE_TOTAL_FILE, total)


async def record_premium_purchase(user_id: int):
    day = date.today().isoformat()
    path = os.path.join(METRICS_DIR, f"daily_{day}.json")
    data = _read_json(path, default={
        'date': day,
        'files': 0,
        'bytes': 0,
        'premium_purchased': 0,
        'unique_users': [],
        'user_details': {}
    })

    data['premium_purchased'] = int(data.get('premium_purchased', 0)) + 1
    ulist = set(data.get('unique_users', []))
    ulist.add(str(user_id))
    data['unique_users'] = list(ulist)
    _write_json(path, data)


def _bytes_to_gb(b: int) -> float:
    return round((int(b) / (1024 ** 3)), 4)


def _collect_month_days(year: int, month: int):
    prefix = f"daily_{year:04d}-{month:02d}-"
    days = []
    for name in os.listdir(METRICS_DIR):
        if name.startswith(prefix) and name.endswith('.json'):
            days.append(name)
    return sorted(days)


async def generate_report_txt(month: Optional[str] = None) -> str:
    """
    Generate a human-readable TXT report.
    `month` format: 'YYYY-MM' (defaults to current month)
    Returns: string (text content)
    """
    # Determine month
    if month is None:
        now = datetime.utcnow()
        year = now.year
        mon = now.month
    else:
        try:
            year, mon = map(int, month.split('-'))
        except Exception:
            now = datetime.utcnow()
            year = now.year
            mon = now.month

    # Get all users for status lookup
    try:
        users_resp = pb.collection('users').get_list(1, 1000)
        users_dict = {str(u.user_id): (u.name, u.is_premium) for u in users_resp.items}
    except Exception:
        users_dict = {}

    # Collect daily files
    days = _collect_month_days(year, mon)

    total_files_month = 0
    total_bytes_month = 0
    total_premium_month = 0

    lines = []
    lines.append(f"Monthly report for {year:04d}-{mon:02d}\n")
    lines.append("Per-day details:\n")

    for fname in days:
        path = os.path.join(METRICS_DIR, fname)
        d = _read_json(path, default={})
        day = d.get('date', fname.replace('daily_', '').replace('.json', ''))
        files = int(d.get('files', 0))
        bytes_ = int(d.get('bytes', 0))
        premium = int(d.get('premium_purchased', 0))
        users_list = d.get('unique_users', [])
        user_details = d.get('user_details', {})

        total_files_month += files
        total_bytes_month += bytes_
        total_premium_month += premium

        lines.append(f"{day}: files={files}, {_bytes_to_gb(bytes_)} GB, premium_purchased={premium}")

        if users_list:
            lines.append("Active users:")
            for uid in users_list:
                user_files = user_details.get(uid, {}).get('files', 0)
                user_bytes = user_details.get(uid, {}).get('bytes', 0)
                user_gb = _bytes_to_gb(user_bytes)

                if uid in users_dict:
                    name, is_prem = users_dict[uid]
                    status = "premium" if is_prem else "free"
                    # show username instead of telegramID at the end
                    lines.append(
                        f"  {name} ({uid}): {status}, files={user_files}, Memory={user_gb} GB, username={name}")
                else:
                    # unknown users: fall back to uid as username
                    lines.append(f"  {uid}: unknown, files={user_files}, Memory={user_gb} GB, username={uid}")
            lines.append("")  # empty line after users

    # Global totals
    # Total files all time (sum all daily files)
    all_files = 0
    all_bytes = 0
    for name in os.listdir(METRICS_DIR):
        if name.startswith('daily_') and name.endswith('.json'):
            d = _read_json(os.path.join(METRICS_DIR, name), default={})
            all_files += int(d.get('files', 0))
            all_bytes += int(d.get('bytes', 0))

    storage_total = _read_json(STORAGE_TOTAL_FILE, default={'bytes_stored': 0})
    bytes_stored = int(storage_total.get('bytes_stored', 0))

    # Get user counts from PocketBase
    try:
        users_resp = pb.collection('users').get_list(1, 1)
        # We don't have an easy total-count API here; try to request a large page to count
        users_all = pb.collection('users').get_list(1, 1000)
        total_users = len(users_all.items)
        # Paid users
        paid = pb.collection('users').get_list(1, 1000, {'filter': 'is_premium=true'})
        total_paid = len(paid.items)
    except Exception:
        total_users = 0
        total_paid = 0

    lines.append("\nSummary:\n")
    lines.append(f"Files this month: {total_files_month}")
    lines.append(f"Bytes this month: {_bytes_to_gb(total_bytes_month)} GB")
    lines.append(f"Premium purchased this month: {total_premium_month}")
    lines.append(f"Files all time: {all_files}")
    lines.append(f"Total bytes all time: {_bytes_to_gb(all_bytes)} GB")
    lines.append(f"Storage cumulative (tracked uploads): {_bytes_to_gb(bytes_stored)} GB")
    lines.append(f"Total users (approx): {total_users}")
    lines.append(f"Paid users (approx): {total_paid}")

    return "\n".join(lines)


async def save_report_to_file(month: Optional[str] = None) -> str:
    """Generate report and save it to a txt file under DATA_DIR/metrics_reports."""
    reports_dir = os.path.join(DATA_DIR, 'metrics_reports')
    os.makedirs(reports_dir, exist_ok=True)
    txt = await generate_report_txt(month)
    now = datetime.utcnow()
    fname = f"report_{month or now.strftime('%Y-%m')}_{now.strftime('%Y%m%d_%H%M%S')}.txt"
    path = os.path.join(reports_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    return path