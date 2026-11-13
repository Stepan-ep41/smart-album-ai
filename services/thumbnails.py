"""Генерация и кэширование превью фотографий.

Превью создаются лениво (при первом запросе) и складываются на диск,
поэтому повторные открытия папки отдают уже готовые маленькие WebP-файлы.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps

import config


class ThumbnailError(Exception):
    """Не удалось построить превью для файла."""


# Набор блокировок по числу бакетов: не даем двум запросам одновременно
# собирать одно и то же превью. 64 замков достаточно и не растут с библиотекой.
_GENERATION_LOCKS = tuple(threading.Lock() for _ in range(64))


def _lock_for(destination: Path) -> threading.Lock:
    return _GENERATION_LOCKS[hash(str(destination)) % len(_GENERATION_LOCKS)]


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_photo(relative_path: str) -> Path:
    """Безопасно превращает относительный путь из БД в путь на диске."""
    root = config.PHOTOS_DIR
    source = (root / relative_path).resolve()

    if not _is_inside(source, root):
        raise FileNotFoundError(relative_path)
    if not source.is_file():
        raise FileNotFoundError(relative_path)

    return source


def thumbnail_path(relative_path: str, size: int) -> Path:
    """Путь в кэше для превью заданного размера.

    Полное имя файла сохраняется (foo.jpg -> foo.jpg.webp), чтобы фото
    с одинаковым именем, но разным расширением, не перезаписывали друг друга.
    """
    relative = Path(relative_path)
    return (
        config.THUMBS_DIR
        / str(size)
        / relative.parent
        / f"{relative.name}.webp"
    )


def _build_thumbnail(source: Path, destination: Path, size: int) -> None:
    try:
        with Image.open(source) as image:
            # JPEG-декодер умеет сразу отдавать уменьшенную копию.
            # На снимках 20+ Мп это экономит и память, и время.
            if image.format == "JPEG":
                image.draft("RGB", (size * 2, size * 2))

            image = ImageOps.exif_transpose(image)

            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            image.thumbnail((size, size), Image.Resampling.LANCZOS)

            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=destination.parent, suffix=".tmp"
            )
            os.close(fd)
            try:
                image.save(
                    temp_name,
                    format="WEBP",
                    quality=config.THUMB_QUALITY,
                    method=4,
                )
                # Атомарно подменяем файл: параллельные запросы не увидят
                # недописанное превью.
                os.replace(temp_name, destination)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ThumbnailError(str(exc)) from exc


def _is_fresh(destination: Path, source: Path) -> bool:
    try:
        return (
            destination.is_file()
            and destination.stat().st_mtime >= source.stat().st_mtime
        )
    except OSError:
        # Не смогли прочитать кэш — просто пересоберем превью.
        return False


def get_thumbnail(relative_path: str, size: int) -> Path:
    """Возвращает путь к готовому превью, создавая его при необходимости."""
    if size not in config.THUMB_SIZES:
        raise ValueError(f"Неподдерживаемый размер превью: {size}")

    source = resolve_photo(relative_path)
    destination = thumbnail_path(relative_path, size)

    if _is_fresh(destination, source):
        return destination

    # Пока один поток строит превью, остальные ждут и затем берут готовый файл.
    with _lock_for(destination):
        if not _is_fresh(destination, source):
            _build_thumbnail(source, destination, size)

    return destination
