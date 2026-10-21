from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

import config
from db.database import Database
from services.scanner import scan_photos

app = FastAPI(title="Smart Album")

# Инициализация базы данных
db = Database(str(config.DB_PATH))

# Раздача фронтенд-статики (CSS, JS)
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

# Раздача медиа-файлов (фотографий) напрямую с диска
app.mount("/media", StaticFiles(directory=str(config.PHOTOS_DIR)), name="media")

# Шаблоны HTML
templates = Jinja2Templates(directory="ui/templates")


@app.get("/")
def read_root(request: Request):
    """Главная страница альбома."""
    return templates.TemplateResponse("index.html", {"request": request})


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