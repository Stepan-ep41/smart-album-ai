import os
from pathlib import Path

# Папка с фото: по умолчанию берем тестовую папку 'photos' в корне проекта
PHOTOS_DIR = Path(os.getenv("PHOTOS_DIR", "./photos")).resolve()

# Путь к файлу базы данных
DB_PATH = Path(os.getenv("DB_PATH", "./album.db")).resolve()

# Кэш сгенерированных превью (миниатюр)
CACHE_DIR = Path(os.getenv("CACHE_DIR", "./cache")).resolve()
THUMBS_DIR = CACHE_DIR / "thumbs"

# Доступные размеры превью (длина большей стороны в пикселях)
THUMB_SIZES = (240, 480, 960)
THUMB_QUALITY = int(os.getenv("THUMB_QUALITY", "80"))

# Сколько секунд браузер может не перезапрашивать готовое превью
THUMB_MAX_AGE = 7 * 24 * 60 * 60

# Настройки сервера
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Создаем папку для фото, если ее еще нет (для локальных тестов)
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)