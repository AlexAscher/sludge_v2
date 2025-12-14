import os

# Директории
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

# Создаем папки при запуске
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Токен бота (из .env)
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# CryptoBot токен для оплаты
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")

# AWS S3 настройки (или compatible)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")  # Для Backblaze: applicationKeyId | Для DigitalOcean Spaces: Access Key из Spaces Keys
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")  # Для Backblaze: applicationKey | Для DigitalOcean Spaces: Secret Key из Spaces Keys
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")  # Имя bucket в Spaces (например, my-sludge-bucket)
S3_REGION = os.getenv("S3_REGION", "fra1")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")  # Для DigitalOcean Spaces: https://[region].digitaloceanspaces.com (например, https://fra1.digitaloceanspaces.com)

# PocketBase
PB_URL = os.getenv("PB_URL", "http://127.0.0.1:8090")  # URL PocketBase сервера
PB_ADMIN_EMAIL = os.getenv("PB_ADMIN_EMAIL")  # Email superuser для аутентификации
PB_ADMIN_PASSWORD = os.getenv("PB_ADMIN_PASSWORD")  # Пароль superuser

# Режим сброса счётчика files_today: '3min' или 'daily'
# По умолчанию используется '3min' для удобного тестирования.
RESET_MODE = os.getenv("RESET_MODE", "daily")

# Free daily copies limit for non-premium users (can be overridden via env)
FREE_DAILY_LIMIT = int(os.getenv('FREE_DAILY_LIMIT', '100'))

# Uploader URL
UPLOADER_URL = os.getenv("UPLOADER_URL", "http://46.101.157.179/")

# Concurrency limits to prevent server overload
MAX_CONCURRENT_USERS = int(os.getenv('MAX_CONCURRENT_USERS', '7'))  # Max users processing simultaneously
MAX_COPIES_PER_REQUEST = int(os.getenv('MAX_COPIES_PER_REQUEST', '120'))  # Max copies per request
