import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Optional, Set

# Список распространенных стоп-слов, чтобы короткие предлоги/союзы не вызывали ложных совпадений
STOPWORDS = {
    'и', 'в', 'во', 'не', 'на', 'с', 'со', 'к', 'у', 'за', 'по', 'о', 'об', 'обо',
    'из', 'до', 'от', 'под', 'над', 'при', 'про', 'для', 'без', 'через', 'а', 'но',
    'да', 'или', 'то', 'как', 'так', 'же', 'ли', 'бы', 'что', 'это', 'тот',
    'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'and', 'or', 'is'
}


class Database:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def switch_db(self, new_db_path: str):
        """Переключает активное соединение на другой файл базы данных."""
        self.db_path = str(new_db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

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
        if not photos_data:
            return 0
        query = """
        INSERT OR IGNORE INTO photos (relative_path, parent_dir)
        VALUES (:relative_path, :parent_dir);
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, photos_data)
            conn.commit()
            return cursor.rowcount

    def merge_from(self, source_db_path: str) -> int:
        """
        Сливает записи из source_db (новой базы со свежим сканированием) в текущую базу (старую базу).
        Приоритет отдается текущим (старым) записям:
        - Все поля существующих записей в старой базе сохраняются без изменений
          (все ручные и автоматические описания, эмбеддинги и флаги обработки не перезаписываются).
        - Новые записи из source_db, которых еще нет в старой базе, добавляются.
        Возвращает количество добавленных новых записей.
        """
        source_path = str(Path(source_db_path).resolve())
        with self._get_connection() as conn:
            conn.execute("ATTACH DATABASE ? AS source_db", (source_path,))
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO photos (
                        relative_path, parent_dir, is_processed, auto_caption, manual_caption, embedding
                    )
                    SELECT relative_path, parent_dir, is_processed, auto_caption, manual_caption, embedding
                    FROM source_db.photos;
                """)
                added_count = cursor.rowcount
                conn.commit()
                return added_count
            finally:
                conn.execute("DETACH DATABASE source_db")

    def search_photos(self, query: str) -> List[sqlite3.Row]:
        """
        Ищет фото по описанию (manual_caption и auto_caption),
        возвращая подходящие результаты, отсортированные по релевантности совпадения.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        tokens = [t.lower() for t in re.findall(r'[\w]+', clean_query)]
        if not tokens:
            return []

        query_lower = clean_query.lower()
        sig_tokens = [t for t in tokens if t not in STOPWORDS] or tokens

        sql = """
        SELECT id, relative_path, parent_dir, is_processed, auto_caption, manual_caption
        FROM photos
        WHERE (manual_caption IS NOT NULL AND manual_caption != '')
           OR (auto_caption IS NOT NULL AND auto_caption != '')
        """
        with self._get_connection() as conn:
            rows = conn.execute(sql).fetchall()

        scored = []
        for row in rows:
            manual = (row["manual_caption"] or "").lower()
            auto = (row["auto_caption"] or "").lower()
            combined = f"{manual} {auto}".strip()
            if not combined:
                continue

            # Проверяем, есть ли хотя бы одно совпадение значимого слова или фразы целиком
            has_match = (query_lower in combined) or any(t in combined for t in sig_tokens)
            if not has_match:
                continue

            score = 0.0

            # 1. Точное совпадение всей поисковой фразы (в ручном описании ценится выше)
            if query_lower in manual:
                score += 150.0
            elif query_lower in auto:
                score += 100.0

            # 2. Совпадение отдельных слов
            for token in tokens:
                is_stop = token in STOPWORDS
                base_weight = 6.0 if is_stop else 28.0

                pattern = r'(?<!\w)' + re.escape(token) + r'(?!\w)'

                # Ручное описание
                m_exact_manual = len(re.findall(pattern, manual, re.IGNORECASE))
                if m_exact_manual > 0:
                    score += base_weight + 12.0 + (m_exact_manual - 1) * 4.0
                elif token in manual:
                    score += base_weight

                # Автоматическое описание
                m_exact_auto = len(re.findall(pattern, auto, re.IGNORECASE))
                if m_exact_auto > 0:
                    score += base_weight + 6.0 + (m_exact_auto - 1) * 2.0
                elif token in auto:
                    score += base_weight * 0.8

            # Доля совпавших уникальных токенов запроса
            matched_unique = len({t for t in tokens if t in combined})
            fraction = matched_unique / len(tokens)
            score += fraction * 40.0
            if matched_unique == len(tokens):
                score += 30.0  # Бонус за присутствие всех слов запроса

            # Нормализация по длине текста (компактные и точные описания ранжируются выше)
            length_norm = 1.0 / (1.0 + 0.002 * len(combined))
            final_score = score * length_norm

            scored.append((final_score, row))

        # Сортировка по убыванию релевантности совпадения
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored]

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
        query = """
        SELECT id, relative_path, parent_dir, is_processed,
               auto_caption, manual_caption
        FROM photos
        WHERE parent_dir = ?
        ORDER BY relative_path
        """
        with self._get_connection() as conn:
            return conn.execute(query, (parent_dir,)).fetchall()

    def get_photo(self, photo_id: int) -> Optional[sqlite3.Row]:
        """Возвращает одно фото по id вместе с описаниями."""
        query = """
        SELECT id, relative_path, parent_dir, is_processed,
               auto_caption, manual_caption
        FROM photos
        WHERE id = ?
        """
        with self._get_connection() as conn:
            return conn.execute(query, (photo_id,)).fetchone()

    def update_manual_caption(
        self, photo_id: int, caption: Optional[str]
    ) -> Optional[sqlite3.Row]:
        """
        Обновляет ручное описание и возвращает обновленную запись.
        None означает, что описание нужно очистить.
        """
        query = "UPDATE photos SET manual_caption = ? WHERE id = ?"
        select_query = """
        SELECT id, relative_path, parent_dir, is_processed,
               auto_caption, manual_caption
        FROM photos
        WHERE id = ?
        """
        with self._get_connection() as conn:
            conn.execute(query, (caption, photo_id))
            row = conn.execute(select_query, (photo_id,)).fetchone()
            conn.commit()
            return row

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
