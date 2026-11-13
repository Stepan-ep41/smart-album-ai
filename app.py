from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse

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


# Раздача фронтенд-статики (CSS, JS). Небольшой max-age, чтобы правки
# в интерфейсе подхватывались без ручной очистки кэша браузера.
app.mount(
    "/static",
    CachedStaticFiles(directory="ui/static", cache_control="public, max-age=3600"),
    name="static",
)

# Раздача медиа-файлов (фотографий) напрямую с диска
app.mount(
    "/media",
    CachedStaticFiles(directory=str(config.PHOTOS_DIR)),
    name="media",
)

# Шаблоны HTML
templates = Jinja2Templates(directory="ui/templates")


@app.get("/")
def read_root(request: Request):
    """Главная страница альбома."""
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/api/browse")
def browse(path: str = ""):
    """
    Возвращает содержимое указанной папки:
    дочерние папки и список фотографий.
    """
    clean_path = path.strip("/")
    subfolders = db.get_subfolders(current_dir=clean_path)
    photos = db.get_photos_in_folder(parent_dir=clean_path)
    
    # Преобразуем Row-объекты sqlite3 в обычные dict
    photos_data = [
        {
            "id": p["id"],
            "relative_path": p["relative_path"],
            "is_processed": bool(p["is_processed"]),
            "auto_caption": p["auto_caption"],
            "manual_caption": p["manual_caption"],
        }
        for p in photos
    ]

    return {
        "current_path": clean_path,
        "subfolders": subfolders,
        "photos": photos_data,
    }


@app.get("/thumb/{size}/{path:path}")
def get_photo_thumbnail(size: int, path: str):
    """
    Отдает маленькое WebP-превью фотографии.

    Размер ограничен списком config.THUMB_SIZES, чтобы нельзя было
    запросить произвольную (и очень тяжелую) миниатюру.
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
def trigger_scan():
    """Запуск сканирования директории с фото и добавление новых в БД."""
    scanned_photos = scan_photos(str(config.PHOTOS_DIR))
    added = db.add_photos(scanned_photos)
    stats = db.get_stats()
    return {"added": added, "stats": stats}


if __name__ == "__main__":
    import uvicorn
    print(f"Сервер запускается по адресу http://localhost:{config.PORT}")
    print(f"Корневая папка с фото: {config.PHOTOS_DIR}")
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True)