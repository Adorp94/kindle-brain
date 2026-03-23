#!/usr/bin/env python3
"""
Enrich clippings with rich context ("golden nuggets") from book text.
Extracts ~3,000-5,000 word blocks centered on each highlight,
snapped to paragraph boundaries. Generates summaries via LLM.
"""

import argparse
import os
import re
import sqlite3
from pathlib import Path

import sys

from dotenv import load_dotenv
from rapidfuzz import fuzz

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "kindle.db"
BOOK_TEXTS_DIR = PROJECT_DIR / "data" / "book_texts"

# Rich context window: ~20,000 characters ≈ 4,000-5,000 words
RICH_CONTEXT_CHARS = 20000
# Minimum overlap ratio to merge two nearby blocks
MERGE_OVERLAP_RATIO = 0.5


def load_book_text(book_id: int) -> str | None:
    """Load extracted book text."""
    text_file = BOOK_TEXTS_DIR / f"{book_id}.txt"
    if not text_file.exists():
        return None
    with open(text_file, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def find_text_in_book(highlight: str, book_text: str, threshold: int = 70) -> tuple[int, int] | None:
    """Find the highlight text within the book using fuzzy matching."""
    if not highlight or not book_text:
        return None

    highlight = highlight.strip()
    if len(highlight) < 10:
        idx = book_text.find(highlight)
        if idx >= 0:
            return (idx, idx + len(highlight))

    # Split book into overlapping chunks for fuzzy matching
    chunk_size = len(highlight) + 50
    step = max(10, len(highlight) // 2)

    best_score = 0
    best_pos = None

    for i in range(0, len(book_text) - chunk_size + 1, step):
        chunk = book_text[i:i + chunk_size]
        score = fuzz.partial_ratio(highlight, chunk)
        if score > best_score and score >= threshold:
            best_score = score
            best_pos = i

    if best_pos is not None:
        search_start = max(0, best_pos - 20)
        search_end = min(len(book_text), best_pos + chunk_size + 20)
        search_region = book_text[search_start:search_end]

        best_local_score = 0
        best_local_pos = 0
        for j in range(len(search_region) - len(highlight) + 1):
            candidate = search_region[j:j + len(highlight)]
            score = fuzz.ratio(highlight, candidate)
            if score > best_local_score:
                best_local_score = score
                best_local_pos = j

        start = search_start + best_local_pos
        end = start + len(highlight)
        return (start, end)

    return None


def snap_to_paragraph(book_text: str, pos: int, direction: str) -> int:
    """Snap a position to the nearest paragraph boundary (\\n\\n).

    direction: 'before' snaps backward, 'after' snaps forward.
    """
    if direction == 'before':
        # Find the last \n\n before pos
        idx = book_text.rfind('\n\n', 0, pos)
        return idx + 2 if idx >= 0 else 0
    else:
        # Find the first \n\n after pos
        idx = book_text.find('\n\n', pos)
        return idx if idx >= 0 else len(book_text)


def extract_rich_context(book_text: str, match_start: int, match_end: int,
                         window_chars: int = RICH_CONTEXT_CHARS) -> tuple[str, int, int]:
    """Extract a massive context block centered on the highlight.

    Returns (rich_context_text, context_start, context_end).
    The highlight is marked with ««« »»» delimiters within the block.
    """
    half_window = window_chars // 2
    highlight_center = (match_start + match_end) // 2

    # Raw window centered on highlight
    raw_start = max(0, highlight_center - half_window)
    raw_end = min(len(book_text), highlight_center + half_window)

    # Snap to paragraph boundaries
    context_start = snap_to_paragraph(book_text, raw_start, 'before')
    context_end = snap_to_paragraph(book_text, raw_end, 'after')

    # Build the block with highlight markers
    before = book_text[context_start:match_start]
    highlight = book_text[match_start:match_end]
    after = book_text[match_end:context_end]

    rich_context = f"{before}«««{highlight}»»»{after}"

    return rich_context, context_start, context_end


def extract_surrounding_context(book_text: str, start: int, end: int,
                                sentences_before: int = 3, sentences_after: int = 3) -> str:
    """Extract sentences before and after the highlight (legacy small context)."""
    before_text = book_text[max(0, start - 1000):start]
    sentence_pattern = r'(?<=[.!?])\s+'
    before_sentences = re.split(sentence_pattern, before_text)
    before_context = ' '.join(before_sentences[-sentences_before:]) if before_sentences else ''

    after_text = book_text[end:min(len(book_text), end + 1000)]
    after_sentences = re.split(sentence_pattern, after_text)
    after_context = ' '.join(after_sentences[:sentences_after]) if after_sentences else ''

    highlight_text = book_text[start:end]
    return f"{before_context.strip()} **»** {highlight_text} **«** {after_context.strip()}"


def get_chapter_for_position(conn: sqlite3.Connection, book_id: int, position: int) -> int | None:
    """Find which chapter contains this position."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM chapters
        WHERE book_id = ? AND start_position <= ?
        ORDER BY start_position DESC LIMIT 1
    """, (book_id, position))
    row = cursor.fetchone()
    return row[0] if row else None


def enrich_clippings(book_id: int | None = None, rich_context: bool = False,
                     force: bool = False) -> dict:
    """Add surrounding context (and optionally rich context) to clippings."""
    if not DB_PATH.exists():
        return {'error': 'Database not found. Run sync.py first.'}

    conn = sqlite3.Connection(DB_PATH)
    cursor = conn.cursor()

    # Build query based on options
    where_clauses = [
        "c.type = 'highlight'",
        "c.text IS NOT NULL",
        "b.text_extracted = 1",
    ]
    params = []

    if book_id:
        where_clauses.append("c.book_id = ?")
        params.append(book_id)

    if rich_context and not force:
        where_clauses.append("c.rich_context IS NULL")
    elif not force:
        where_clauses.append("c.surrounding_context IS NULL")

    query = f"""
        SELECT c.id, c.book_id, c.text, c.position_start
        FROM clippings c
        JOIN books b ON c.book_id = b.id
        WHERE {' AND '.join(where_clauses)}
    """
    cursor.execute(query, params)
    clippings = cursor.fetchall()

    stats = {'enriched': 0, 'rich_context': 0, 'not_found': 0, 'total_clippings': len(clippings)}
    book_cache = {}

    for clip_id, clip_book_id, text, position_start in clippings:
        if clip_book_id not in book_cache:
            book_cache[clip_book_id] = load_book_text(clip_book_id)

        book_text = book_cache[clip_book_id]
        if not book_text:
            stats['not_found'] += 1
            continue

        match = find_text_in_book(text, book_text)
        if not match:
            stats['not_found'] += 1
            continue

        start, end = match
        context = extract_surrounding_context(book_text, start, end)
        chapter_id = get_chapter_for_position(conn, clip_book_id, start)

        if rich_context:
            rc_text, rc_start, rc_end = extract_rich_context(book_text, start, end)
            cursor.execute("""
                UPDATE clippings
                SET surrounding_context = ?, chapter_id = ?,
                    rich_context = ?, rich_context_start = ?, rich_context_end = ?,
                    matched_char_start = ?, matched_char_end = ?
                WHERE id = ?
            """, (context, chapter_id, rc_text, rc_start, rc_end, start, end, clip_id))
            stats['rich_context'] += 1
        else:
            cursor.execute("""
                UPDATE clippings
                SET surrounding_context = ?, chapter_id = ?
                WHERE id = ?
            """, (context, chapter_id, clip_id))

        stats['enriched'] += 1

        if stats['enriched'] % 50 == 0:
            conn.commit()
            print(f"  Enriched {stats['enriched']}/{stats['total_clippings']} clippings...")

    conn.commit()
    conn.close()
    return stats


def get_gemini_client():
    """Get Google GenAI client if available."""
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except ImportError:
        print("Warning: google-genai package not installed")
        return None


def generate_book_summary(client, book_text: str, title: str) -> str | None:
    """Generate a summary for the book using Gemini."""
    if not client or not book_text:
        return None
    max_chars = 200000
    if len(book_text) > max_chars:
        portion = max_chars // 2
        book_text = book_text[:portion] + "\n\n[...middle content omitted...]\n\n" + book_text[-portion:]
    try:
        from scripts.config import SUMMARY_MODEL
        response = client.models.generate_content(
            model=SUMMARY_MODEL,
            contents=f"You are a helpful assistant that creates concise book summaries. "
                     f"Focus on the main themes, arguments, and key takeaways. "
                     f"Keep the summary to about 200 words.\n\n"
                     f"Please summarize this book titled '{title}':\n\n{book_text}",
        )
        return response.text.strip()
    except Exception as e:
        print(f"  Error generating summary: {e}")
        return None


def generate_chapter_summary(client, chapter_text: str, chapter_title: str, book_title: str) -> str | None:
    """Generate a summary for a chapter using Gemini."""
    if not client or not chapter_text:
        return None
    max_chars = 50000
    if len(chapter_text) > max_chars:
        chapter_text = chapter_text[:max_chars] + "\n\n[...truncated...]"
    try:
        from scripts.config import SUMMARY_MODEL
        response = client.models.generate_content(
            model=SUMMARY_MODEL,
            contents=f"You are a helpful assistant that creates concise chapter summaries. "
                     f"Focus on the main points and key ideas. Keep the summary to about 100 words.\n\n"
                     f"Please summarize this chapter '{chapter_title}' from the book '{book_title}':\n\n{chapter_text}",
        )
        return response.text.strip()
    except Exception as e:
        print(f"  Error generating chapter summary: {e}")
        return None


def generate_summaries(book_id: int | None = None) -> dict:
    """Generate book and chapter summaries using Gemini."""
    client = get_gemini_client()
    if not client:
        return {'error': 'GOOGLE_API_KEY not configured. Set it in .env file.'}

    conn = sqlite3.Connection(DB_PATH)
    cursor = conn.cursor()
    stats = {'book_summaries': 0, 'chapter_summaries': 0, 'failed': 0}

    book_filter = "AND id = ?" if book_id else ""
    book_params = (book_id,) if book_id else ()

    cursor.execute(f"""
        SELECT id, title, author FROM books
        WHERE summary IS NULL AND text_extracted = 1 {book_filter}
    """, book_params)
    books = cursor.fetchall()

    for bid, title, author in books:
        print(f"\nGenerating summary for: {title}")
        book_text = load_book_text(bid)
        if book_text:
            summary = generate_book_summary(client, book_text, title)
            if summary:
                cursor.execute("UPDATE books SET summary = ? WHERE id = ?", (summary, bid))
                conn.commit()
                stats['book_summaries'] += 1
                print(f"  Summary generated ({len(summary)} chars)")
            else:
                stats['failed'] += 1
        else:
            stats['failed'] += 1

    chapter_filter = "AND ch.book_id = ?" if book_id else ""
    chapter_params = (book_id,) if book_id else ()

    cursor.execute(f"""
        SELECT ch.id, ch.title, ch.start_position, ch.book_id, b.title as book_title
        FROM chapters ch
        JOIN books b ON ch.book_id = b.id
        WHERE ch.summary IS NULL AND b.text_extracted = 1 {chapter_filter}
        ORDER BY ch.book_id, ch.chapter_number
    """, chapter_params)
    chapters = cursor.fetchall()

    book_chapters = {}
    for ch_id, ch_title, start_pos, bid, book_title in chapters:
        if bid not in book_chapters:
            book_chapters[bid] = []
        book_chapters[bid].append((ch_id, ch_title, start_pos, book_title))

    for bid, chapter_list in book_chapters.items():
        book_text = load_book_text(bid)
        if not book_text:
            continue
        for i, (ch_id, ch_title, start_pos, book_title) in enumerate(chapter_list):
            end_pos = chapter_list[i + 1][2] if i + 1 < len(chapter_list) else len(book_text)
            chapter_text = book_text[start_pos:end_pos]
            print(f"  Generating summary for chapter: {ch_title}")
            summary = generate_chapter_summary(client, chapter_text, ch_title, book_title)
            if summary:
                cursor.execute("UPDATE chapters SET summary = ? WHERE id = ?", (summary, ch_id))
                conn.commit()
                stats['chapter_summaries'] += 1

    conn.close()
    return stats


def run_enrichment(book_id: int | None = None, rich_context: bool = False,
                   skip_summaries: bool = False, force: bool = False) -> dict:
    """Run full enrichment pipeline."""
    results = {}

    mode = "rich context (golden nuggets)" if rich_context else "surrounding context"
    scope = f"book_id={book_id}" if book_id else "all books"
    print(f"Enriching clippings with {mode} for {scope}...")

    results['context'] = enrich_clippings(book_id=book_id, rich_context=rich_context, force=force)

    if 'error' in results['context']:
        return results

    print(f"\nContext enrichment complete:")
    print(f"  Enriched: {results['context']['enriched']}")
    if rich_context:
        print(f"  Rich context blocks: {results['context']['rich_context']}")
    print(f"  Not found in text: {results['context']['not_found']}")

    if not skip_summaries:
        print("\nGenerating summaries...")
        results['summaries'] = generate_summaries(book_id=book_id)
        if 'error' not in results['summaries']:
            print(f"\nSummary generation complete:")
            print(f"  Book summaries: {results['summaries']['book_summaries']}")
            print(f"  Chapter summaries: {results['summaries']['chapter_summaries']}")
        else:
            print(f"Skipping summaries: {results['summaries']['error']}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Enrich Kindle clippings with context')
    parser.add_argument('--book', type=int, help='Process only this book_id')
    parser.add_argument('--rich-context', action='store_true', help='Extract rich context golden nuggets (~4K words)')
    parser.add_argument('--no-summaries', action='store_true', help='Skip summary generation')
    parser.add_argument('--force', action='store_true', help='Re-process even if already enriched')
    args = parser.parse_args()

    results = run_enrichment(
        book_id=args.book,
        rich_context=args.rich_context,
        skip_summaries=args.no_summaries,
        force=args.force,
    )

    if 'error' in results.get('context', {}):
        print(f"Error: {results['context']['error']}")
        exit(1)
