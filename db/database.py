import sqlite3
from pathlib import Path
from typing import List, Dict, Set


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Создает таблицу photos и индекс для мгновенной выборки по папкам."""
        query = """
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT UNIQUE NOT NULL,
            parent_dir TEXT NOT NULL,
            is_processed INTEGER NOT NULL DEFAULT 0,
            auto_caption TEXT,
            manual_caption TEXT,
            embedding BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_parent_dir ON photos(parent_dir);
        """
        with self._get_connection() as conn:
            conn.executescript(query)
            conn.commit()

    def add_photos(self, photos_data: List[Dict[str, str]]) -> int:
        """
        Добавляет новые фото в базу.
        Каждый элемент photos_data — это dict с ключами 'relative_path' и 'parent_dir'.
        """
        query = """
        INSERT OR IGNORE INTO photos (relative_path, parent_dir)
        VALUES (:relative_path, :parent_dir);
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, photos_data)
            conn.commit()
            return cursor.rowcount

    def get_subfolders(self, current_dir: str = "") -> List[str]:
        """
        Возвращает только непосредственные дочерние папки для current_dir.
        Например, для корня ("") вернет ['2023', '2024'], а не всю глубину.
        """
        prefix = f"{current_dir}/" if current_dir else ""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT parent_dir FROM photos WHERE parent_dir != ''"
            )
            subfolders: Set[str] = set()
            for row in cursor.fetchall():
                p_dir = row["parent_dir"]
                if current_dir == "":
                    # В корне берем самый первый сегмент пути
                    subfolders.add(p_dir.split("/")[0])
                elif p_dir.startswith(prefix):
                    # Во вложенной папке берем следующий сегмент
                    remainder = p_dir[len(prefix):]
                    subfolders.add(remainder.split("/")[0])
            return sorted(list(subfolders))

    def get_photos_in_folder(self, parent_dir: str = "") -> List[sqlite3.Row]:
        """Мгновенно возвращает фото, лежащие непосредственно в указанной папке."""
        query = "SELECT * FROM photos WHERE parent_dir = ?"
        with self._get_connection() as conn:
            return conn.execute(query, (parent_dir,)).fetchall()

    def get_stats(self) -> dict:
        """Общая статистика альбома."""
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            processed = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE is_processed = 1"
            ).fetchone()[0]
        return {
            "total": total,
            "processed": processed,
            "unprocessed": total - processed,
        }