#!/usr/bin/env python3
"""
Простой веб-сервер для загрузки файлов в DigitalOcean Spaces.
Запуск: python upload_endpoint.py
Затем uploader.html будет отправлять файлы сюда.
"""

from flask import Flask, request, jsonify
import boto3
import os
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import config  # Импорт config.py

load_dotenv()

app = Flask(__name__)

# Настройки из config.py
S3_BUCKET_NAME = config.S3_BUCKET_NAME
S3_REGION = config.S3_REGION
S3_ENDPOINT = config.S3_ENDPOINT
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Инициализация клиента S3
s3_client = boto3.client(
    's3',
    region_name=S3_REGION,
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

UPLOAD_FOLDER = 'uploads/'

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Валидация типа файла
    allowed_types = [
        'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/svg+xml',
        'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm', 'video/avi', 'video/mpeg', 'video/ogg'
    ]
    if file.content_type not in allowed_types:
        return jsonify({'error': 'Invalid file type. Only images and videos allowed.'}), 400

    filename = secure_filename(file.filename)
    file_key = f"{UPLOAD_FOLDER}{int(__import__('time').time() * 1000)}_{filename}"

    try:
        # Загрузка в Spaces
        s3_client.upload_fileobj(
            file,
            S3_BUCKET_NAME,
            file_key,
            ExtraArgs={'ACL': 'public-read', 'ContentType': file.content_type}
        )

        # Ссылка на файл
        file_url = f"https://{S3_BUCKET_NAME}.{S3_REGION}.digitaloceanspaces.com/{file_key}"

        return jsonify({'url': file_url}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)