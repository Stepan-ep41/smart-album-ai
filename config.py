import os
import json
import hashlib
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Папка для хранения всех файлов баз данных
DATABASES_DIR = Path(os.getenv("DATABASES_DIR", BASE_DIR / "databases")).resolve()
DATABASES_DIR.mkdir(parents=True, exist_ok=True)

# Файл с сохраненными настройками пользователя
SETTINGS_FILE = BASE_DIR / "user_settings.json"


def _normalize_path_str(path: Path | str) -> str:
    resolved = Path(path).resolve()
    return str(resolved).lower() if os.name == "nt" else str(resolved)


def get_db_path(photos_dir: Path | str | None = None) -> Path:
    """
    Возвращает путь к файлу БД, жестко привязанный к указанной папке с фото.
    Каждой уникальной папке соответствует отдельный файл БД в папке DATABASES_DIR.
    """
    target = Path(photos_dir if photos_dir is not None else PHOTOS_DIR).resolve()
    folder_slug = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', target.name) or "root"
    norm_path = _normalize_path_str(target)
    path_hash = hashlib.sha256(norm_path.encode("utf-8")).hexdigest()[:10]
    return DATABASES_DIR / f"album_{folder_slug}_{path_hash}.db"


def _load_persisted_photos_dir() -> Path:
    env_dir = os.getenv("PHOTOS_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    if SETTINGS_FILE.is_file():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "photos_dir" in data:
                    p = Path(data["photos_dir"]).resolve()
                    if p.exists() and p.is_dir():
                        return p
        except Exception:
            pass
    return (BASE_DIR / "photos").resolve()


# Папка с фото: по умолчанию берем сохраненную или тестовую папку 'photos' в корне проекта
PHOTOS_DIR = _load_persisted_photos_dir()

# Путь к файлу базы данных, привязанный к текущей PHOTOS_DIR
DB_PATH = get_db_path(PHOTOS_DIR)


def set_photos_dir(new_path: Path | str) -> Path:
    """Устанавливает новый путь к фото, перепривязывает DB_PATH и сохраняет настройку."""
    global PHOTOS_DIR, DB_PATH
    PHOTOS_DIR = Path(new_path).resolve()
    DB_PATH = get_db_path(PHOTOS_DIR)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"photos_dir": str(PHOTOS_DIR)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return PHOTOS_DIR


# Кэш сгенерированных превью (миниатюр)
CACHE_DIR = Path(os.getenv("CACHE_DIR", BASE_DIR / "cache")).resolve()
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
