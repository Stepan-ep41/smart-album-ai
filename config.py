import os
from pathlib import Path

# Папка с фото: по умолчанию берем тестовую папку 'photos' в корне проекта
PHOTOS_DIR = Path(os.getenv("PHOTOS_DIR", "./photos")).resolve()

# Путь к файлу базы данных
DB_PATH = Path(os.getenv("DB_PATH", "./album.db")).resolve()

# Настройки сервера
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Создаем папку для фото, если ее еще нет (для локальных тестов)
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)