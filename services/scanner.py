from pathlib import Path
from typing import List, Dict

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def scan_photos(folder_path: str) -> List[Dict[str, str]]:
    """
    Рекурсивно сканирует папку и возвращает список словарей:
    [
        {"relative_path": "2024/05/img.jpg", "parent_dir": "2024/05"},
        {"relative_path": "root_img.jpg", "parent_dir": ""},
        ...
    ]
    """
    root = Path(folder_path).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Указанный путь не существует или не является папкой: {folder_path}")

    photos = []
    for file_path in root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            rel_path = file_path.relative_to(root)
            parent = rel_path.parent

            photos.append({
                "relative_path": rel_path.as_posix(),
                # Если файл лежит в самом корне альбома, parent_dir равен пустой строке ""
                "parent_dir": "" if parent == Path(".") else parent.as_posix()
            })

    return photos