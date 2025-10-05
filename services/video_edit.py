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

    # Составляем цепочку фильтров для ffmpeg
    filter_chain = f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation},noise=alls={noise_strength}:allf=t+u"

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
