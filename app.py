import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from db.database import Database
from services.scanner import scan_photos
from services.thumbnails import ThumbnailError, get_thumbnail

app = FastAPI(title="Smart Album")

# Инициализация базы данных
db = Database(str(config.DB_PATH))


class CachedStaticFiles(StaticFiles):
    """Статика с заголовком кэширования, чтобы браузер не перезапрашивал файлы."""

    def __init__(self, *args, cache_control: str = "public, max-age=86400", **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", self.cache_control)
        return response


class DynamicMediaFiles(StaticFiles):
    """Раздает медиа-файлы напрямую из актуальной папки config.PHOTOS_DIR."""

    def __init__(self, cache_control: str = "public, max-age=86400", **kwargs):
        super().__init__(directory=str(config.PHOTOS_DIR), check_dir=False, **kwargs)
        self.cache_control = cache_control

    def lookup_path(self, path: str):
        self.directory = str(config.PHOTOS_DIR)
        self.all_directories = (self.directory,)
        return super().lookup_path(path)

    async def get_response(self, path: str, scope):
        self.directory = str(config.PHOTOS_DIR)
        self.all_directories = (self.directory,)
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", self.cache_control)
        return response


# Раздача фронтенд-статики (CSS, JS).
app.mount(
    "/static",
    CachedStaticFiles(directory="ui/static", cache_control="no-cache"),
    name="static",
)

# Раздача медиа-файлов (фотографий) напрямую с диска
app.mount(
    "/media",
    DynamicMediaFiles(cache_control="no-cache"),
    name="media",
)

# Шаблоны HTML
templates = Jinja2Templates(directory="ui/templates")


class PhotoCaptionUpdate(BaseModel):
    manual_caption: str | None = None


class SettingsUpdate(BaseModel):
    photos_dir: str


class ScanRequest(BaseModel):
    photos_dir: str | None = None


def photo_to_dict(photo) -> dict:
    """Преобразует Row из sqlite3 в JSON-совместимый dict."""
    return {
        "id": photo["id"],
        "relative_path": photo["relative_path"],
        "is_processed": bool(photo["is_processed"]),
        "auto_caption": photo["auto_caption"],
        "manual_caption": photo["manual_caption"],
    }


@app.get("/")
def read_root(request: Request):
    """Главная страница альбома."""
    return templates.TemplateResponse(
        name="index.html",
        request=request,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/settings")
def get_settings():
    """Возвращает текущие настройки приложения и информацию о БД."""
    target_db = config.get_db_path(config.PHOTOS_DIR)
    db_exists = target_db.exists() and target_db.stat().st_size > 0
    return {
        "photos_dir": str(config.PHOTOS_DIR),
        "db_path": str(config.DB_PATH),
        "db_exists": db_exists,
        "stats": db.get_stats(),
    }


@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    """Обновляет путь к папке с фото и переключает БД."""
    raw_path = payload.photos_dir.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Путь к папке не может быть пустым")

    p = Path(raw_path).resolve()
    if not p.exists() or not p.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Указанный путь не существует или не является папкой: {raw_path}",
        )

    config.set_photos_dir(p)
    target_db = config.get_db_path(config.PHOTOS_DIR)
    db.switch_db(str(target_db))

    db_exists = target_db.exists() and target_db.stat().st_size > 0
    return {
        "photos_dir": str(config.PHOTOS_DIR),
        "db_path": str(config.DB_PATH),
        "db_exists": db_exists,
        "stats": db.get_stats(),
    }


@app.get("/api/browse")
def browse(path: str = ""):
    """
    Возвращает содержимое указанной папки:
    дочерние папки и список фотографий.
    """
    clean_path = path.strip("/")
    subfolders = db.get_subfolders(current_dir=clean_path)
    photos = db.get_photos_in_folder(parent_dir=clean_path)

    return {
        "current_path": clean_path,
        "subfolders": subfolders,
        "photos": [photo_to_dict(photo) for photo in photos],
    }


@app.get("/api/search")
def search_photos_endpoint(q: str = ""):
    """
    Поиск фотографий по описанию.
    Возвращает результаты, отсортированные по релевантности совпадения.
    """
    clean_query = q.strip()
    if not clean_query:
        return {"query": "", "count": 0, "photos": []}

    results = db.search_photos(clean_query)
    return {
        "query": clean_query,
        "count": len(results),
        "photos": [photo_to_dict(photo) for photo in results],
    }


@app.get("/api/photos/{photo_id}")
def get_photo(photo_id: int):
    """Возвращает фото и его описания по id."""
    photo = db.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    return photo_to_dict(photo)


@app.patch("/api/photos/{photo_id}")
def update_photo_caption(photo_id: int, payload: PhotoCaptionUpdate):
    """Обновляет ручное описание фото. Пустая строка очищает описание."""
    caption = payload.manual_caption
    if caption is not None:
        caption = caption.strip() or None
        if len(caption or "") > 5000:
            raise HTTPException(status_code=422, detail="Слишком длинное описание")

    photo = db.update_manual_caption(photo_id, caption)
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    return photo_to_dict(photo)


@app.get("/thumb/{size}/{path:path}")
def get_photo_thumbnail(size: int, path: str):
    """
    Отдает маленькое WebP-превью фотографии.
    """
    if size not in config.THUMB_SIZES:
        raise HTTPException(status_code=404, detail="Неизвестный размер превью")

    try:
        thumbnail = get_thumbnail(path, size)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    except ThumbnailError:
        raise HTTPException(status_code=415, detail="Не удалось создать превью")

    return FileResponse(
        thumbnail,
        media_type="image/webp",
        headers={
            "Cache-Control": f"public, max-age={config.THUMB_MAX_AGE}",
        },
    )


@app.get("/api/stats")
def get_stats():
    """Статистика по БД."""
    return db.get_stats()


@app.post("/api/scan")
def trigger_scan(payload: ScanRequest | None = None):
    """
    Запуск сканирования директории с фото.
    - При изменении пути на новый создается новая БД, старая не удаляется.
    - При изменении пути на такой, для которого уже была создана база,
      старая база сливается с новой (приоритет отдается старым записям).
    """
    if payload and payload.photos_dir:
        raw_path = payload.photos_dir.strip()
        if raw_path:
            p = Path(raw_path).resolve()
            if not p.exists() or not p.is_dir():
                raise HTTPException(
                    status_code=400,
                    detail=f"Указанный путь не существует или не является папкой: {raw_path}",
                )
            if p != config.PHOTOS_DIR:
                config.set_photos_dir(p)

    target_db_path = config.get_db_path(config.PHOTOS_DIR)
    db_already_existed = target_db_path.exists() and target_db_path.stat().st_size > 0

    try:
        scanned_photos = scan_photos(str(config.PHOTOS_DIR))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not db_already_existed:
        # Создается новая БД для нового пути, старая не удаляется
        config.DB_PATH = target_db_path
        db.switch_db(str(target_db_path))
        added = db.add_photos(scanned_photos)
        merged = False
    else:
        # База для этого пути уже существовала.
        # Старая база сливается с новой (приоритет отдается старым записям).
        config.DB_PATH = target_db_path
        db.switch_db(str(target_db_path))

        fd, temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            temp_db = Database(temp_db_path)
            temp_db.add_photos(scanned_photos)

            # Сливаем: старая база дополняется новыми фото, старые записи имеют приоритет
            added = db.merge_from(temp_db_path)
            merged = True
        finally:
            if os.path.exists(temp_db_path):
                try:
                    os.unlink(temp_db_path)
                except OSError:
                    pass

    stats = db.get_stats()
    return {
        "added": added,
        "stats": stats,
        "photos_dir": str(config.PHOTOS_DIR),
        "db_path": str(config.DB_PATH),
        "merged": merged,
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Сервер запускается по адресу http://localhost:{config.PORT}")
    print(f"Корневая папка с фото: {config.PHOTOS_DIR}")
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True)
