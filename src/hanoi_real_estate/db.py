import sqlite3
from pathlib import Path

from .config import DB_PATH, SQL_DIR


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(schema_path: Path | None = None) -> None:
    schema_file = schema_path or (SQL_DIR / "schema.sql")
    with get_connection() as conn:
        conn.executescript(schema_file.read_text(encoding="utf-8"))

