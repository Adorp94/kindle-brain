#!/usr/bin/env python3
"""
Build and update ChromaDB vector index using Gemini Embedding 2.
Embeds rich context golden nuggets (~4K words each) as single vectors.
Deduplicates overlapping blocks before indexing.
"""

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv
from google import genai

from scripts.config import EMBEDDING_MODEL, COLLECTION_NAME

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "kindle.db"
VECTORDB_DIR = PROJECT_DIR / "vectordb"

MERGE_OVERLAP_RATIO = 0.5


def get_gemini_client():
    return genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))


def get_chroma_client():
    """Get ChromaDB client with persistent storage."""
    VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(VECTORDB_DIR),
        settings=Settings(anonymized_telemetry=False)
    )


def get_embeddings(client, texts: list[str]) -> list[list[float]]:
    """Get embeddings from Gemini Embedding 2 API."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
    )
    return [e.values for e in response.embeddings]


def build_document(clipping: dict) -> str:
    """Build searchable document from clipping data.

    Prefers rich_context (golden nugget) over small surrounding_context.
    """
    parts = []

    # Use rich context if available, else fall back to highlight + surrounding
    if clipping['rich_context']:
        parts.append(clipping['rich_context'])
    else:
        if clipping['text']:
            parts.append(clipping['text'])
        if clipping['surrounding_context']:
            context = clipping['surrounding_context']
            context = context.replace('**»**', '').replace('**«**', '')
            parts.append(context)

    if clipping['chapter_title']:
        parts.append(f"Chapter: {clipping['chapter_title']}")

    parts.append(f"Book: {clipping['book_title']}")
    if clipping['author']:
        parts.append(f"Author: {clipping['author']}")

    return '\n'.join(parts)


def deduplicate_clippings(clippings: list[dict]) -> list[dict]:
    """Merge clippings whose rich_context blocks overlap >50%.

    When two highlights are close together in a book, their ~20K char windows
    overlap significantly. We keep one and merge the highlight texts.
    """
    if not clippings:
        return clippings

    # Group by book
    by_book = {}
    for c in clippings:
        by_book.setdefault(c['book_id'], []).append(c)

    result = []
    for book_id, book_clips in by_book.items():
        # Sort by rich_context_start
        book_clips.sort(key=lambda c: c.get('rich_context_start') or 0)

        merged = []
        for clip in book_clips:
            rc_start = clip.get('rich_context_start')
            rc_end = clip.get('rich_context_end')

            if not rc_start or not rc_end:
                merged.append(clip)
                continue

            # Check overlap with last merged
            if merged and merged[-1].get('rich_context_start') and merged[-1].get('rich_context_end'):
                prev = merged[-1]
                prev_start, prev_end = prev['rich_context_start'], prev['rich_context_end']
                overlap_start = max(rc_start, prev_start)
                overlap_end = min(rc_end, prev_end)
                overlap = max(0, overlap_end - overlap_start)
                smaller_len = min(rc_end - rc_start, prev_end - prev_start)

                if smaller_len > 0 and overlap / smaller_len > MERGE_OVERLAP_RATIO:
                    # Skip this one — the previous golden nugget already covers it
                    # But store the extra highlight ID in metadata
                    if 'merged_ids' not in prev:
                        prev['merged_ids'] = []
                    prev['merged_ids'].append(str(clip['id']))
                    continue

            merged.append(clip)

        result.extend(merged)

    return result


def index_clippings(full_reindex: bool = False, book_id: int | None = None) -> dict:
    """Build or update the vector index with Gemini embeddings."""
    if not DB_PATH.exists():
        return {'error': 'Database not found. Run sync.py first.'}

    gemini_client = get_gemini_client()
    chroma_client = get_chroma_client()

    if full_reindex:
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            print("Deleted existing collection.")
        except Exception:
            pass

    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    existing = collection.get()
    indexed_ids = set(existing['ids']) if existing['ids'] else set()
    print(f"Already indexed: {len(indexed_ids)} clippings")

    # Load clippings from SQLite
    conn = sqlite3.Connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    book_filter = "AND c.book_id = ?" if book_id else ""
    params = (book_id,) if book_id else ()

    cursor.execute(f"""
        SELECT
            c.id, c.text, c.surrounding_context, c.rich_context,
            c.rich_context_start, c.rich_context_end,
            c.matched_char_start, c.matched_char_end,
            c.page, c.position_start, c.date, c.note_text,
            b.id as book_id, b.title as book_title, b.author,
            b.summary as book_summary,
            ch.title as chapter_title, ch.chapter_number
        FROM clippings c
        JOIN books b ON c.book_id = b.id
        LEFT JOIN chapters ch ON c.chapter_id = ch.id
        WHERE c.type = 'highlight' AND c.text IS NOT NULL AND c.text != ''
        {book_filter}
    """, params)

    clippings = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Deduplicate overlapping golden nuggets
    original_count = len(clippings)
    clippings = deduplicate_clippings(clippings)
    deduped = original_count - len(clippings)
    if deduped > 0:
        print(f"Deduplicated: {deduped} overlapping blocks merged")

    # Filter to new only
    if full_reindex:
        new_clippings = clippings
    else:
        new_clippings = [c for c in clippings if str(c['id']) not in indexed_ids]

    print(f"Total highlights: {original_count}")
    print(f"After dedup: {len(clippings)}")
    print(f"New to index: {len(new_clippings)}")

    if not new_clippings:
        return {'indexed': 0, 'total': len(indexed_ids), 'message': 'Index is up to date.'}

    # Process in batches with retry + backoff for rate limits
    batch_size = 20  # Smaller batches to avoid rate limits
    stats = {'indexed': 0, 'failed': 0, 'deduplicated': deduped}

    for i in range(0, len(new_clippings), batch_size):
        batch = new_clippings[i:i + batch_size]

        documents = []
        metadatas = []
        ids = []

        for clipping in batch:
            doc = build_document(clipping)
            documents.append(doc)

            metadata = {
                'book_id': clipping['book_id'],
                'book_title': clipping['book_title'],
                'author': clipping['author'] or '',
                'chapter_title': clipping['chapter_title'] or '',
                'chapter_number': clipping['chapter_number'] or 0,
                'page': clipping['page'] or 0,
                'date': clipping['date'] or '',
                'has_note': bool(clipping['note_text']),
                'has_rich_context': bool(clipping['rich_context']),
            }
            if clipping.get('merged_ids'):
                metadata['merged_highlight_ids'] = ','.join(clipping['merged_ids'])
            metadatas.append(metadata)
            ids.append(str(clipping['id']))

        batch_num = i // batch_size + 1
        total_batches = (len(new_clippings) + batch_size - 1) // batch_size
        print(f"  Embedding batch {batch_num}/{total_batches}...")

        # Retry with exponential backoff
        max_retries = 5
        for attempt in range(max_retries):
            try:
                embeddings = get_embeddings(gemini_client, documents)
                collection.add(
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    ids=ids
                )
                stats['indexed'] += len(batch)
                break
            except Exception as e:
                if '429' in str(e) and attempt < max_retries - 1:
                    wait = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
                    print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                else:
                    print(f"  Error: {e}")
                    stats['failed'] += len(batch)
                    break

        # Small delay between batches to stay under rate limits
        if stats['indexed'] > 0 and i + batch_size < len(new_clippings):
            time.sleep(2)

    stats['total'] = len(indexed_ids) + stats['indexed']
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build vector index with Gemini embeddings')
    parser.add_argument('--full', action='store_true', help='Full reindex (delete and rebuild)')
    parser.add_argument('--book', type=int, help='Index only this book_id')
    args = parser.parse_args()

    if args.full:
        print("Full re-index with Gemini Embedding 2...")
    else:
        print("Updating vector index...")

    result = index_clippings(full_reindex=args.full, book_id=args.book)

    if 'error' in result:
        print(f"Error: {result['error']}")
        exit(1)

    print(f"\nIndexing complete!")
    print(f"  Indexed this run: {result['indexed']}")
    print(f"  Total in index: {result['total']}")
    if result.get('deduplicated'):
        print(f"  Deduplicated: {result['deduplicated']}")
    if result.get('failed'):
        print(f"  Failed: {result['failed']}")
