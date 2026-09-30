"""Подключение к Postgres и применение схемы.

Запуск напрямую (`python db/connection.py`) применяет storage-parser/db/schema.sql
к базе, указанной в DATABASE_URL.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def get_connection():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан (см. .env.example)")
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(commit=True):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def apply_schema():
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_cursor() as cur:
        cur.execute(sql)
    print(f"Схема применена ({SCHEMA_PATH.name}) к базе из DATABASE_URL")


if __name__ == "__main__":
    apply_schema()
