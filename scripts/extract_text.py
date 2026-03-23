#!/usr/bin/env python3
"""
Extract plain text from Kindle ebook files using Calibre.
Also attempts chapter detection for structuring content.
"""

import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

# Paths
KINDLE_MOUNT = "/Volumes/Kindle"
KINDLE_DOCS = f"{KINDLE_MOUNT}/documents"
CALIBRE_CONVERT = "/Applications/calibre.app/Contents/MacOS/ebook-convert"
PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "kindle.db"
BOOK_TEXTS_DIR = PROJECT_DIR / "data" / "book_texts"
BOOK_FILES_DIR = PROJECT_DIR / "data" / "book_files"


def find_book_file(title: str, author: str | None, kindle_path: str | None) -> str | None:
    """Find the ebook file on Kindle matching this book."""
    if not os.path.exists(KINDLE_DOCS):
        return None

    # If we have a stored path, try that first
    if kindle_path:
        full_path = os.path.join(KINDLE_DOCS, kindle_path)
        if os.path.exists(full_path):
            return full_path

    # Search for matching file
    # Clean title for matching
    clean_title = re.sub(r'[^\w\s]', '', title.lower())
    title_words = set(clean_title.split())

    best_match = None
    best_score = 0

    for root, _, files in os.walk(KINDLE_DOCS):
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
    if not os.path.exists(CALIBRE_CONVERT):
        print(f"  Error: Calibre not found at {CALIBRE_CONVERT}")
        return False

    try:
        result = subprocess.run(
            [CALIBRE_CONVERT, input_path, output_path],
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
    if not DB_PATH.exists():
        return {'error': 'Database not found. Run sync.py first.'}

    # Ensure directories exist
    BOOK_TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    BOOK_FILES_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.Connection(DB_PATH)
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

    kindle_connected = os.path.exists(KINDLE_MOUNT)

    for book_id, title, author, kindle_filename, kindle_path in books:
        print(f"\nProcessing: {title}")

        # Find the book file
        book_file = None
        if kindle_connected:
            book_file = find_book_file(title, author, kindle_path)

        if not book_file:
            # Check if we have a local copy
            local_files = list(BOOK_FILES_DIR.glob(f"{book_id}.*"))
            if local_files:
                book_file = str(local_files[0])
            else:
                print(f"  Book file not found")
                stats['not_found'] += 1
                continue

        # Copy to local storage if from Kindle
        if book_file.startswith(KINDLE_MOUNT):
            ext = os.path.splitext(book_file)[1]
            local_copy = BOOK_FILES_DIR / f"{book_id}{ext}"
            if not local_copy.exists():
                print(f"  Copying to local storage...")
                shutil.copy2(book_file, local_copy)
            book_file = str(local_copy)

            # Update database with path info
            cursor.execute("""
                UPDATE books
                SET kindle_filename = ?, kindle_path = ?
                WHERE id = ?
            """, (os.path.basename(book_file), os.path.relpath(book_file, KINDLE_DOCS) if book_file.startswith(KINDLE_DOCS) else None, book_id))

        # Extract text
        output_path = BOOK_TEXTS_DIR / f"{book_id}.txt"
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


if __name__ == '__main__':
    print("Extracting text from Kindle books...")

    if not os.path.exists(CALIBRE_CONVERT):
        print(f"Error: Calibre not found at {CALIBRE_CONVERT}")
        print("Please install Calibre from https://calibre-ebook.com/")
        exit(1)

    result = extract_books()

    if 'error' in result:
        print(f"Error: {result['error']}")
        exit(1)

    print(f"\nExtraction complete!")
    print(f"  Books extracted this run: {result['extracted']}")
    print(f"  Failed (DRM/other): {result['failed']}")
    print(f"  File not found: {result['not_found']}")
    print(f"  Books with chapters: {result['with_chapters']} ({result['total_chapters']} total chapters)")
    print(f"  Total books extracted: {result['total_extracted']}/{result['total_books']}")
