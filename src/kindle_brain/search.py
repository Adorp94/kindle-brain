"""
Semantic search for Kindle clippings using Gemini Embedding 2.
Searches golden nuggets (rich context blocks) for deep semantic matches.
"""

import chromadb
from chromadb.config import Settings

from kindle_brain.config import EMBEDDING_MODEL, COLLECTION_NAME, get_gemini_client
from kindle_brain.db import get_connection
from kindle_brain.paths import db_path, vectordb_dir


def get_chroma_client():
    """Get ChromaDB client with persistent storage."""
    return chromadb.PersistentClient(
        path=str(vectordb_dir()),
        settings=Settings(anonymized_telemetry=False)
    )


def get_query_embedding(client, query: str) -> list[float]:
    """Get embedding for a search query."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
    )
    return response.embeddings[0].values


def diversify_results(
    results: list[dict], max_per_book: int = 3, max_total: int = 10
) -> list[dict]:
    """Cap results per book using greedy round-robin selection."""
    if not results:
        return []

    by_book: dict[str, list[dict]] = {}
    for r in results:
        key = r.get('book_title', '')
        by_book.setdefault(key, []).append(r)

    for key in by_book:
        by_book[key].sort(key=lambda x: x.get('score', 0), reverse=True)

    diverse = []
    for round_idx in range(max_per_book):
        for key in by_book:
            if round_idx < len(by_book[key]) and len(diverse) < max_total:
                diverse.append(by_book[key][round_idx])

    diverse.sort(key=lambda x: x.get('score', 0), reverse=True)
    return diverse[:max_total]


def semantic_search(query: str, top_k: int = 10, book_filter: str = None) -> list[dict]:
    """Search clippings by semantic similarity using Gemini embeddings."""
    gemini_client = get_gemini_client()
    chroma_client = get_chroma_client()

    try:
        collection = chroma_client.get_collection(COLLECTION_NAME)
    except Exception:
        return []

    query_embedding = get_query_embedding(gemini_client, query)

    where = None
    if book_filter:
        where = {"book_title": {"$eq": book_filter}}

    # Fetch extra results so diversity filter has room
    fetch_k = top_k * 2 if not book_filter else top_k

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_k,
        where=where,
        include=["documents", "metadatas", "distances"]
    )

    if not results['ids'][0]:
        return []

    conn = get_connection(row_factory=True)
    cursor = conn.cursor()

    output = []
    for i, clip_id in enumerate(results['ids'][0]):
        cursor.execute("""
            SELECT
                c.text, c.surrounding_context, c.rich_context,
                c.page, c.date, c.note_text,
                b.title as book_title, b.author, b.summary as book_summary,
                ch.title as chapter_title, ch.chapter_number
            FROM clippings c
            JOIN books b ON c.book_id = b.id
            LEFT JOIN chapters ch ON c.chapter_id = ch.id
            WHERE c.id = ?
        """, (clip_id,))

        row = cursor.fetchone()
        if row:
            distance = results['distances'][0][i]
            score = 1 - distance

            output.append({
                'score': round(score, 4),
                'text': row['text'],
                'surrounding_context': row['surrounding_context'],
                'rich_context': row['rich_context'],
                'page': row['page'],
                'date': row['date'],
                'note_text': row['note_text'],
                'book_title': row['book_title'],
                'author': row['author'],
                'book_summary': row['book_summary'],
                'chapter_title': row['chapter_title'],
                'chapter_number': row['chapter_number'],
            })

    conn.close()

    # Apply diversity cap unless filtering by a single book
    if not book_filter:
        output = diversify_results(output, max_per_book=3, max_total=top_k)

    return output


def get_book_clippings(book_title: str) -> list[dict]:
    """Get all clippings from a specific book."""
    conn = get_connection(row_factory=True)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.text, c.surrounding_context, c.rich_context,
            c.page, c.date, c.note_text,
            b.title as book_title, b.author, b.summary as book_summary,
            ch.title as chapter_title, ch.chapter_number
        FROM clippings c
        JOIN books b ON c.book_id = b.id
        LEFT JOIN chapters ch ON c.chapter_id = ch.id
        WHERE c.type = 'highlight' AND b.title LIKE ?
        ORDER BY c.position_start
    """, (f"%{book_title}%",))

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def list_books() -> list[dict]:
    """List all books with clipping counts."""
    conn = get_connection(row_factory=True)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            b.title, b.author, b.summary,
            COUNT(c.id) as clipping_count,
            SUM(CASE WHEN c.rich_context IS NOT NULL THEN 1 ELSE 0 END) as rich_count,
            MIN(c.date) as first_highlight, MAX(c.date) as last_highlight
        FROM books b
        LEFT JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
        GROUP BY b.id
        HAVING clipping_count > 0
        ORDER BY clipping_count DESC
    """)

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_stats() -> dict:
    """Get database statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}
    cursor.execute("SELECT COUNT(*) FROM books")
    stats['total_books'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings")
    stats['total_clippings'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'highlight'")
    stats['total_highlights'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'note'")
    stats['total_notes'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings WHERE rich_context IS NOT NULL")
    stats['golden_nuggets'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM clippings WHERE surrounding_context IS NOT NULL")
    stats['enriched_clippings'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM books WHERE summary IS NOT NULL")
    stats['books_with_summaries'] = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(date), MAX(date) FROM clippings WHERE date IS NOT NULL")
    date_range = cursor.fetchone()
    stats['date_range'] = {'first': date_range[0], 'last': date_range[1]}

    conn.close()
    return stats


def format_result(result: dict, index: int) -> str:
    """Format a single search result for display."""
    lines = []
    lines.append(f"## Result {index}" + (f" (Score: {result['score']})" if 'score' in result else ""))
    lines.append(f"**Book**: {result['book_title']}" + (f" ({result['author']})" if result['author'] else ""))

    if result.get('chapter_title'):
        chapter_info = f"Chapter {result['chapter_number']}" if result.get('chapter_number') else ""
        lines.append(f"**Chapter**: {chapter_info} — {result['chapter_title']}")

    # Show the highlight text
    lines.append(f"**Highlight**: {result['text']}")

    if result.get('surrounding_context'):
        lines.append(f"**Context**: {result['surrounding_context']}")

    meta_parts = []
    if result.get('date'):
        meta_parts.append(f"Date: {result['date'][:10]}")
    if result.get('page'):
        meta_parts.append(f"Page {result['page']}")
    if result.get('rich_context'):
        meta_parts.append(f"Golden Nugget: {len(result['rich_context'])} chars")
    if meta_parts:
        lines.append(f"**{' | '.join(meta_parts)}**")

    if result.get('note_text'):
        lines.append(f"**Note**: {result['note_text']}")

    return '\n'.join(lines)
