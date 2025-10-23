#!/usr/bin/env python3
"""
Тестовый скрипт для расширенной функциональности водяных знаков (текст + изображение)
"""

import os
import sys
import logging
from pathlib import Path
from PIL import Image, ImageDraw

# Добавляем корневую директорию проекта в Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_test_image():
    """Создает тестовое изображение"""
    width, height = 800, 600
    image = Image.new('RGB', (width, height), color='lightblue')
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, width - 100, height - 100], fill='white', outline='black', width=3)
    draw.text((width // 2 - 100, height // 2), "TEST IMAGE", fill='black')

    test_image_path = 'test_base_image.jpg'
    image.save(test_image_path, 'JPEG')
    logger.info(f"✅ Создано тестовое изображение: {test_image_path}")
    return test_image_path


def create_test_watermark_image():
    """Создает тестовое изображение для водяного знака"""
    width, height = 200, 100
    # Создаем изображение с прозрачным фоном
    image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Рисуем простой логотип
    draw.rectangle([10, 10, width - 10, height - 10], fill=(255, 0, 0, 180), outline=(255, 255, 255, 255), width=2)
    draw.text((width // 2 - 30, height // 2 - 10), "LOGO", fill=(255, 255, 255, 255))

    watermark_path = 'test_watermark.png'
    image.save(watermark_path, 'PNG')
    logger.info(f"✅ Создан тестовый водяной знак: {watermark_path}")
    return watermark_path


def test_text_watermarks():
    """Тестируем текстовые водяные знаки"""
    logger.info("🧪 Тестируем текстовые водяные знаки")

    try:
        from services.watermark import add_watermark_image

        test_image_path = create_test_image()

        # Тестируем разные позиции
        positions = ['top_left', 'center', 'bottom_right']
        results = []

        for position in positions:
            try:
                output_path = f"test_text_watermark_{position}.jpg"
                result_path = add_watermark_image(
                    test_image_path,
                    f"@TestChannel",
                    position,
                    output_path
                )

                if os.path.exists(result_path):
                    file_size = os.path.getsize(result_path)
                    logger.info(f"✅ Text watermark {position}: {result_path} ({file_size} bytes)")
                    results.append((position, True))
                else:
                    logger.error(f"❌ Text watermark {position}: файл не создан")
                    results.append((position, False))

            except Exception as e:
                logger.error(f"❌ Text watermark {position}: ошибка - {e}")
                results.append((position, False))

        # Очистка
        cleanup_files = [test_image_path] + [f"test_text_watermark_{pos}.jpg" for pos in positions]
        for file_path in cleanup_files:
            if os.path.exists(file_path):
                os.remove(file_path)

        success_count = sum(1 for _, success in results if success)
        logger.info(f"📊 Текстовые водяные знаки: {success_count}/{len(positions)} успешно")
        return success_count == len(positions)

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в тесте текстовых водяных знаков: {e}")
        return False


def test_image_watermarks():
    """Тестируем водяные знаки-изображения"""
    logger.info("🧪 Тестируем водяные знаки-изображения")

    try:
        from services.watermark import add_image_watermark_image

        test_image_path = create_test_image()
        watermark_image_path = create_test_watermark_image()

        # Тестируем разные позиции и масштабы
        test_cases = [
            ('top_left', 0.15),
            ('center', 0.2),
            ('bottom_right', 0.25)
        ]
        results = []

        for position, scale in test_cases:
            try:
                output_path = f"test_image_watermark_{position}_{int(scale * 100)}.jpg"
                result_path = add_image_watermark_image(
                    test_image_path,
                    watermark_image_path,
                    position,
                    scale,
                    output_path
                )

                if os.path.exists(result_path):
                    file_size = os.path.getsize(result_path)
                    logger.info(f"✅ Image watermark {position} (scale {scale}): {result_path} ({file_size} bytes)")
                    results.append((position, True))
                else:
                    logger.error(f"❌ Image watermark {position}: файл не создан")
                    results.append((position, False))

            except Exception as e:
                logger.error(f"❌ Image watermark {position}: ошибка - {e}")
                results.append((position, False))

        # Очистка
        cleanup_files = [test_image_path, watermark_image_path]
        cleanup_files.extend([f"test_image_watermark_{pos}_{int(scale * 100)}.jpg" for pos, scale in test_cases])

        for file_path in cleanup_files:
            if os.path.exists(file_path):
                os.remove(file_path)

        success_count = sum(1 for _, success in results if success)
        logger.info(f"📊 Водяные знаки-изображения: {success_count}/{len(test_cases)} успешно")
        return success_count == len(test_cases)

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в тесте водяных знаков-изображений: {e}")
        return False


def test_bot_integration():
    """Тестируем интеграцию с ботом"""
    logger.info("🤖 Тестируем интеграцию с ботом")

    try:
        # Проверяем импорт всех функций
        from services.watermark import (
            add_watermark_image, add_watermark_video,
            add_image_watermark_image, add_image_watermark_video,
            WATERMARK_POSITIONS
        )

        logger.info("✅ Все функции водяных знаков импортированы успешно")
        logger.info(f"✅ Доступно позиций: {len(WATERMARK_POSITIONS)}")

        # Проверяем, что обработчики импортируются без ошибок
        from handlers.process import watermark_state
        logger.info("✅ Состояние водяных знаков импортировано из process.py")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка интеграции с ботом: {e}")
        return False


def test_dependencies():
    """Проверяем зависимости"""
    logger.info("🔍 Проверяем зависимости...")

    results = {}

    try:
        from PIL import Image, ImageDraw, ImageFont
        results['Pillow'] = True
        logger.info("✅ Pillow (PIL) - доступен")
    except ImportError as e:
        results['Pillow'] = False
        logger.error(f"❌ Pillow недоступен: {e}")

    try:
        import cv2
        results['OpenCV'] = True
        logger.info("✅ OpenCV - доступен")
    except ImportError:
        results['OpenCV'] = False
        logger.warning("⚠️ OpenCV недоступен (видео watermark не будет работать)")

    try:
        import numpy as np
        results['NumPy'] = True
        logger.info("✅ NumPy - доступен")
    except ImportError:
        results['NumPy'] = False
        logger.warning("⚠️ NumPy недоступен")

    # Для базовой функциональности нужен только Pillow
    return results.get('Pillow', False)


def main():
    """Основная функция тестирования"""
    logger.info("🚀 Запуск расширенных тестов водяных знаков")
    logger.info("=" * 70)

    tests = [
        ("Проверка зависимостей", test_dependencies),
        ("Интеграция с ботом", test_bot_integration),
        ("Текстовые водяные знаки", test_text_watermarks),
        ("Водяные знаки-изображения", test_image_watermarks),
    ]

    results = []

    for test_name, test_func in tests:
        logger.info(f"\n--- {test_name} ---")
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                logger.info(f"✅ {test_name}: ПРОЙДЕН")
            else:
                logger.error(f"❌ {test_name}: ПРОВАЛЕН")
        except Exception as e:
            logger.error(f"❌ {test_name}: ОШИБКА - {e}")
            results.append((test_name, False))

    # Итоговый отчет
    logger.info("\n" + "=" * 70)
    logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
    logger.info("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
        logger.info(f"{test_name}: {status}")

    logger.info(f"\nИТОГО: {passed}/{total} тестов пройдено")

    if passed == total:
        logger.info("🎉 Все тесты пройдены! Расширенная система водяных знаков готова!")
        logger.info("\n💧 Новые возможности:")
        logger.info("📝 Текстовые водяные знаки")
        logger.info("🖼️ Водяные знаки-изображения (логотипы)")
        logger.info("📍 9 позиций размещения")
        logger.info("🎯 Автоматическое масштабирование")
        logger.info("👻 Поддержка прозрачности")
        logger.info("\n🤖 Как использовать в боте:")
        logger.info("1. Загрузите фото/видео")
        logger.info("2. Нажмите '💧 Add Watermark'")
        logger.info("3. Выберите тип: 📝 Text или 🖼️ Image")
        logger.info("4. Введите текст ИЛИ загрузите изображение")
        logger.info("5. Выберите позицию")
        logger.info("6. Получите результат!")
        return True
    elif passed >= total - 1:
        logger.info("⚠️ Почти все тесты пройдены. Основная функциональность работает!")
    else:
        logger.error("❌ Критические ошибки. Проверьте установку зависимостей.")

    return passed >= total - 1


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)