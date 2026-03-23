"""Extract plain text from Kindle ebook files using Calibre.

Also attempts chapter detection for structuring content.
"""

import os
import re
import shutil
import sqlite3
import subprocess

from kindle_brain.db import get_connection
from kindle_brain.paths import (
    book_files_dir,
    book_texts_dir,
    db_path,
    find_calibre,
    find_kindle_mount,
)


def find_book_file(title: str, author: str | None, kindle_path: str | None) -> str | None:
    """Find the ebook file on Kindle matching this book."""
    kindle_mount = find_kindle_mount()
    if not kindle_mount:
        return None

    kindle_docs = os.path.join(kindle_mount, "documents")
    if not os.path.exists(kindle_docs):
        return None

    # If we have a stored path, try that first
    if kindle_path:
        full_path = os.path.join(kindle_docs, kindle_path)
        if os.path.exists(full_path):
            return full_path

    # Search for matching file
    # Clean title for matching
    clean_title = re.sub(r'[^\w\s]', '', title.lower())
    title_words = set(clean_title.split())

    best_match = None
    best_score = 0

    for root, _, files in os.walk(kindle_docs):
        for filename in files:
            if not filename.endswith(('.azw3', '.azw', '.mobi', '.kfx')):
                continue

            # Score based on title word matches
            clean_filename = re.sub(r'[^\w\s]', '', filename.lower().rsplit('.', 1)[0])
            file_words = set(clean_filename.split())

            common_words = title_words & file_words
            if common_words:
                score = len(common_words) / max(len(title_words), len(file_words))
                if score > best_score:
                    best_score = score
                    best_match = os.path.join(root, filename)

    return best_match if best_score > 0.3 else None


def extract_text_with_calibre(input_path: str, output_path: str) -> bool:
    """Convert ebook to plain text using Calibre."""
    calibre_convert = find_calibre()
    if not calibre_convert:
        print("  Error: Calibre not found")
        return False

    try:
        result = subprocess.run(
            [calibre_convert, input_path, output_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.returncode == 0 and os.path.exists(output_path)
    except subprocess.TimeoutExpired:
        print(f"  Timeout extracting {input_path}")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def detect_chapters(text: str) -> list[dict]:
    """Detect chapter boundaries in extracted text."""
    chapters = []

    # Common chapter patterns
    patterns = [
        # "Chapter 1", "Chapter One", "CHAPTER 1"
        r'^(?:Chapter|CHAPTER|Capítulo|CAPÍTULO)\s+(\d+|[A-Za-z]+)(?:\s*[:\.\-—]\s*(.+))?$',
        # "1.", "I.", numbered chapters
        r'^(\d+|[IVXLC]+)\.\s+(.+)$',
        # All caps titles (potential chapters)
        r'^([A-Z][A-Z\s]{10,50})$',
        # "Part 1", "PART ONE"
        r'^(?:Part|PART|Parte|PARTE)\s+(\d+|[A-Za-z]+)(?:\s*[:\.\-—]\s*(.+))?$',
    ]

    lines = text.split('\n')
    current_pos = 0

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            current_pos += 1
            continue

        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                chapter_num = len(chapters) + 1
                title = match.group(2) if match.lastindex >= 2 and match.group(2) else match.group(1)

                chapters.append({
                    'chapter_number': chapter_num,
                    'title': title.strip() if title else f"Chapter {chapter_num}",
                    'start_position': current_pos,
                    'line_number': i
                })
                break

        current_pos += len(line) + 1

    return chapters


def save_chapters(conn: sqlite3.Connection, book_id: int, chapters: list[dict]):
    """Save detected chapters to database."""
    cursor = conn.cursor()

    # Clear existing chapters
    cursor.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))

    for chapter in chapters:
        cursor.execute("""
            INSERT INTO chapters (book_id, chapter_number, title, start_position)
            VALUES (?, ?, ?, ?)
        """, (
            book_id,
            chapter['chapter_number'],
            chapter['title'],
            chapter['start_position']
        ))

    conn.commit()


def extract_books() -> dict:
    """Extract text from all books not yet extracted."""
    path = db_path()
    if not path.exists():
        return {'error': 'Database not found. Run sync first.'}

    # Ensure directories exist
    texts_dir = book_texts_dir()
    files_dir = book_files_dir()
    texts_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    # Get books that need extraction
    cursor.execute("""
        SELECT id, title, author, kindle_filename, kindle_path
        FROM books
        WHERE text_extracted = 0
    """)
    books = cursor.fetchall()

    stats = {
        'extracted': 0,
        'failed': 0,
        'not_found': 0,
        'with_chapters': 0,
        'total_chapters': 0
    }

    kindle_mount = find_kindle_mount()
    kindle_connected = kindle_mount is not None
    kindle_docs = os.path.join(kindle_mount, "documents") if kindle_connected else None

    for book_id, title, author, kindle_filename, kindle_path in books:
        print(f"\nProcessing: {title}")

        # Find the book file
        book_file = None
        if kindle_connected:
            book_file = find_book_file(title, author, kindle_path)

        if not book_file:
            # Check if we have a local copy
            local_files = list(files_dir.glob(f"{book_id}.*"))
            if local_files:
                book_file = str(local_files[0])
            else:
                print(f"  Book file not found")
                stats['not_found'] += 1
                continue

        # Copy to local storage if from Kindle
        if kindle_mount and book_file.startswith(kindle_mount):
            ext = os.path.splitext(book_file)[1]
            local_copy = files_dir / f"{book_id}{ext}"
            if not local_copy.exists():
                print(f"  Copying to local storage...")
                shutil.copy2(book_file, local_copy)
            book_file = str(local_copy)

            # Update database with path info
            cursor.execute("""
                UPDATE books
                SET kindle_filename = ?, kindle_path = ?
                WHERE id = ?
            """, (
                os.path.basename(book_file),
                os.path.relpath(book_file, kindle_docs) if kindle_docs and book_file.startswith(kindle_docs) else None,
                book_id
            ))

        # Extract text
        output_path = texts_dir / f"{book_id}.txt"
        print(f"  Extracting text...")

        if extract_text_with_calibre(book_file, str(output_path)):
            # Read extracted text
            with open(output_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()

            # Detect chapters
            chapters = detect_chapters(text)
            if chapters:
                save_chapters(conn, book_id, chapters)
                print(f"  Found {len(chapters)} chapters")
                stats['with_chapters'] += 1
                stats['total_chapters'] += len(chapters)

            # Update book record
            cursor.execute("""
                UPDATE books
                SET text_extracted = 1, has_chapters = ?
                WHERE id = ?
            """, (1 if chapters else 0, book_id))
            conn.commit()

            stats['extracted'] += 1
            print(f"  Extracted successfully ({len(text):,} characters)")
        else:
            stats['failed'] += 1
            print(f"  Failed to extract (possibly DRM protected)")

    # Get totals
    cursor.execute("SELECT COUNT(*) FROM books WHERE text_extracted = 1")
    stats['total_extracted'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM books")
    stats['total_books'] = cursor.fetchone()[0]

    conn.close()
    return stats
