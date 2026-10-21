import sys
from db.database import Database
from services.scanner import scan_photos


def main():
    print("=== Умный альбом: Тест иерархии и БД ===")

    photos_dir = input("Введите путь к папке с фотографиями: ").strip()
    db_file = input("Введите путь к файлу БД (например, album.db): ").strip()

    if not db_file:
        db_file = "album.db"

    try:
        # 1. Инициализация БД
        print(f"\n[1/3] Подключение к БД: {db_file}")
        db = Database(db_file)

        # 2. Сканирование
        print(f"[2/3] Сканирование: {photos_dir}")
        scanned_photos = scan_photos(photos_dir)
        print(f"Найдено изображений на диске: {len(scanned_photos)}")

        # 3. Синхронизация
        print("[3/3] Синхронизация...")
        added_count = db.add_photos(scanned_photos)
        print(f"Новых фото добавлено: {added_count}")

        # Статистика
        stats = db.get_stats()
        print("\n--- Статистика ---")
        print(f"Всего в БД: {stats['total']} | Обработано: {stats['processed']} | Ожидают: {stats['unprocessed']}")

        # Проверка иерархии в корневой папке
        print("\n--- Содержимое корня альбома ---")
        subfolders = db.get_subfolders(current_dir="")
        root_photos = db.get_photos_in_folder(parent_dir="")
        
        print(f"Папки в корне ({len(subfolders)}): {subfolders}")
        print(f"Фото прямо в корне ({len(root_photos)}): {[p['relative_path'] for p in root_photos]}")

    except Exception as e:
        print(f"\nОшибка: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()