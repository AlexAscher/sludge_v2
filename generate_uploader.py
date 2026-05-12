#!/usr/bin/env python3
"""
Скрипт для генерации uploader.html с подстановкой переменных из config.py
Запуск: python generate_uploader.py
Результат: uploader.html с реальными значениями SPACE_NAME и REGION
"""

import os
import sys

# Добавляем текущую директорию в путь для импорта config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import config
except ImportError as e:
    print(f"Ошибка импорта config.py: {e}")
    sys.exit(1)

# Шаблон uploader.html
TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Загрузчик файлов</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f5f6fa; margin: 0; padding: 0; }
        .container { max-width: 500px; margin: 60px auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 32px; }
        h1 { text-align: center; margin-bottom: 24px; }
        input[type=file] { width: 100%; margin-bottom: 18px; }
        button { background: #007bff; color: #fff; border: none; border-radius: 8px; padding: 12px 24px; font-size: 1.1em; cursor: pointer; }
        button:disabled { background: #aaa; }
        .status { margin-top: 18px; text-align: center; font-size: 1.05em; }
    </style>
</head>
<body>
<div class="container">
    <h1>Загрузите файл</h1>
    <input type="file" id="fileInput" accept="image/*,video/*" />
    <button id="uploadBtn">Загрузить</button>
    <div class="status" id="status"></div>
</div>
<script>
// === НАСТРОЙКИ ===
// Значения SPACE_NAME и REGION подставлены автоматически из config.py
const SPACE_NAME = "{{SPACE_NAME}}";
const REGION = "{{REGION}}";
const UPLOAD_PATH = 'uploads/'; // папка внутри bucket

// === ЛОГИКА ===
function getISODate() {
    return new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, 'Z');
}


function isValidFileType(file) {
    const allowedTypes = [
        'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/svg+xml',
        'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm', 'video/avi', 'video/mpeg', 'video/ogg'
    ];
    return allowedTypes.includes(file.type);
}

async function uploadFile(file) {
    const fileName = UPLOAD_PATH + Date.now() + '_' + encodeURIComponent(file.name);
    const url = `https://${SPACE_NAME}.${REGION}.digitaloceanspaces.com/${fileName}`;
    document.getElementById('status').innerText = 'Загрузка...';
    try {
        const resp = await fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': file.type || 'application/octet-stream',
                'x-amz-acl': 'public-read'
            },
            body: file
        });
        if (resp.ok) {
            document.getElementById('status').innerHTML = `✅ Файл загружен!<br>Скопируйте ссылку и отправьте её боту:<br><input type='text' value='${url}' readonly style='width:100%;margin-top:8px;' onclick='this.select()'>`;
        } else {
            document.getElementById('status').innerText = `❌ Ошибка загрузки: ${resp.status} ${resp.statusText}`;
        }
    } catch (error) {
        document.getElementById('status').innerText = `❌ Ошибка загрузки: ${error.message}`;
    }
}

document.getElementById('uploadBtn').onclick = async () => {
    const file = document.getElementById('fileInput').files[0];
    if (!file) return alert('Выберите файл!');
    if (!isValidFileType(file)) {
        alert('Можно загружать только фото или видео!');
        return;
    }
    await uploadFile(file);
};
</script>
</body>
</html>"""

def main():
    # Получаем значения из config
    space_name = getattr(config, 'S3_BUCKET_NAME', 'yourfiles')
    region = getattr(config, 'S3_REGION', 'fra1')

    if not space_name or space_name.startswith('$'):
        print("Ошибка: S3_BUCKET_NAME не задан в .env или config.py")
        sys.exit(1)

    # Заменяем плейсхолдеры
    html = TEMPLATE.replace('{{SPACE_NAME}}', space_name).replace('{{REGION}}', region)

    # Записываем в файл
    output_path = os.path.join(os.path.dirname(__file__), 'uploader.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ uploader.html сгенерирован с SPACE_NAME='{space_name}' и REGION='{region}'")
    print(f"Файл сохранён: {output_path}")
    print("Теперь загрузите этот файл в корень вашего DigitalOcean Spaces.")

if __name__ == '__main__':
    main()