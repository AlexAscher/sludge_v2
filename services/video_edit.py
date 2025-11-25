import os
import shutil
import subprocess
from config import TEMP_DIR, OUTPUT_DIR
import uuid
import logging
import random
import string


def random_string(n=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def randomize_metadata(input_file: str, output_file: str = None) -> str:
    """Меняет метаданные видео и применяет случайные эффекты (brightness, contrast, color, noise) через ffmpeg."""
    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, f"{uuid.uuid4().hex}{os.path.splitext(input_file)[1]}")
    # Устанавливаем уникальный seed для случайности на основе uuid
    seed = uuid.uuid4().int
    random.seed(seed)
    logging.info(f"Using seed for metadata and effects: {seed}")
    title = random_string(10)
    artist = random_string(10)
    comment = random_string(16)
    logging.info(f"Randomizing metadata for {output_file}: title={title}, artist={artist}, comment={comment}")

    # Ультра-микроскопические эффекты (~1/100000 от оригинала)
    brightness = random.uniform(-0.00001, 0.00001)  # -0.00001 to +0.00001
    contrast = random.uniform(0.96999, 1.00001)  # 0.99999 to 1.00001
    saturation = random.uniform(0.97999, 1.00001)  # 0.99999 to 1.00001 for color
    noise_strength = random.uniform(1, 5)  # strength for noise filter

    logging.info(f"Applied effects: brightness={brightness:.4f}, contrast={contrast:.4f}, saturation={saturation:.4f}, noise_strength={noise_strength:.1f}")

    # Получаем размеры видео для случайного пикселя
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        input_file
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        width, height = map(int, probe_result.stdout.strip().split(','))
    except Exception:
        width, height = 1920, 1080  # fallback

    # Случайный пиксель и цвет для drawbox
    px = random.randint(0, max(0, width - 1))
    py = random.randint(0, max(0, height - 1))
    r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
    pixel_color = f"0x{r:02X}{g:02X}{b:02X}"
    logging.info(f"Replacing pixel at ({px}, {py}) with color {pixel_color}")

    # Составляем цепочку фильтров для ffmpeg (с drawbox 1x1 для пикселя)
    filter_chain = f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation},noise=alls={noise_strength}:allf=t+u,drawbox=x={px}:y={py}:w=1:h=1:color={pixel_color}:t=fill"

    cmd = [
        "ffmpeg",
        "-i", input_file,
        "-vf", filter_chain,
        "-metadata", f"title={title}",
        "-metadata", f"artist={artist}",
        "-metadata", f"comment={comment}",
        "-c:v", "libx264",  # Перекодируем видео для применения фильтров
        "-preset", "fast",
        "-c:a", "copy",  # Аудио копируем
        output_file,
        "-y"
    ]
    subprocess.run(cmd, check=True)
    return output_file
