import os
import shutil
import subprocess
from config import TEMP_DIR, OUTPUT_DIR
import uuid
import logging

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
    """Меняет метаданные видео (title, artist, comment) через ffmpeg."""
    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, os.path.basename(input_file))
    # Устанавливаем уникальный seed для случайности на основе uuid
    seed = uuid.uuid4().int
    random.seed(seed)
    logging.info(f"Using seed for metadata: {seed}")
    title = random_string(10)
    artist = random_string(10)
    comment = random_string(16)
    logging.info(f"Randomizing metadata for {output_file}: title={title}, artist={artist}, comment={comment}")
    cmd = [
        "ffmpeg",
        "-i", input_file,
        "-metadata", f"title={title}",
        "-metadata", f"artist={artist}",
        "-metadata", f"comment={comment}",
        "-c", "copy",
        output_file,
        "-y"
    ]
    subprocess.run(cmd, check=True)
    return output_file


from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import piexif


def rand_str(n=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def randomize_exif(input_file: str, output_file: str = None) -> str:
    """Меняет EXIF-метаданные у фото и применяет случайные эффекты (brightness, contrast, color, noise)."""
    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, f"{uuid.uuid4().hex}.jpg")
    # Устанавливаем уникальный seed для случайности на основе uuid
    seed = uuid.uuid4().int
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))  # numpy seed должен быть 0-2**32-1
    logging.info(f"Using seed for EXIF and effects: {seed}")
    img = Image.open(input_file)
    exif_bytes = img.info.get('exif', None)
    try:
        exif_dict = piexif.load(exif_bytes) if exif_bytes else {"0th": {}, "Exif": {}, "GPS": {}, "1st": {},
                                                                "thumbnail": None}
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    # Случайные значения для разных EXIF-полей
    artist = rand_str(8)
    copyright_ = rand_str(12)
    description = rand_str(16)
    software = rand_str(10)
    datetime_ = f"20{random.randint(10, 29):02d}:{random.randint(1, 12):02d}:{random.randint(1, 28):02d} {random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
    logging.info(
        f"Randomizing EXIF for {output_file}: Artist={artist}, Copyright={copyright_}, Description={description}, Software={software}, DateTime={datetime_}")
    exif_dict['0th'][piexif.ImageIFD.Artist] = artist.encode()
    exif_dict['0th'][piexif.ImageIFD.Copyright] = copyright_.encode()
    exif_dict['0th'][piexif.ImageIFD.ImageDescription] = description.encode()
    exif_dict['0th'][piexif.ImageIFD.Software] = software.encode()
    exif_dict['0th'][piexif.ImageIFD.DateTime] = datetime_.encode()
    exif_bytes = piexif.dump(exif_dict)

    # Применяем ультра-микроскопические эффекты (~1/100000 от оригинала)
    # Brightness: 0.99999 - 1.00001
    brightness_factor = random.uniform(0.99, 1.1)
    img = ImageEnhance.Brightness(img).enhance(brightness_factor)
    # Contrast: 0.99999 - 1.00001
    contrast_factor = random.uniform(0.99, 1.1)
    img = ImageEnhance.Contrast(img).enhance(contrast_factor)
    # Color (saturation): 0.99999 - 1.00001
    color_factor = random.uniform(0.989, 1.1) #for dsfsdf
    img = ImageEnhance.Color(img).enhance(color_factor)
    # Noise
    noise_strength = random.uniform(0.00001, 0.0001)
    img_array = np.array(img)
    noise = np.random.normal(0, noise_strength * 255, img_array.shape).astype(np.uint8)
    img_array = np.clip(img_array + noise, 0, 255)
    img = Image.fromarray(img_array.astype(np.uint8))

    logging.info(
        f"Applied effects: brightness={brightness_factor:.2f}, contrast={contrast_factor:.2f}, color={color_factor:.2f}, noise_strength={noise_strength:.4f}")

    # Замена одного случайного пикселя для уникальности pHash
    width, height = img.size
    px = random.randint(0, width - 1)
    py = random.randint(0, height - 1)
    new_color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img.putpixel((px, py), new_color)
    logging.info(f"Replaced pixel at ({px}, {py}) with color {new_color}")

    img.convert('RGB').save(output_file, format='JPEG', exif=exif_bytes, quality=95)
    return output_file

