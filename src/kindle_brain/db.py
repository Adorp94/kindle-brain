"""Database connection factory for Kindle Brain."""

import sqlite3
from pathlib import Path

from kindle_brain.paths import db_path, memory_db_path


def get_connection(row_factory: bool = False) -> sqlite3.Connection:
    """Get a connection to the main kindle.db database."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.Connection(path)
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def get_memory_connection() -> sqlite3.Connection:
    """Get a connection to the memory.db database."""
    path = memory_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
