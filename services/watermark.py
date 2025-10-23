import os
import uuid
import logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional, Tuple, Union
from config import TEMP_DIR, OUTPUT_DIR

logger = logging.getLogger(__name__)

try:
    import cv2  # Это правильный импорт для OpenCV (пакет называется opencv-python)
except Exception:
    cv2 = None
    logger.warning(
        "OpenCV (cv2) is not available. Video watermarking functions will be disabled until opencv-python is installed.")

import numpy as np

# Позиции для водяных знаков
WATERMARK_POSITIONS = {
    'top_left': 'Top Left',
    'top_center': 'Top Center',
    'top_right': 'Top Right',
    'middle_left': 'Middle Left',
    'center': 'Center',
    'middle_right': 'Middle Right',
    'bottom_left': 'Bottom Left',
    'bottom_center': 'Bottom Center',
    'bottom_right': 'Bottom Right'
    ,
    'full': 'Full Screen'
}


class WatermarkService:
    """Сервис для добавления текстовых водяных знаков"""

    def __init__(self):
        self.default_font_size = 48
        self.default_opacity = 128  # 50% прозрачности (0-255)
        self.default_color = (255, 255, 255, self.default_opacity)  # Белый с прозрачностью
        self.margin = 20  # Отступ от краев

    def _get_font(self, size: int) -> ImageFont.ImageFont:
        """Получить шрифт. Пытается использовать системный, иначе дефолтный."""
        try:
            # Пробуем найти системный шрифт
            font_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/TTF/arial.ttf',
                '/System/Library/Fonts/Arial.ttf',  # macOS
                'C:\\Windows\\Fonts\\arial.ttf',  # Windows
            ]

            for font_path in font_paths:
                if os.path.exists(font_path):
                    return ImageFont.truetype(font_path, size)

            # Если системный шрифт не найден, используем дефолтный
            return ImageFont.load_default()

        except Exception as e:
            logger.warning(f"Could not load font: {e}, using default")
            return ImageFont.load_default()

    def _calculate_position(self, image_size: Tuple[int, int], text_size: Tuple[int, int],
                            position: str) -> Tuple[int, int]:
        """Вычисляет координаты для размещения текста"""
        img_width, img_height = image_size
        text_width, text_height = text_size

        # Маппинг позиций на координаты
        positions_map = {
            'top_left': (self.margin, self.margin),
            'top_center': ((img_width - text_width) // 2, self.margin),
            'top_right': (img_width - text_width - self.margin, self.margin),
            'middle_left': (self.margin, (img_height - text_height) // 2),
            'center': ((img_width - text_width) // 2, (img_height - text_height) // 2),
            'middle_right': (img_width - text_width - self.margin, (img_height - text_height) // 2),
            'bottom_left': (self.margin, img_height - text_height - self.margin),
            'bottom_center': ((img_width - text_width) // 2, img_height - text_height - self.margin),
            'bottom_right': (img_width - text_width - self.margin, img_height - text_height - self.margin)
        }
        # special case: full screen -> place at (0,0) and caller should scale/resize accordingly
        if position == 'full':
            return (0, 0)

        return positions_map.get(position, positions_map['bottom_right'])

    def _remove_border_white_bg(self, pil_img: Image.Image, bg_threshold: int = 240,
                                blur_radius: int = 2) -> Image.Image:
        """
        Remove white (or nearly white) background from the watermark image.
        This more aggressive variant removes white pixels anywhere (not only border-connected)
        which helps when logos contain white parts that should become transparent.

        If the operation would make the entire watermark fully transparent (for example,
        when the watermark is completely white), a fallback is applied: we try to
        recover a silhouette by thresholding non-white pixels; if that fails (pure white
        image), we convert the watermark to a black silhouette with a medium alpha so
        it remains visible on light backgrounds.

        Args:
            pil_img: RGBA image
            bg_threshold: 0-255 threshold to consider a pixel white
            blur_radius: gaussian blur radius to feather alpha edges

        Returns:
            Image with updated alpha channel
        """
        try:
            img = pil_img.convert('RGBA')
            arr = np.array(img)
            h, w = arr.shape[:2]

            # Channels as int for calculations
            r = arr[:, :, 0].astype(np.int32)
            g = arr[:, :, 1].astype(np.int32)
            b = arr[:, :, 2].astype(np.int32)

            # Use luminance to determine 'whiteness' (better than simple avg)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)

            # Global white mask: wherever luminance >= threshold -> treat as background
            white_mask = luminance >= float(bg_threshold)

            # Existing alpha (if any)
            if arr.shape[2] == 4:
                alpha = arr[:, :, 3].astype(np.float32)
            else:
                alpha = np.full((h, w), 255.0, dtype=np.float32)

            # Remove white pixels globally by setting their alpha to 0
            alpha[white_mask] = 0.0

            # Feather edges by blurring alpha channel
            from PIL import ImageFilter
            alpha_img = Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8))
            if blur_radius > 0:
                alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            alpha = np.array(alpha_img).astype(np.uint8)

            # Fallback: if watermark became fully transparent, try to recover a silhouette
            if alpha.max() == 0:
                # Try thresholding non-white pixels as silhouette
                non_white_mask = luminance < 255.0
                if non_white_mask.sum() > 0:
                    alpha = (non_white_mask.astype(np.uint8) * 255)
                    # Feather slightly
                    alpha_img = Image.fromarray(alpha)
                    if blur_radius > 0:
                        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=max(1, blur_radius // 2)))
                    alpha = np.array(alpha_img).astype(np.uint8)
                else:
                    # The watermark is (nearly) fully white. Convert to black silhouette
                    # and give it a medium alpha so it remains visible on light backgrounds.
                    arr[:, :, 0:3] = 0  # set RGB to black
                    alpha = np.full((h, w), 200, dtype=np.uint8)

            # Put updated alpha back into array
            arr[:, :, 3] = alpha

            return Image.fromarray(arr.astype(np.uint8), mode='RGBA')
        except Exception:
            # On any failure, return original image to avoid data loss
            return pil_img

    def _remove_checkerboard_bg(self, pil_img: Image.Image, tile_min: int = 4,
                                similarity_thresh: float = 0.95) -> Image.Image:
        """
        Detect and remove a repeating checkerboard-like pattern (often used to indicate transparency)
        which got embedded as light/dark squares in the PNG itself.

        Strategy:
        - Convert to grayscale and downscale to speed up detection.
        - Search for a small tile size (powers of two between tile_min and 64) that, when repeated,
          reconstructs the image with high similarity.
        - If tile detected, create a mask by considering tiles that closely match either the 'light'
          or 'dark' tile color and set those pixels to transparent.

        This is heuristic and conservative: it only acts when a clear repeating pattern is found.
        """
        # Checkerboard removal removed — keep function as no-op for backward compatibility
        return pil_img

    # clean_foreground_image removed — use _remove_border_white_bg directly when needed

    # paste_on_background removed — use standard overlay/paste where needed

    def add_image_watermark_to_image(self, input_path: str, watermark_image_path: str,
                                     position: str = 'bottom_right', scale: float = 0.2,
                                     opacity: Optional[int] = None, output_path: Optional[str] = None,
                                     remove_bg: bool = True, bg_threshold: int = 240) -> str:
        """
        Добавляет изображение-водяной знак к изображению

        Args:
            input_path: Путь к исходному изображению
            watermark_image_path: Путь к изображению водяного знака
            position: Позиция ('top_left', 'center', 'bottom_right', etc.)
            scale: Масштаб водяного знака относительно изображения (0.1 = 10%)
            opacity: Прозрачность 0-255 (по умолчанию 128)
            output_path: Путь для сохранения (автогенерация если None)

        Returns:
            Путь к файлу с водяным знаком
        """
        try:
            if output_path is None:
                # Default output: prefer PNG when source is PNG to preserve transparency
                in_ext = os.path.splitext(input_path)[1].lower()
                if in_ext == '.png':
                    output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4().hex}.png")
                else:
                    output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4().hex}.jpg")

            # Открываем основное изображение
            base_image = Image.open(input_path)

            # Открываем водяной знак
            watermark = Image.open(watermark_image_path)

            # Конвертируем в RGBA для работы с прозрачностью
            if base_image.mode != 'RGBA':
                base_image = base_image.convert('RGBA')
            if watermark.mode != 'RGBA':
                watermark = watermark.convert('RGBA')

            # Вычисляем размер водяного знака
            base_width, base_height = base_image.size
            # Если позиция full, масштабируем водяной знак на весь кадр
            if position == 'full':
                watermark_width = base_width
                watermark_height = base_height
                watermark = watermark.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)
            else:
                watermark_width = int(base_width * scale)
                watermark_height = int((watermark.height * watermark_width) / watermark.width)
                # Изменяем размер водяного знака
                watermark = watermark.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)

            # Изменяем размер водяного знака
            watermark = watermark.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)

            # Опционально удаляем фон (белые/почти белые пиксели) у водяного знака
            # Используем объединённый helper, который обрабатывает tiled/checkerboard и white-bg
            if remove_bg:
                try:
                    watermark = self._remove_border_white_bg(watermark, bg_threshold=bg_threshold, blur_radius=2)
                except Exception:
                    pass

            # Если водяной знак содержит прозрачные пиксели, по умолчанию используем PNG вывод
            if output_path is None and watermark.mode == 'RGBA':
                try:
                    a = watermark.split()[-1]
                    a_min, a_max = a.getextrema()
                    if a_min < 255:
                        # Водяной знак имеет прозрачность -> предпочитаем PNG
                        output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4().hex}.png")
                except Exception:
                    # На случай ошибки при проверке альфа-канала — ничего не делаем
                    pass

            # Применяем прозрачность к водяному знаку
            if opacity is None:
                opacity = 255  # Полная непрозрачность по умолчанию для сохранения оригинального альфа-канала

            # Если файл уже имеет альфа-канал (PNG с прозрачностью), используем его
            if watermark.mode == 'RGBA':
                # Получаем существующий альфа-канал
                r, g, b, a = watermark.split()

                if opacity < 255:
                    # Применяем opacity только к непрозрачным пикселям
                    # Сохраняем существующую прозрачность
                    a = a.point(lambda p: 0 if p == 0 else int(p * (opacity / 255)))

                watermark = Image.merge('RGBA', (r, g, b, a))
            else:
                # Если файл без альфа-канала, применяем общую прозрачность
                if opacity < 255:
                    alpha = Image.new('L', watermark.size, opacity)
                    watermark.putalpha(alpha)

            # Вычисляем позицию
            x, y = self._calculate_position(base_image.size, watermark.size, position)

            # Для позиции full мы хотим, чтобы водяной знак покрывал весь кадр, поэтому x,y остаются (0,0)

            # Создаем прозрачный слой для водяного знака
            overlay = Image.new('RGBA', base_image.size, (0, 0, 0, 0))

            # Вставляем водяной знак с учётом альфа-канала
            # Paste watermark on top of base image using alpha channel
            overlay.paste(watermark, (x, y), watermark)
            result = Image.alpha_composite(base_image, overlay)

            # Сохраняем результат. Если результат имеет альфа-канал и целевой
            # формат поддерживает альфу (png/webp/tiff), сохраним с прозрачностью.
            out_ext = os.path.splitext(output_path)[1].lower()
            supports_alpha = out_ext in ['.png', '.webp', '.tiff']

            if result.mode == 'RGBA':
                if supports_alpha:
                    # Сохраняем как PNG, чтобы не потерять альфу
                    result.save(output_path, 'PNG')
                else:
                    # Формат не поддерживает альфу -> сворачиваем на белый фон и сохраняем JPEG
                    background = Image.new('RGB', result.size, (255, 255, 255))
                    background.paste(result, mask=result.split()[-1])
                    background.save(output_path, 'JPEG', quality=95)
            else:
                # Нет альфа-канала -> сохраняем по расширению (png/jpg)
                if out_ext == '.png':
                    result.save(output_path, 'PNG')
                else:
                    result = result.convert('RGB')
                    result.save(output_path, 'JPEG', quality=95)

            logger.info(f"Image watermark added successfully: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to add image watermark: {e}")
            raise

    def add_watermark_to_image(self, input_path: str, text: str, position: str = 'bottom_right',
                               font_size: Optional[int] = None, opacity: Optional[int] = None,
                               output_path: Optional[str] = None) -> str:
        """
        Добавляет текстовый водяной знак к изображению

        Args:
            input_path: Путь к исходному изображению
            text: Текст водяного знака
            position: Позиция ('top_left', 'center', 'bottom_right', etc.)
            font_size: Размер шрифта (по умолчанию зависит от размера изображения)
            opacity: Прозрачность 0-255 (по умолчанию 128)
            output_path: Путь для сохранения (автогенерация если None)

        Returns:
            Путь к файлу с водяным знаком
        """
        try:
            if output_path is None:
                in_ext = os.path.splitext(input_path)[1].lower()
                if in_ext == '.png':
                    output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4().hex}.png")
                else:
                    output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4().hex}.jpg")

            # Открываем изображение
            image = Image.open(input_path)

            # Конвертируем в RGBA для работы с прозрачностью
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            # Автоматический размер шрифта на основе размера изображения
            if font_size is None:
                # Для full-screen делаем максимально большой шрифт
                if position == 'full':
                    font_size = max(40, min(image.width, image.height) // 6)
                else:
                    font_size = max(20, min(image.width, image.height) // 25)

            if opacity is None:
                opacity = self.default_opacity

            # Получаем шрифт
            font = self._get_font(font_size)

            # Создаем прозрачный слой для текста
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Вычисляем размер текста
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Вычисляем позицию
            x, y = self._calculate_position(image.size, (text_width, text_height), position)

            # Если позиция full — расширяем текст, центрируем и увеличиваем прозрачность (чтобы не закрывать полностью)
            if position == 'full':
                # центруем по центру, x,y уже (0,0) из _calculate_position
                x = 0
                y = 0
                # Создадим фон-оверлей с текстом, центрируем позже используя большие отступы
                # Для simplicity — оставим текст отрисованным в центре масштабированного шрифта
                # Пересчитаем координаты для центра
                x = (image.width - text_width) // 2
                y = (image.height - text_height) // 2

            # Рисуем текст с тенью для лучшей видимости
            shadow_offset = 2
            shadow_color = (0, 0, 0, opacity // 2)  # Полупрозрачная тень
            text_color = (255, 255, 255, opacity)  # Белый текст

            # Тень
            draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color)
            # Основной текст
            draw.text((x, y), text, font=font, fill=text_color)

            # Объединяем изображение с водяным знаком
            watermarked = Image.alpha_composite(image, overlay)

            # Сохраняем результат аналогично: сохраняем PNG при наличии альфы и поддерживаемом расширении
            out_ext = os.path.splitext(output_path)[1].lower()
            supports_alpha = out_ext in ['.png', '.webp', '.tiff']

            if watermarked.mode == 'RGBA':
                if supports_alpha:
                    watermarked.save(output_path, 'PNG')
                else:
                    background = Image.new('RGB', watermarked.size, (255, 255, 255))
                    background.paste(watermarked, mask=watermarked.split()[-1])
                    background.save(output_path, 'JPEG', quality=95)
            else:
                if out_ext == '.png':
                    watermarked.save(output_path, 'PNG')
                else:
                    watermarked = watermarked.convert('RGB')
                    watermarked.save(output_path, 'JPEG', quality=95)

            logger.info(f"Watermark added successfully: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to add watermark: {e}")
            raise

    def add_image_watermark_to_video(self, input_path: str, watermark_image_path: str,
                                     position: str = 'bottom_right', scale: float = 0.2,
                                     opacity: Optional[int] = None, output_path: Optional[str] = None,
                                     remove_bg: bool = True, bg_threshold: int = 240) -> str:
        """
        Добавляет изображение-водяной знак к видео

        Args:
            input_path: Путь к исходному видео
            watermark_image_path: Путь к изображению водяного знака
            position: Позиция водяного знака
            scale: Масштаб водяного знака относительно видео (0.1 = 10%)
            opacity: Прозрачность 0-255
            output_path: Путь для сохранения

        Returns:
            Путь к файлу с водяным знаком
        """
        try:
            if output_path is None:
                output_path = os.path.join(OUTPUT_DIR, f"watermarked_video_{uuid.uuid4().hex}.mp4")

            # Открываем видео
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise ValueError(f"Cannot open video: {input_path}")

            # Получаем параметры видео
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Загружаем и подготавливаем водяной знак
            watermark_pil = Image.open(watermark_image_path)
            if watermark_pil.mode != 'RGBA':
                watermark_pil = watermark_pil.convert('RGBA')

            # Вычисляем размер водяного знака для видео
            # Если позиция full — масштабируем водяной знак до размеров видео
            if position == 'full':
                watermark_width = width
                watermark_height = height
                watermark_pil = watermark_pil.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)
            else:
                watermark_width = int(width * scale)
                watermark_height = int((watermark_pil.height * watermark_width) / watermark_pil.width)
                watermark_pil = watermark_pil.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)
            # Опционально удаляем фон у водяного знака
            if remove_bg:
                try:
                    watermark_pil = self._remove_border_white_bg(watermark_pil, bg_threshold=bg_threshold,
                                                                 blur_radius=2)
                except Exception:
                    pass

            # Применяем прозрачность к водяному знаку
            if opacity is None:
                opacity = 255  # Полная непрозрачность по умолчанию для сохранения оригинального альфа-канала

            # Если файл уже имеет альфа-канал (PNG с прозрачностью), используем его
            if watermark_pil.mode == 'RGBA':
                # Получаем существующий альфа-канал
                r, g, b, a = watermark_pil.split()

                if opacity < 255:
                    # Применяем opacity только к непрозрачным пикселям
                    # Сохраняем существующую прозрачность
                    a = a.point(lambda p: 0 if p == 0 else int(p * (opacity / 255)))

                watermark_pil = Image.merge('RGBA', (r, g, b, a))
            else:
                # Если файл без альфа-канала, применяем общую прозрачность
                if opacity < 255:
                    alpha = Image.new('L', watermark_pil.size, opacity)
                    watermark_pil.putalpha(alpha)

            # Конвертируем в OpenCV формат (BGR + Alpha)
            watermark_array = np.array(watermark_pil)
            if watermark_array.shape[2] == 4:  # RGBA
                # Конвертируем RGBA в BGRA для OpenCV
                watermark_cv = cv2.cvtColor(watermark_array, cv2.COLOR_RGBA2BGRA)
            else:  # RGB
                watermark_cv = cv2.cvtColor(watermark_array, cv2.COLOR_RGB2BGR)

            # Вычисляем позицию
            x, y = self._calculate_position((width, height), (watermark_width, watermark_height), position)

            # Для full позиции хотим расположить водяной знак в (0,0)
            if position == 'full':
                x, y = 0, 0

            # Создаем временный файл для обработанного видео
            temp_output = os.path.join(TEMP_DIR, f"temp_watermarked_{uuid.uuid4().hex}.avi")

            # Настраиваем кодек для записи
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))

            frame_count = 0
            logger.info(f"Processing video with image watermark: {total_frames} frames at {fps} FPS")
            logger.info(f"Watermark size: {watermark_width}x{watermark_height} at position: {position}")

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Добавляем водяной знак к кадру
                frame_with_watermark = self._overlay_image_on_frame(frame, watermark_cv, x, y)
                out.write(frame_with_watermark)

                frame_count += 1
                if frame_count % 30 == 0:
                    logger.info(f"Processed {frame_count}/{total_frames} frames")

            logger.info(f"Finished processing {frame_count} frames")

            # Закрываем файлы
            cap.release()
            out.release()

            # Конвертируем в MP4 и копируем аудио
            import subprocess

            temp_video_only = os.path.join(TEMP_DIR, f"temp_video_only_{uuid.uuid4().hex}.mp4")

            cmd_video = [
                "ffmpeg",
                "-i", temp_output,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",
                "-y", temp_video_only
            ]

            subprocess.run(cmd_video, check=True, capture_output=True, text=True)

            cmd_final = [
                "ffmpeg",
                "-i", temp_video_only,
                "-i", input_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-shortest",
                "-y", output_path
            ]

            subprocess.run(cmd_final, check=True, capture_output=True, text=True)

            # Удаляем временные файлы
            os.remove(temp_output)
            os.remove(temp_video_only)

            logger.info(f"Video image watermark completed: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Video image watermark failed: {e}")
            raise
        finally:
            if 'cap' in locals():
                cap.release()
            if 'out' in locals():
                out.release()

    def _overlay_image_on_frame(self, frame: np.ndarray, watermark: np.ndarray, x: int, y: int) -> np.ndarray:
        """Накладывает изображение-водяной знак на кадр видео с учетом прозрачности"""
        try:
            frame_h, frame_w = frame.shape[:2]
            watermark_h, watermark_w = watermark.shape[:2]

            # Проверяем границы
            if x + watermark_w > frame_w:
                watermark_w = frame_w - x
                watermark = watermark[:, :watermark_w]
            if y + watermark_h > frame_h:
                watermark_h = frame_h - y
                watermark = watermark[:watermark_h, :]

            if watermark_w <= 0 or watermark_h <= 0:
                return frame

            # Извлекаем области
            frame_region = frame[y:y + watermark_h, x:x + watermark_w]

            # Если водяной знак имеет альфа-канал
            if watermark.shape[2] == 4:
                # Нормализуем альфа-канал
                alpha = watermark[:, :, 3] / 255.0
                alpha = np.stack([alpha] * 3, axis=-1)

                # Применяем blend
                watermark_rgb = watermark[:, :, :3]
                blended = frame_region * (1 - alpha) + watermark_rgb * alpha
                frame[y:y + watermark_h, x:x + watermark_w] = blended.astype(np.uint8)
            else:
                # Простое наложение без прозрачности
                frame[y:y + watermark_h, x:x + watermark_w] = watermark

            return frame

        except Exception as e:
            logger.error(f"Error overlaying watermark: {e}")
            return frame

    def add_watermark_to_video(self, input_path: str, text: str, position: str = 'bottom_right',
                               font_size: Optional[int] = None, opacity: Optional[int] = None,
                               output_path: Optional[str] = None) -> str:
        """
        Добавляет текстовый водяной знак к видео

        Args:
            input_path: Путь к исходному видео
            text: Текст водяного знака
            position: Позиция водяного знака
            font_size: Размер шрифта
            opacity: Прозрачность
            output_path: Путь для сохранения

        Returns:
            Путь к файлу с водяным знаком
        """
        try:
            if output_path is None:
                output_path = os.path.join(OUTPUT_DIR, f"watermarked_video_{uuid.uuid4().hex}.mp4")

            # Открываем видео
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise ValueError(f"Cannot open video: {input_path}")

            # Получаем параметры видео
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Создаем временный файл для обработанного видео
            temp_output = os.path.join(TEMP_DIR, f"temp_watermarked_{uuid.uuid4().hex}.avi")

            # Настраиваем кодек для записи
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))

            # Параметры текста для OpenCV
            if font_size is None:
                font_size = max(20, min(width, height) // 25)

            if opacity is None:
                opacity = 0.7  # Для OpenCV используем от 0.0 до 1.0
            else:
                opacity = opacity / 255.0

            # Вычисляем позицию текста
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = font_size / 48.0  # Масштабирование относительно базового размера
            thickness = max(1, int(font_scale * 2))

            # Получаем размер текста
            (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)

            # Вычисляем координаты
            x, y = self._calculate_position_opencv((width, height), (text_width, text_height), position)

            frame_count = 0
            logger.info(f"Processing video: {total_frames} frames at {fps} FPS")
            logger.info(f"Video dimensions: {width}x{height}")
            logger.info(f"Watermark text: '{text}' at position: {position}")
            logger.info(f"Text position coordinates: x={x}, y={y}")

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Создаем копию кадра для наложения
                overlay = frame.copy()

                # Добавляем тень
                cv2.putText(overlay, text, (x + 2, y + 2), font, font_scale, (0, 0, 0), thickness + 1)
                # Добавляем основной текст
                cv2.putText(overlay, text, (x, y), font, font_scale, (255, 255, 255), thickness)

                # Смешиваем с исходным кадром
                cv2.addWeighted(overlay, opacity, frame, 1 - opacity, 0, frame)

                out.write(frame)

                frame_count += 1
                if frame_count % 30 == 0:  # Логируем прогресс каждые 30 кадров
                    logger.info(f"Processed {frame_count}/{total_frames} frames")

            logger.info(f"Finished processing {frame_count} frames")

            # Закрываем файлы
            cap.release()
            out.release()

            # Конвертируем в MP4 и копируем аудио из исходного видео
            import subprocess

            # Сначала конвертируем видео с водяным знаком в MP4
            temp_video_only = os.path.join(TEMP_DIR, f"temp_video_only_{uuid.uuid4().hex}.mp4")

            cmd_video = [
                "ffmpeg",
                "-i", temp_output,  # Видео с водяным знаком
                "-c:v", "libx264",  # Кодек видео
                "-preset", "fast",
                "-crf", "23",
                "-an",  # Убираем аудио
                "-y", temp_video_only
            ]

            result = subprocess.run(cmd_video, check=True, capture_output=True, text=True)
            logger.info("Video conversion completed")

            # Теперь объединяем обработанное видео с аудио из исходного файла
            cmd_final = [
                "ffmpeg",
                "-i", temp_video_only,  # Обработанное видео (без звука)
                "-i", input_path,  # Исходное видео (со звуком)
                "-c:v", "copy",  # Копируем видео как есть
                "-c:a", "aac",  # Кодек аудио
                "-map", "0:v:0",  # Берем видео из первого файла (с watermark)
                "-map", "1:a:0?",  # Берем аудио из второго файла (исходного)
                "-shortest",  # Обрезать по самому короткому потоку
                "-y", output_path
            ]

            result = subprocess.run(cmd_final, check=True, capture_output=True, text=True)
            logger.info("Audio merging completed")

            # Удаляем временные файлы
            os.remove(temp_output)
            os.remove(temp_video_only)

            logger.info(f"Video watermark completed: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Video watermark failed: {e}")
            raise
        finally:
            if 'cap' in locals():
                cap.release()
            if 'out' in locals():
                out.release()

    def _calculate_position_opencv(self, image_size: Tuple[int, int], text_size: Tuple[int, int],
                                   position: str) -> Tuple[int, int]:
        """Вычисляет координаты для OpenCV (y координата для baseline текста)"""
        img_width, img_height = image_size
        text_width, text_height = text_size

        positions_map = {
            'top_left': (self.margin, self.margin + text_height),
            'top_center': ((img_width - text_width) // 2, self.margin + text_height),
            'top_right': (img_width - text_width - self.margin, self.margin + text_height),
            'middle_left': (self.margin, (img_height + text_height) // 2),
            'center': ((img_width - text_width) // 2, (img_height + text_height) // 2),
            'middle_right': (img_width - text_width - self.margin, (img_height + text_height) // 2),
            'bottom_left': (self.margin, img_height - self.margin),
            'bottom_center': ((img_width - text_width) // 2, img_height - self.margin),
            'bottom_right': (img_width - text_width - self.margin, img_height - self.margin)
        }

        return positions_map.get(position, positions_map['bottom_right'])


# Глобальный экземпляр сервиса
watermark_service = WatermarkService()


def add_watermark_image(input_path: str, text: str, position: str = 'bottom_right',
                        output_path: str = None) -> str:
    """Удобная функция для добавления текстового водяного знака к изображению"""
    return watermark_service.add_watermark_to_image(input_path, text, position, output_path=output_path)


def add_watermark_video(input_path: str, text: str, position: str = 'bottom_right',
                        output_path: str = None) -> str:
    """Удобная функция для добавления текстового водяного знака к видео"""
    return watermark_service.add_watermark_to_video(input_path, text, position, output_path=output_path)


def add_image_watermark_image(input_path: str, watermark_image_path: str, position: str = 'bottom_right',
                              scale: float = 0.2, output_path: str = None,
                              remove_bg: bool = True, bg_threshold: int = 240) -> str:
    """Удобная функция для добавления изображения-водяного знака к изображению"""
    return watermark_service.add_image_watermark_to_image(
        input_path, watermark_image_path, position, scale, opacity=None, output_path=output_path,
        remove_bg=remove_bg, bg_threshold=bg_threshold
    )


def add_image_watermark_video(input_path: str, watermark_image_path: str, position: str = 'bottom_right',
                              scale: float = 0.2, output_path: str = None,
                              remove_bg: bool = True, bg_threshold: int = 240) -> str:
    """Удобная функция для добавления изображения-водяного знака к видео"""
    return watermark_service.add_image_watermark_to_video(
        input_path, watermark_image_path, position, scale, opacity=None, output_path=output_path,
        remove_bg=remove_bg, bg_threshold=bg_threshold
    )