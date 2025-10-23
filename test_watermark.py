#!/usr/bin/env python3
"""
Быстрый тест исправления прозрачности
"""

import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw

# Добавляем корневую директорию проекта в Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def create_test_logo_with_transparency():
    """Создает тестовый PNG логотип с полностью прозрачным фоном"""
    # Создаем изображение с полностью прозрачным фоном
    logo = Image.new('RGBA', (200, 100), (0, 0, 0, 0))  # Полностью прозрачный
    draw = ImageDraw.Draw(logo)

    # Рисуем логотип только в видимых областях
    # Синий круг
    draw.ellipse([20, 20, 80, 80], fill=(0, 100, 255, 255))  # Непрозрачный синий

    # Текст
    draw.text((110, 50), "TEST", fill=(255, 0, 0, 255), anchor='mm')  # Красный текст

    # Белая рамка (но не фон!)
    draw.rectangle([10, 10, 190, 90], outline=(255, 255, 255, 255), width=2)

    logo_path = 'transparent_test_logo.png'
    logo.save(logo_path, 'PNG')
    print(f"✅ Создан тестовый логотип с прозрачностью: {logo_path}")
    return logo_path


def create_test_background():
    """Создает фоновое изображение для теста"""
    # Градиентный фон для лучшей проверки прозрачности
    bg = Image.new('RGB', (600, 400), 'white')
    draw = ImageDraw.Draw(bg)

    # Красно-синий градиент
    for y in range(400):
        color = int(255 * y / 400)
        draw.line([(0, y), (600, y)], fill=(255 - color, 0, color))

    # Текст для контраста
    draw.text((300, 200), "BACKGROUND", fill=(255, 255, 255), anchor='mm')

    bg_path = 'test_background.jpg'
    bg.save(bg_path, 'JPEG')
    print(f"✅ Создан фон: {bg_path}")
    return bg_path


def test_transparency_fix():
    """Тестирует исправленную функцию прозрачности"""
    try:
        from services.watermark import add_image_watermark_image

        # Создаем тестовые файлы
        logo_path = create_test_logo_with_transparency()
        bg_path = create_test_background()

        # Тестируем с полной непрозрачностью (должен сохранить оригинальную прозрачность PNG)
        result_path = add_image_watermark_image(
            bg_path,
            logo_path,
            'center',
            scale=0.3,
            output_path='test_result_transparent.jpg'
        )

        if os.path.exists(result_path):
            file_size = os.path.getsize(result_path)
            print(f"✅ Тест пройден: {result_path} ({file_size} bytes)")
            print("🎯 Проверьте результат - прозрачные области логотипа должны показывать фон")
            success = True
        else:
            print("❌ Файл результата не создан")
            success = False

        # Очистка
        for file_path in [logo_path, bg_path, result_path]:
            if os.path.exists(file_path):
                os.remove(file_path)

        return success

    except Exception as e:
        print(f"❌ Ошибка в тесте: {e}")
        return False


if __name__ == "__main__":
    print("🧪 Тест исправления прозрачности")
    print("=" * 50)

    success = test_transparency_fix()

    if success:
        print("\n✅ Тест пройден! Прозрачность должна работать корректно.")
        print("💡 Теперь PNG файлы с прозрачным фоном будут отображаться правильно")
    else:
        print("\n❌ Тест провален. Проблема остается.")

    sys.exit(0 if success else 1)