"""Parse Kindle clippings from My Clippings.txt into SQLite database.

Handles incremental updates by tracking byte offset.
Supports both Spanish and English Kindle locale formats.
"""

import os
import re
import sqlite3
from datetime import datetime

from kindle_brain.db import get_connection
from kindle_brain.paths import db_path, find_kindle_mount, find_clippings_file

# Spanish month mapping
SPANISH_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

# English month mapping
ENGLISH_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}

# Spanish day of week (just for parsing, not used in datetime)
SPANISH_DAYS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def init_db(conn: sqlite3.Connection):
    """Create database schema if not exists."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            kindle_filename TEXT,
            kindle_path TEXT,
            text_extracted INTEGER DEFAULT 0,
            summary TEXT,
            has_chapters INTEGER DEFAULT 0,
            UNIQUE(title, author)
        );

        CREATE TABLE IF NOT EXISTS clippings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            type TEXT NOT NULL,  -- highlight, note, bookmark
            page INTEGER,
            position_start INTEGER,
            position_end INTEGER,
            date TEXT,
            text TEXT,
            note_text TEXT,  -- paired note for highlights
            surrounding_context TEXT,
            chapter_id INTEGER,
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id),
            UNIQUE(book_id, type, position_start, position_end, text)
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            chapter_number INTEGER,
            title TEXT,
            summary TEXT,
            start_position INTEGER,
            FOREIGN KEY (book_id) REFERENCES books(id)
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_byte_offset INTEGER DEFAULT 0,
            last_sync_date TEXT
        );

        INSERT OR IGNORE INTO sync_state (id, last_byte_offset) VALUES (1, 0);

        CREATE INDEX IF NOT EXISTS idx_clippings_book ON clippings(book_id);
        CREATE INDEX IF NOT EXISTS idx_clippings_type ON clippings(type);
        CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
    """)

    # Migration: add rich_context columns if missing
    cursor = conn.cursor()
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(clippings)")}
    migrations = {
        'rich_context': 'TEXT',
        'rich_context_start': 'INTEGER',
        'rich_context_end': 'INTEGER',
        'matched_char_start': 'INTEGER',
        'matched_char_end': 'INTEGER',
    }
    for col, typ in migrations.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE clippings ADD COLUMN {col} {typ}")

    conn.commit()


def parse_spanish_date(date_str: str) -> str | None:
    """Parse Spanish date format to ISO format."""
    # Example: "jueves, 4 de enero de 2018 18:38:48"
    pattern = r'(\w+),\s*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})'
    match = re.search(pattern, date_str.lower())
    if not match:
        return None

    _, day, month_name, year, hour, minute, second = match.groups()
    month = SPANISH_MONTHS.get(month_name)
    if not month:
        return None

    try:
        dt = datetime(int(year), month, int(day), int(hour), int(minute), int(second))
        return dt.isoformat()
    except ValueError:
        return None


def parse_english_date(date_str: str) -> str | None:
    """Parse English date format to ISO format."""
    # Example: "Thursday, January 4, 2018 6:38:48 PM"
    pattern = r'(\w+),\s+(\w+)\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?'
    match = re.search(pattern, date_str, re.IGNORECASE)
    if not match:
        return None

    _, month_name, day, year, hour, minute, second, ampm = match.groups()
    month = ENGLISH_MONTHS.get(month_name.lower())
    if not month:
        return None

    hour_int = int(hour)
    if ampm:
        if ampm.upper() == 'PM' and hour_int != 12:
            hour_int += 12
        elif ampm.upper() == 'AM' and hour_int == 12:
            hour_int = 0

    try:
        dt = datetime(int(year), month, int(day), hour_int, int(minute), int(second))
        return dt.isoformat()
    except ValueError:
        return None


def detect_locale(content: str) -> str:
    """Detect clippings file locale by inspecting the first few entries.

    Returns "es" for Spanish or "en" for English.
    """
    # Check the first ~2000 characters for locale-specific keywords
    sample = content[:2000].lower()

    spanish_markers = ['subrayado', 'nota', 'marcador', 'página', 'posición', 'añadido el']
    english_markers = ['highlight', 'note', 'bookmark', 'page', 'location', 'added on']

    es_count = sum(1 for m in spanish_markers if m in sample)
    en_count = sum(1 for m in english_markers if m in sample)

    return "es" if es_count >= en_count else "en"


def parse_clipping_entry(entry: str) -> dict | None:
    """Parse a single clipping entry. Auto-detects Spanish or English locale."""
    lines = entry.strip().split('\n')
    if len(lines) < 3:
        return None

    # First line: Book Title (Author) or just Book Title
    title_line = lines[0].strip()
    author_match = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', title_line)
    if author_match:
        title = author_match.group(1).strip()
        author = author_match.group(2).strip()
    else:
        title = title_line
        author = None

    # Second line: metadata
    meta_line = lines[1].strip()
    meta_lower = meta_line.lower()

    # Detect locale from metadata line
    is_english = ('highlight' in meta_lower or 'note' in meta_lower
                  or 'bookmark' in meta_lower or 'added on' in meta_lower
                  or 'location' in meta_lower)

    # Determine type
    if is_english:
        if 'highlight' in meta_lower:
            clip_type = 'highlight'
        elif 'note' in meta_lower:
            clip_type = 'note'
        elif 'bookmark' in meta_lower:
            clip_type = 'bookmark'
        else:
            clip_type = 'unknown'
    else:
        if 'subrayado' in meta_lower:
            clip_type = 'highlight'
        elif 'nota' in meta_lower:
            clip_type = 'note'
        elif 'marcador' in meta_lower:
            clip_type = 'bookmark'
        else:
            clip_type = 'unknown'

    # Parse page (Spanish: "página", English: "page")
    page_match = re.search(r'(?:página|page)\s+(\d+)', meta_line, re.IGNORECASE)
    page = int(page_match.group(1)) if page_match else None

    # Parse position (Spanish: "posición", English: "location")
    pos_match = re.search(r'(?:posición|location)\s+(\d+)(?:-(\d+))?', meta_line, re.IGNORECASE)
    if pos_match:
        position_start = int(pos_match.group(1))
        position_end = int(pos_match.group(2)) if pos_match.group(2) else position_start
    else:
        position_start = position_end = None

    # Parse date (Spanish: "Añadido el", English: "Added on")
    date = None
    date_match_es = re.search(r'Añadido el\s+(.+)$', meta_line, re.IGNORECASE)
    date_match_en = re.search(r'Added on\s+(.+)$', meta_line, re.IGNORECASE)
    if date_match_es:
        date = parse_spanish_date(date_match_es.group(1))
    elif date_match_en:
        date = parse_english_date(date_match_en.group(1))

    # Text content (lines after metadata, before next separator)
    text = '\n'.join(lines[2:]).strip() if len(lines) > 2 else None

    return {
        'title': title,
        'author': author,
        'type': clip_type,
        'page': page,
        'position_start': position_start,
        'position_end': position_end,
        'date': date,
        'text': text
    }


def get_or_create_book(conn: sqlite3.Connection, title: str, author: str | None) -> int:
    """Get existing book ID or create new book entry."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM books WHERE title = ? AND (author = ? OR (author IS NULL AND ? IS NULL))",
        (title, author, author)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        "INSERT INTO books (title, author) VALUES (?, ?)",
        (title, author)
    )
    conn.commit()
    return cursor.lastrowid


def insert_clipping(conn: sqlite3.Connection, book_id: int, clipping: dict) -> int | None:
    """Insert clipping, return ID or None if duplicate."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO clippings (book_id, type, page, position_start, position_end, date, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            book_id,
            clipping['type'],
            clipping['page'],
            clipping['position_start'],
            clipping['position_end'],
            clipping['date'],
            clipping['text']
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Duplicate entry
        return None


def pair_notes_with_highlights(conn: sqlite3.Connection):
    """Match notes with their associated highlights based on position."""
    cursor = conn.cursor()

    # Find notes that haven't been paired yet
    cursor.execute("""
        SELECT c.id, c.book_id, c.position_start, c.position_end, c.text
        FROM clippings c
        WHERE c.type = 'note' AND c.text IS NOT NULL
    """)
    notes = cursor.fetchall()

    for note_id, book_id, pos_start, pos_end, note_text in notes:
        # Find a highlight at the same or nearby position
        cursor.execute("""
            SELECT id FROM clippings
            WHERE book_id = ?
            AND type = 'highlight'
            AND note_text IS NULL
            AND (
                (position_start <= ? AND position_end >= ?)
                OR (position_start = ? OR position_end = ?)
                OR (ABS(position_start - ?) <= 5)
            )
            LIMIT 1
        """, (book_id, pos_start, pos_start, pos_start, pos_end, pos_start))

        highlight = cursor.fetchone()
        if highlight:
            cursor.execute(
                "UPDATE clippings SET note_text = ? WHERE id = ?",
                (note_text, highlight[0])
            )

    conn.commit()


def scan_kindle_books(conn: sqlite3.Connection):
    """Scan Kindle for book files and register them."""
    kindle_mount = find_kindle_mount()
    if not kindle_mount:
        return 0

    kindle_docs = os.path.join(kindle_mount, "documents")
    if not os.path.exists(kindle_docs):
        return 0

    cursor = conn.cursor()
    new_books = 0

    # Find all ebook files
    for root, _, files in os.walk(kindle_docs):
        for filename in files:
            if filename.endswith(('.azw3', '.azw', '.mobi', '.kfx')):
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, kindle_docs)

                # Check if already registered
                cursor.execute(
                    "SELECT id FROM books WHERE kindle_filename = ?",
                    (filename,)
                )
                if cursor.fetchone():
                    continue

                # Try to match with existing book by title similarity
                # First find a matching book
                cursor.execute("""
                    SELECT id FROM books
                    WHERE kindle_filename IS NULL
                    AND title LIKE ?
                    LIMIT 1
                """, (f"%{filename.rsplit('.', 1)[0][:20]}%",))
                match = cursor.fetchone()
                if match:
                    cursor.execute("""
                        UPDATE books
                        SET kindle_filename = ?, kindle_path = ?
                        WHERE id = ?
                    """, (filename, rel_path, match[0]))
                    new_books += 1

    conn.commit()
    return new_books


def sync_clippings(clippings_file: str = None) -> dict:
    """Main sync function. Returns stats.

    Args:
        clippings_file: Optional path to a clippings file. If None,
                        auto-detects from connected Kindle.
    """
    if clippings_file is None:
        clippings_file = find_clippings_file()
        if clippings_file is None:
            kindle_mount = find_kindle_mount()
            if kindle_mount is None:
                return {'error': 'Kindle not connected. Please connect your Kindle device.'}
            return {'error': f'Clippings file not found on Kindle at {kindle_mount}'}

    if not os.path.exists(clippings_file):
        return {'error': f'Clippings file not found at {clippings_file}'}

    conn = get_connection()
    init_db(conn)

    # Get last sync position
    cursor = conn.cursor()
    cursor.execute("SELECT last_byte_offset FROM sync_state WHERE id = 1")
    last_offset = cursor.fetchone()[0] or 0

    # Read clippings file
    with open(clippings_file, 'r', encoding='utf-8') as f:
        # Check if file has grown
        f.seek(0, 2)  # End of file
        file_size = f.tell()

        if file_size <= last_offset:
            # Check if file was reset (smaller than last offset)
            if file_size < last_offset:
                last_offset = 0
            else:
                return {
                    'new_clippings': 0,
                    'new_books': 0,
                    'message': 'No new clippings since last sync.'
                }

        # Read from last position (or beginning for full sync)
        f.seek(last_offset if last_offset > 0 else 0)
        content = f.read()
        new_offset = f.tell()

    # For first sync, read entire file
    if last_offset == 0:
        with open(clippings_file, 'r', encoding='utf-8') as f:
            content = f.read()
            new_offset = f.tell()

    # Parse entries (separated by ==========)
    entries = content.split('==========')

    stats = {
        'new_clippings': 0,
        'duplicates': 0,
        'new_books': 0,
        'books_updated': set()
    }

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        parsed = parse_clipping_entry(entry)
        if not parsed:
            continue

        # Get or create book
        book_id = get_or_create_book(conn, parsed['title'], parsed['author'])

        # Insert clipping
        clipping_id = insert_clipping(conn, book_id, parsed)
        if clipping_id:
            stats['new_clippings'] += 1
            stats['books_updated'].add(parsed['title'])
        else:
            stats['duplicates'] += 1

    # Pair notes with highlights
    pair_notes_with_highlights(conn)

    # Scan for book files
    stats['new_book_files'] = scan_kindle_books(conn)

    # Update sync state
    cursor.execute(
        "UPDATE sync_state SET last_byte_offset = ?, last_sync_date = ?",
        (new_offset, datetime.now().isoformat())
    )
    conn.commit()

    # Get totals
    cursor.execute("SELECT COUNT(*) FROM clippings")
    stats['total_clippings'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM books")
    stats['total_books'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'highlight'")
    stats['total_highlights'] = cursor.fetchone()[0]

    stats['new_books'] = len(stats['books_updated'])
    del stats['books_updated']

    conn.close()
    return stats


def reset_sync():
    """Reset sync state to re-import everything."""
    path = db_path()
    if not path.exists():
        print("Database doesn't exist yet.")
        return

    conn = get_connection()
    conn.execute("UPDATE sync_state SET last_byte_offset = 0")
    conn.commit()
    conn.close()
    print("Sync state reset. Next sync will re-import all clippings.")
